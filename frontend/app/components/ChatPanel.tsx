"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { streamChat, submitFeedback, SourceCitation, RAGMetrics } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import SourceBadge from "./SourceBadge";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: SourceCitation[];
  metrics?: RAGMetrics;
  isStreaming?: boolean;
  feedback?: "up" | "down" | null;
}

interface ChatPanelProps {
  sessionId: string | null;
  videoMetadata?: { A?: { title: string }; B?: { title: string } } | null;
}

const SUGGESTED_QUESTIONS = [
  "Why did Video A get more engagement?",
  "Compare the hooks in the first 5 seconds",
  "Suggest improvements for Video B",
  "What topics does each video cover?",
];

function generateId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
}

// ---------------------------------------------------------------------------
// RAG Metrics Display Component
// ---------------------------------------------------------------------------

function RAGMetricsPanel({ metrics }: { metrics: RAGMetrics }) {
  const [expanded, setExpanded] = useState(false);

  const simColor = (sim: number) => {
    if (sim >= 0.8) return "var(--success)";
    if (sim >= 0.6) return "var(--warning)";
    return "var(--error)";
  };

  const simPercent = (sim: number) => Math.round(sim * 100);

  return (
    <div className="rag-metrics-container">
      <button
        className="rag-metrics-toggle"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        <div className="rag-metrics-summary">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" opacity="0.6">
            <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM9 17H7v-7h2v7zm4 0h-2V7h2v10zm4 0h-2v-4h2v4z" />
          </svg>
          <span
            className="rag-sim-badge"
            style={{ color: simColor(metrics.avg_similarity) }}
          >
            {simPercent(metrics.avg_similarity)}% match
          </span>
          <span className="rag-latency">
            {Math.round(metrics.retrieval_time_ms + metrics.generation_time_ms)}ms
          </span>
        </div>
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="currentColor"
          className={`rag-chevron ${expanded ? "expanded" : ""}`}
        >
          <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6z" />
        </svg>
      </button>

      {expanded && (
        <div className="rag-metrics-detail">
          <div className="rag-metrics-grid">
            <div className="rag-metric-item">
              <span className="rag-metric-label">Avg similarity</span>
              <div className="rag-metric-bar-container">
                <div
                  className="rag-metric-bar"
                  style={{
                    width: `${simPercent(metrics.avg_similarity)}%`,
                    background: simColor(metrics.avg_similarity),
                  }}
                />
              </div>
              <span className="rag-metric-value">
                {simPercent(metrics.avg_similarity)}%
              </span>
            </div>
            <div className="rag-metric-item">
              <span className="rag-metric-label">Best chunk</span>
              <div className="rag-metric-bar-container">
                <div
                  className="rag-metric-bar"
                  style={{
                    width: `${simPercent(metrics.top_similarity)}%`,
                    background: simColor(metrics.top_similarity),
                  }}
                />
              </div>
              <span className="rag-metric-value">
                {simPercent(metrics.top_similarity)}%
              </span>
            </div>
            <div className="rag-metric-item">
              <span className="rag-metric-label">Worst chunk</span>
              <div className="rag-metric-bar-container">
                <div
                  className="rag-metric-bar"
                  style={{
                    width: `${simPercent(metrics.lowest_similarity)}%`,
                    background: simColor(metrics.lowest_similarity),
                  }}
                />
              </div>
              <span className="rag-metric-value">
                {simPercent(metrics.lowest_similarity)}%
              </span>
            </div>
          </div>
          <div className="rag-metrics-footer">
            <span className="rag-chunk-dist">
              <span className="rag-chunk-a">{metrics.video_a_chunks} chunks A</span>
              <span className="rag-chunk-sep">·</span>
              <span className="rag-chunk-b">{metrics.video_b_chunks} chunks B</span>
            </span>
            <span className="rag-timing">
              Retrieval {Math.round(metrics.retrieval_time_ms)}ms
              <span className="rag-chunk-sep">·</span>
              Generation {Math.round(metrics.generation_time_ms)}ms
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Feedback Buttons Component
// ---------------------------------------------------------------------------

function FeedbackButtons({
  messageId,
  sessionId,
  currentFeedback,
  onFeedback,
}: {
  messageId: string;
  sessionId: string;
  currentFeedback: "up" | "down" | null;
  onFeedback: (messageId: string, rating: "up" | "down") => void;
}) {
  const [submitting, setSubmitting] = useState(false);

  const handleClick = async (rating: "up" | "down") => {
    if (submitting || currentFeedback === rating) return;
    setSubmitting(true);
    try {
      await submitFeedback({ session_id: sessionId, message_id: messageId, rating });
      onFeedback(messageId, rating);
    } catch {
      // best-effort
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="feedback-buttons">
      <button
        className={`feedback-btn ${currentFeedback === "up" ? "active-up" : ""}`}
        onClick={() => handleClick("up")}
        disabled={submitting}
        title="Good response"
        aria-label="Thumbs up"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
          <path d="M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z" />
        </svg>
      </button>
      <button
        className={`feedback-btn ${currentFeedback === "down" ? "active-down" : ""}`}
        onClick={() => handleClick("down")}
        disabled={submitting}
        title="Poor response"
        aria-label="Thumbs down"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
          <path d="M15 3H6c-.83 0-1.54.5-1.84 1.22l-3.02 7.05c-.09.23-.14.47-.14.73v2c0 1.1.9 2 2 2h6.31l-.95 4.57-.03.32c0 .41.17.79.44 1.06L9.83 23l6.59-6.59c.36-.36.58-.86.58-1.41V5c0-1.1-.9-2-2-2zm4 0v12h4V3h-4z" />
        </svg>
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chat Export Utility
// ---------------------------------------------------------------------------

function exportChatAsMarkdown(
  messages: Message[],
  videoMeta?: { A?: { title: string }; B?: { title: string } } | null,
) {
  const now = new Date().toISOString().slice(0, 19).replace("T", " ");
  let md = `# RAGBot Chat Export\n\n`;
  md += `**Exported at:** ${now}\n\n`;

  if (videoMeta?.A?.title || videoMeta?.B?.title) {
    md += `## Videos Analyzed\n`;
    if (videoMeta?.A?.title) md += `- **Video A:** ${videoMeta.A.title}\n`;
    if (videoMeta?.B?.title) md += `- **Video B:** ${videoMeta.B.title}\n`;
    md += `\n`;
  }

  md += `## Conversation\n\n`;

  for (const msg of messages) {
    if (msg.role === "user") {
      md += `### 🧑 You\n\n${msg.content}\n\n`;
    } else {
      md += `### 🤖 AI Assistant\n\n${msg.content}\n\n`;
      if (msg.metrics) {
        md += `> **RAG Metrics:** ${Math.round(msg.metrics.avg_similarity * 100)}% avg similarity | `;
        md += `${msg.metrics.num_chunks_used} chunks used | `;
        md += `${Math.round(msg.metrics.retrieval_time_ms + msg.metrics.generation_time_ms)}ms total\n\n`;
      }
      if (msg.sources?.length) {
        md += `**Sources:**\n`;
        for (const src of msg.sources) {
          md += `- Video ${src.video_id} · Chunk ${src.chunk_index}: "${src.chunk_text.slice(0, 100)}..."\n`;
        }
        md += `\n`;
      }
    }
    md += `---\n\n`;
  }

  md += `\n*Generated by RAGBot — AI-Powered Social Media Video Analyzer*\n`;
  return md;
}

function downloadMarkdown(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Main ChatPanel Component
// ---------------------------------------------------------------------------

export default function ChatPanel({ sessionId, videoMetadata }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const isDisabled = !sessionId;

  // Auto-scroll to the bottom whenever messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Clean up any in-flight request when the component unmounts
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  const appendToken = useCallback((token: string) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (!last || last.role !== "assistant") return prev;
      const updated = { ...last, content: last.content + token };
      return [...prev.slice(0, -1), updated];
    });
  }, []);

  const finaliseSources = useCallback((sources: SourceCitation[], metrics?: RAGMetrics) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (!last || last.role !== "assistant") return prev;
      const updated = { ...last, sources, metrics, isStreaming: false };
      return [...prev.slice(0, -1), updated];
    });
    setIsStreaming(false);
  }, []);

  const handleFeedback = useCallback((messageId: string, rating: "up" | "down") => {
    setMessages((prev) =>
      prev.map((msg) =>
        msg.id === messageId ? { ...msg, feedback: rating } : msg
      )
    );
  }, []);

  const handleSend = useCallback(
    async (query: string) => {
      if (!sessionId || !query.trim() || isStreaming) return;

      abortControllerRef.current?.abort();
      const controller = new AbortController();
      abortControllerRef.current = controller;

      const userMsg: Message = {
        id: generateId(),
        role: "user",
        content: query.trim(),
      };
      const assistantMsg: Message = {
        id: generateId(),
        role: "assistant",
        content: "",
        isStreaming: true,
        feedback: null,
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setInput("");
      setIsStreaming(true);

      try {
        await streamChat(
          query.trim(),
          sessionId,
          appendToken,
          finaliseSources,
          controller.signal,
        );
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          setIsStreaming(false);
          return;
        }
        const errorText =
          err instanceof Error ? err.message : "Unknown error occurred.";
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (!last || last.role !== "assistant") return prev;
          return [
            ...prev.slice(0, -1),
            { ...last, content: `⚠️ Error: ${errorText}`, isStreaming: false },
          ];
        });
        setIsStreaming(false);
      }
    },
    [sessionId, isStreaming, appendToken, finaliseSources]
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend(input);
    }
  };

  const handleExport = () => {
    if (messages.length === 0) return;
    const md = exportChatAsMarkdown(messages, videoMetadata);
    const timestamp = new Date().toISOString().slice(0, 10);
    downloadMarkdown(md, `ragbot-chat-${timestamp}.md`);
  };

  return (
    <div className={`chat-panel ${isDisabled ? "chat-disabled" : ""}`}>
      {/* Header */}
      <div className="chat-header">
        <div className="chat-header-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z" />
          </svg>
        </div>
        <div>
          <h2 className="chat-header-title">AI Analytics Assistant</h2>
          <p className="chat-header-subtitle">
            {isDisabled
              ? "Ingest videos to start chatting"
              : "Ask anything about your videos"}
          </p>
        </div>
        <div className="chat-header-actions">
          {!isDisabled && messages.length > 0 && (
            <button
              className="btn-icon export-btn"
              onClick={handleExport}
              title="Export chat as Markdown"
              aria-label="Export chat"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z" />
              </svg>
            </button>
          )}
          {!isDisabled && <div className="chat-online-dot" />}
        </div>
      </div>

      {/* Messages */}
      <div className="chat-messages">
        {isDisabled && (
          <div className="chat-empty-state">
            <div className="empty-icon">💬</div>
            <h3>Ready to analyze your videos</h3>
            <p>
              Enter your YouTube and Instagram URLs above, then ask me anything
              about their performance, content strategy, or engagement.
            </p>
          </div>
        )}

        {!isDisabled && messages.length === 0 && (
          <div className="suggested-questions">
            <p className="suggested-label">Suggested questions</p>
            <div className="suggested-list">
              {SUGGESTED_QUESTIONS.map((q) => (
                <button
                  key={q}
                  className="suggested-chip"
                  onClick={() => handleSend(q)}
                  disabled={isStreaming}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`message-wrapper ${msg.role === "user" ? "user" : "assistant"}`}
          >
            {msg.role === "assistant" && (
              <div className="assistant-avatar">AI</div>
            )}
            <div className="message-bubble-group">
              <div
                className={`message-bubble ${msg.role === "user" ? "user-bubble" : "assistant-bubble"}`}
              >
                {msg.role === "assistant" ? (
                  <div className="markdown-content">
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                    {msg.isStreaming && <span className="typing-cursor" />}
                  </div>
                ) : (
                  msg.content
                )}
              </div>

              {/* Source citations */}
              {msg.role === "assistant" && msg.sources && (
                <SourceBadge sources={msg.sources} />
              )}

              {/* RAG Metrics */}
              {msg.role === "assistant" && msg.metrics && !msg.isStreaming && (
                <RAGMetricsPanel metrics={msg.metrics} />
              )}

              {/* Feedback buttons */}
              {msg.role === "assistant" && !msg.isStreaming && msg.content && sessionId && (
                <FeedbackButtons
                  messageId={msg.id}
                  sessionId={sessionId}
                  currentFeedback={msg.feedback ?? null}
                  onFeedback={handleFeedback}
                />
              )}
            </div>
            {msg.role === "user" && (
              <div className="user-avatar">U</div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="chat-input-bar">
        <textarea
          ref={inputRef}
          className="chat-input"
          placeholder={
            isDisabled
              ? "Ingest videos first..."
              : "Ask about hooks, engagement, content strategy..."
          }
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isDisabled || isStreaming}
          rows={1}
          aria-label="Chat message input"
        />
        <button
          className="chat-send-btn"
          onClick={() => handleSend(input)}
          disabled={isDisabled || isStreaming || !input.trim()}
          aria-label="Send message"
        >
          {isStreaming ? (
            <div className="send-spinner" />
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}
