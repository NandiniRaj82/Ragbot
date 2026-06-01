from __future__ import annotations

import chromadb

from app.core.config import settings as app_settings


class VideoVectorStore:
    """
    Thin wrapper around ChromaDB for storing and querying transcript chunks.

    Uses PersistentClient (SQLite backend, fully auto-persisted).
    All chunks share one collection and are filtered at query time by
    `session_id` so different users never see each other's data.
    """

    COLLECTION_NAME = "video_transcripts"

    def __init__(self) -> None:
        # PersistentClient: SQLite backend, data is automatically persisted.
        # No manual persist() call needed; no Settings object needed.
        self._client = chromadb.PersistentClient(
            path=app_settings.CHROMA_DB_PATH,
        )
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upsert(self, chunks: list[dict]) -> None:
        """
        Batch-upsert a list of chunk dicts into the collection.
        Each dict must contain: id, text, embedding, metadata.
        """
        if not chunks:
            return

        self._collection.upsert(
            ids=[c["id"] for c in chunks],
            documents=[c["text"] for c in chunks],
            embeddings=[c["embedding"] for c in chunks],
            metadatas=[c["metadata"] for c in chunks],
        )

    def query(
        self,
        query_embedding: list[float],
        session_id: str,
        n_results: int = 6,
    ) -> list[dict]:
        """
        Retrieve the top-N most similar chunks for the given session.

        Guards against n_results > total collection count, which causes
        ChromaDB to raise an InvalidDimensionException.
        """
        try:
            total = self._collection.count()
        except Exception:
            total = 0

        if total == 0:
            return []

        safe_n = min(n_results, total)

        try:
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=safe_n,
                where={"session_id": session_id},
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            # The where filter may match 0 docs; return empty rather than crash.
            return []

        hits: list[dict] = []
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for doc, meta, dist in zip(documents, metadatas, distances):
            hits.append({"document": doc, "metadata": meta, "distance": dist})

        return hits

    def delete_session(self, session_id: str) -> None:
        """
        Remove all chunks associated with a given session from the collection.
        """
        self._collection.delete(where={"session_id": session_id})


# Module-level singleton — created once on first import.
vector_store = VideoVectorStore()
