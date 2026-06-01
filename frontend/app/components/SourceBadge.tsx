"use client";

import { useState } from "react";
import { SourceCitation } from "@/lib/api";

interface SourceBadgeProps {
  sources: SourceCitation[];
}

export default function SourceBadge({ sources }: SourceBadgeProps) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  if (!sources || sources.length === 0) return null;

  const handleToggle = (index: number) => {
    setExpandedIndex((prev) => (prev === index ? null : index));
  };

  return (
    <div className="source-badge-container">
      <p className="source-badge-label">Sources</p>
      <div className="source-badge-list">
        {sources.map((source, index) => (
          <div key={index} className="source-badge-item">
            <button
              className={`source-pill ${expandedIndex === index ? "active" : ""}`}
              onClick={() => handleToggle(index)}
              aria-expanded={expandedIndex === index}
              aria-label={`Video ${source.video_id} Chunk ${source.chunk_index}`}
            >
              <span className={`pill-dot video-${source.video_id.toLowerCase()}`} />
              Video {source.video_id} · Chunk {source.chunk_index}
            </button>
            {expandedIndex === index && (
              <div className="source-popover" role="tooltip">
                <div className="source-popover-header">
                  <span className={`popover-badge video-${source.video_id.toLowerCase()}`}>
                    Video {source.video_id}
                  </span>
                  <span className="popover-chunk">Chunk {source.chunk_index}</span>
                  <button
                    className="popover-close"
                    onClick={() => setExpandedIndex(null)}
                    aria-label="Close"
                  >
                    ✕
                  </button>
                </div>
                <p className="source-popover-text">{source.chunk_text}</p>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
