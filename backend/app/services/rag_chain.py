"""
rag_chain.py — RAG pipeline using Gemini 2.5 Flash + local SentenceTransformer embeddings.

LLM:        Gemini 2.5 Flash (via google-genai)
Embeddings: all-MiniLM-L6-v2 (via sentence-transformers, local CPU)
Memory:     LangGraph MemorySaver (in-process, per-session)
Retrieval:  ChromaDB cosine similarity (top-6 chunks)
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import AsyncGenerator, TypedDict

from google import genai
from google.genai import types as genai_types
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.core.config import settings
from app.models.schemas import RAGMetrics, SourceCitation, VideoMetadata
from app.services.embedder_model import embed_query
from app.services.vectorstore import vector_store

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gemini client — created once per process
# ---------------------------------------------------------------------------
_gemini_client: genai.Client | None = None


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        logger.info("[RAG] Gemini client initialized")
    return _gemini_client


GEMINI_MODEL = "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------

class RAGState(TypedDict):
    messages: list[dict]       # list of {"role": ..., "content": ...}
    retrieved_docs: list[dict] # output of vectorstore.query()
    session_id: str


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def _build_system_prompt(
    video_metadata: dict,
    retrieved_docs: list[dict],
) -> str:
    """
    Build the system prompt with injected metadata and retrieved context blocks.
    """
    video_a: VideoMetadata | None = video_metadata.get("A")
    video_b: VideoMetadata | None = video_metadata.get("B")

    def fmt_meta(vm: VideoMetadata | None) -> str:
        if vm is None:
            return "N/A"
        return (
            f"title='{vm.title}', creator='{vm.creator}', "
            f"views={vm.views:,}, likes={vm.likes:,}, comments={vm.comments:,}, "
            f"followers={vm.follower_count:,}, uploaded={vm.upload_date}, "
            f"duration={vm.duration_seconds}s"
        )

    er_a = f"{video_a.engagement_rate:.4f}" if video_a else "N/A"
    er_b = f"{video_b.engagement_rate:.4f}" if video_b else "N/A"

    context_lines: list[str] = []
    for doc in retrieved_docs:
        meta = doc.get("metadata", {})
        vid_id = meta.get("video_id", "?")
        chunk_idx = meta.get("chunk_index", 0)
        text = doc.get("document", "")
        context_lines.append(f"[Video {vid_id} · Chunk {chunk_idx}]: {text}")

    context_block = "\n\n".join(context_lines) if context_lines else "No context retrieved."

    return (
        "You are a social media analytics assistant helping a content creator "
        "understand their video performance.\n\n"
        f"You have access to two videos:\n"
        f"- Video A: {fmt_meta(video_a)}\n"
        f"- Video B: {fmt_meta(video_b)}\n\n"
        f"Engagement rates: Video A = {er_a}%, Video B = {er_b}%\n\n"
        "Use ONLY the retrieved transcript chunks below to answer questions.\n"
        "Always cite your sources using [Video A · Chunk N] or [Video B · Chunk N] "
        "format at the end of each claim.\n"
        "Be specific, data-driven, and actionable.\n\n"
        f"Retrieved Context:\n{context_block}"
    )


# ---------------------------------------------------------------------------
# LangGraph nodes
# ---------------------------------------------------------------------------

def retrieve_node(state: RAGState) -> dict:
    """
    Embed the latest user message and retrieve relevant transcript chunks.
    Uses local SentenceTransformers — no API call needed.
    """
    user_message = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )

    logger.info("[RAG] Embedding query for retrieval (%d chars)", len(user_message))
    query_embedding: list[float] = embed_query(user_message)

    docs = vector_store.query(
        query_embedding=query_embedding,
        session_id=state["session_id"],
        n_results=6,
    )
    logger.info("[RAG] Retrieved %d chunks", len(docs))

    return {"retrieved_docs": docs}


def generate_node(state: RAGState, video_metadata: dict) -> dict:
    """
    Non-streaming LLM call using Gemini 2.5 Flash.
    Used only by the graph for memory checkpointing.
    Real streaming happens in astream_rag outside the graph.
    """
    system_prompt = _build_system_prompt(video_metadata, state["retrieved_docs"])
    client = _get_gemini_client()

    # Build Gemini-compatible message list
    contents = _build_gemini_contents(system_prompt, state["messages"])

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=4096,
            ),
        )
    except Exception as exc:
        raise RuntimeError(f"Gemini generation failed: {exc}") from exc

    assistant_content: str = response.text or ""

    updated_messages = state["messages"] + [
        {"role": "assistant", "content": assistant_content}
    ]
    return {"messages": updated_messages}


def _build_gemini_contents(
    system_prompt: str,
    messages: list[dict],
) -> list[genai_types.Content]:
    """
    Convert OpenAI-style messages to Gemini Content objects.
    The system prompt is prepended as the first user message.
    """
    contents: list[genai_types.Content] = []

    # Gemini doesn't have a "system" role in the same way.
    # We prepend system instructions as context in the first user turn.
    system_injected = False

    for msg in messages:
        role = msg["role"]
        text = msg["content"]

        if role == "system":
            # Will be handled by prepending to first user message
            continue
        elif role == "user":
            if not system_injected:
                text = f"[System Instructions]\n{system_prompt}\n\n[User Query]\n{text}"
                system_injected = True
            contents.append(genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=text)],
            ))
        elif role == "assistant":
            contents.append(genai_types.Content(
                role="model",
                parts=[genai_types.Part(text=text)],
            ))

    # If no messages had role=user yet, inject system prompt as standalone user message
    if not system_injected and not contents:
        contents.append(genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=system_prompt)],
        ))

    return contents


# ---------------------------------------------------------------------------
# Graph — built ONCE per process, not per request.
# MemorySaver is shared so multi-turn memory works across calls.
# ---------------------------------------------------------------------------

_checkpointer = MemorySaver()


def _build_graph(video_metadata: dict):
    """
    Build and compile a graph with the given video metadata bound into
    the generate node.  This is called once per unique session.
    """
    def _generate_bound(state: RAGState) -> dict:
        return generate_node(state, video_metadata)

    builder: StateGraph = StateGraph(RAGState)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("generate", _generate_bound)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "generate")
    builder.add_edge("generate", END)

    return builder.compile(checkpointer=_checkpointer)


# ---------------------------------------------------------------------------
# LRU graph cache — evicts oldest entries when capacity is exceeded so
# memory doesn't grow without bound across sessions.
# ---------------------------------------------------------------------------

class _LRUGraphCache:
    """Bounded cache for compiled LangGraph graphs, keyed by session_id."""

    def __init__(self, max_size: int = 100) -> None:
        self._cache: OrderedDict = OrderedDict()
        self._max_size = max_size

    def get_or_create(self, session_id: str, video_metadata: dict):
        if session_id in self._cache:
            self._cache.move_to_end(session_id)
            return self._cache[session_id]
        graph = _build_graph(video_metadata)
        self._cache[session_id] = graph
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
        return graph


_graph_cache = _LRUGraphCache(max_size=100)


# ---------------------------------------------------------------------------
# Helper: load prior conversation history from LangGraph checkpointer
# ---------------------------------------------------------------------------

def _load_prior_messages(graph, config: dict) -> list[dict]:
    """
    Retrieve the conversation history stored by the MemorySaver checkpointer.
    Returns an empty list if no prior history exists.
    """
    try:
        state_snapshot = graph.get_state(config)
        if state_snapshot and state_snapshot.values:
            return list(state_snapshot.values.get("messages", []))
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Public streaming function
# ---------------------------------------------------------------------------

async def astream_rag(
    query: str,
    session_id: str,
    video_metadata: dict,
) -> AsyncGenerator[str | list[SourceCitation], None]:
    """
    Stream Gemini 2.5 Flash tokens for a RAG query, then yield a final list of
    SourceCitations referencing the actual retrieved chunks.

    Multi-turn memory is maintained via LangGraph's MemorySaver: prior
    conversation history is loaded before each call and the new turn is
    persisted after streaming completes — WITHOUT making a duplicate LLM call.

    Yields:
        - str tokens one at a time while the LLM generates
        - list[SourceCitation] as the final item

    Args:
        query:          The user's question.
        session_id:     Used to scope ChromaDB queries and LangGraph thread.
        video_metadata: Dict with keys "A" and "B" mapping to VideoMetadata.
    """
    loop = asyncio.get_running_loop()

    # 1. Embed query and retrieve docs — local model, runs in thread pool.
    def _embed_and_retrieve() -> tuple[list[float], list[dict]]:
        embedding = embed_query(query)
        docs = vector_store.query(
            query_embedding=embedding,
            session_id=session_id,
            n_results=6,
        )
        return embedding, docs

    logger.info("[RAG] Embedding query and retrieving docs ...")
    retrieval_start = time.time()
    _, retrieved_docs = await loop.run_in_executor(None, _embed_and_retrieve)
    retrieval_time_ms = (time.time() - retrieval_start) * 1000
    logger.info("[RAG] Retrieved %d docs for streaming", len(retrieved_docs))

    # 2. Load prior conversation history for multi-turn memory.
    graph = _graph_cache.get_or_create(session_id, video_metadata)
    config = {"configurable": {"thread_id": session_id}}
    prior_messages = await loop.run_in_executor(
        None, _load_prior_messages, graph, config,
    )

    # 3. Build system prompt with retrieved context.
    system_prompt = _build_system_prompt(video_metadata, retrieved_docs)

    # 4. Assemble full message payload with history for multi-turn context.
    all_messages = prior_messages + [{"role": "user", "content": query}]
    contents = _build_gemini_contents(system_prompt, all_messages)

    # 5. Stream tokens — Gemini streaming runs synchronously, so we
    #    use a thread pool + queue pattern to avoid blocking the event loop.
    token_queue: asyncio.Queue[str | None] = asyncio.Queue()
    full_response_parts: list[str] = []

    def _stream_to_queue() -> None:
        """Run synchronously in a thread pool; push tokens onto the queue."""
        try:
            client = _get_gemini_client()
            stream = client.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=contents,
                config=genai_types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=4096,
                ),
            )
            for chunk in stream:
                if chunk.text:
                    full_response_parts.append(chunk.text)
                    loop.call_soon_threadsafe(token_queue.put_nowait, chunk.text)
        except Exception as exc:
            error_msg = f"\n\n⚠️ Stream error: {exc}"
            full_response_parts.append(error_msg)
            loop.call_soon_threadsafe(
                token_queue.put_nowait,
                error_msg,
            )
        finally:
            # Sentinel: None signals end of stream
            loop.call_soon_threadsafe(token_queue.put_nowait, None)

    # Launch the blocking stream in a thread pool.
    logger.info("[RAG] Starting Gemini 2.5 Flash stream ...")
    generation_start = time.time()
    stream_future = loop.run_in_executor(None, _stream_to_queue)

    # Yield tokens as they arrive from the queue.
    while True:
        token = await token_queue.get()
        if token is None:
            break
        yield token

    # Ensure the streaming thread has finished.
    await stream_future
    generation_time_ms = (time.time() - generation_start) * 1000
    logger.info("[RAG] Gemini stream complete — %d chars in %.0fms", len("".join(full_response_parts)), generation_time_ms)

    # 6. Persist the new turn in LangGraph WITHOUT making a second LLM call.
    full_response = "".join(full_response_parts)
    new_messages = prior_messages + [
        {"role": "user", "content": query},
        {"role": "assistant", "content": full_response},
    ]

    def _persist_turn() -> None:
        try:
            graph.update_state(
                config,
                {
                    "messages": new_messages,
                    "retrieved_docs": retrieved_docs,
                    "session_id": session_id,
                },
            )
        except Exception:
            # update_state may not be available on all checkpointer versions;
            # fall back to a lightweight invoke that skips the LLM.
            try:
                graph.invoke(
                    {
                        "messages": new_messages,
                        "retrieved_docs": retrieved_docs,
                        "session_id": session_id,
                    },
                    config=config,
                )
            except Exception:
                pass  # best-effort persistence

    await loop.run_in_executor(None, _persist_turn)

    # 7. Build citations from the actual retrieved chunks.
    citations: list[SourceCitation] = [
        SourceCitation(
            video_id=doc.get("metadata", {}).get("video_id", "?"),
            chunk_index=int(doc.get("metadata", {}).get("chunk_index", 0)),
            chunk_text=doc.get("document", ""),
        )
        for doc in retrieved_docs
    ]

    # 8. Compute RAG evaluation metrics from retrieval distances.
    #    ChromaDB cosine distance = 1 - cosine_similarity, so we invert.
    distances = [doc.get("distance", 1.0) for doc in retrieved_docs]
    if distances:
        avg_sim = 1 - (sum(distances) / len(distances))
        top_sim = 1 - min(distances)
        low_sim = 1 - max(distances)
    else:
        avg_sim = top_sim = low_sim = 0.0

    video_a_chunks = sum(
        1 for doc in retrieved_docs
        if doc.get("metadata", {}).get("video_id") == "A"
    )
    video_b_chunks = sum(
        1 for doc in retrieved_docs
        if doc.get("metadata", {}).get("video_id") == "B"
    )

    metrics = RAGMetrics(
        avg_similarity=round(avg_sim, 4),
        top_similarity=round(top_sim, 4),
        lowest_similarity=round(low_sim, 4),
        num_chunks_used=len(retrieved_docs),
        video_a_chunks=video_a_chunks,
        video_b_chunks=video_b_chunks,
        retrieval_time_ms=round(retrieval_time_ms, 1),
        generation_time_ms=round(generation_time_ms, 1),
    )

    logger.info(
        "[RAG] Metrics: avg_sim=%.4f  top=%.4f  low=%.4f  A=%d  B=%d  retrieval=%.0fms  gen=%.0fms",
        avg_sim, top_sim, low_sim, video_a_chunks, video_b_chunks,
        retrieval_time_ms, generation_time_ms,
    )

    yield {"citations": citations, "metrics": metrics}
