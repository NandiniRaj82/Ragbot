"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { streamSummary } from "@/lib/api";
import ReactMarkdown from "react-markdown";

interface SummaryCardProps {
  sessionId: string | null;
}

export default function SummaryCard({ sessionId }: SummaryCardProps) {
  const [content, setContent] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [isDone, setIsDone] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const hasStarted = useRef(false);

  const generateSummary = useCallback(async () => {
    if (!sessionId || hasStarted.current) return;
    hasStarted.current = true;
    setIsStreaming(true);
    setError(null);
    setContent("");

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamSummary(
        sessionId,
        (token) => setContent((prev) => prev + token),
        () => {
          setIsStreaming(false);
          setIsDone(true);
        },
        controller.signal,
      );
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof Error ? err.message : "Summary generation failed");
      setIsStreaming(false);
    }
  }, [sessionId]);

  useEffect(() => {
    generateSummary();
    return () => {
      abortRef.current?.abort();
    };
  }, [generateSummary]);

  if (!sessionId) return null;

  return (
    <div className="summary-card">
      <div
        className="summary-header"
        onClick={() => setIsCollapsed(!isCollapsed)}
        role="button"
        tabIndex={0}
        aria-expanded={!isCollapsed}
      >
        <div className="summary-header-left">
          <div className="summary-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z" />
            </svg>
          </div>
          <div>
            <h3 className="summary-title">AI Comparison Summary</h3>
            <p className="summary-subtitle">
              {isStreaming
                ? "Generating insights..."
                : isDone
                ? "Auto-generated executive brief"
                : "Preparing analysis..."}
            </p>
          </div>
        </div>
        <div className="summary-header-right">
          {isStreaming && <div className="summary-pulse" />}
          {isDone && <span className="summary-done-badge">✓ Complete</span>}
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="currentColor"
            className={`summary-chevron ${isCollapsed ? "collapsed" : ""}`}
          >
            <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6z" />
          </svg>
        </div>
      </div>

      {!isCollapsed && (
        <div className="summary-content">
          {error ? (
            <div className="summary-error">
              <span>⚠️</span> {error}
            </div>
          ) : content ? (
            <div className="markdown-content summary-markdown">
              <ReactMarkdown>{content}</ReactMarkdown>
              {isStreaming && <span className="typing-cursor" />}
            </div>
          ) : (
            <div className="summary-loading">
              <div className="summary-skeleton" />
              <div className="summary-skeleton short" />
              <div className="summary-skeleton" />
              <div className="summary-skeleton medium" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
