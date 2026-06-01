"use client";

import { useState, useCallback } from "react";
import {
  startIngestJob,
  cancelJob,
  IngestResult,
  TranscriptInfo,
} from "@/lib/api";
import { useJobPolling } from "@/lib/hooks/useJobPolling";

interface IngestFormProps {
  onIngestComplete: (data: IngestResult) => void;
}

// All processing stages in order
const STAGES = [
  { key: "validating", label: "Validating URLs" },
  { key: "fetching_metadata", label: "Fetching video metadata" },
  { key: "downloading_audio", label: "Downloading audio" },
  { key: "transcribing", label: "Extracting transcript" },
  { key: "chunking", label: "Chunking transcript" },
  { key: "embedding", label: "Generating embeddings" },
  { key: "storing", label: "Storing in vector database" },
  { key: "completed", label: "Ready to chat" },
];

const STAGE_KEYS = STAGES.map((s) => s.key);

const LANGUAGE_OPTIONS = [
  { code: "", label: "Auto-detect (recommended)" },
  { code: "en", label: "English" },
  { code: "hi", label: "Hindi" },
  { code: "te", label: "Telugu" },
  { code: "ta", label: "Tamil" },
  { code: "kn", label: "Kannada" },
  { code: "ml", label: "Malayalam" },
  { code: "bn", label: "Bengali" },
  { code: "mr", label: "Marathi" },
  { code: "gu", label: "Gujarati" },
  { code: "pa", label: "Punjabi" },
  { code: "ur", label: "Urdu" },
  { code: "ar", label: "Arabic" },
  { code: "es", label: "Spanish" },
  { code: "fr", label: "French" },
  { code: "de", label: "German" },
  { code: "ja", label: "Japanese" },
  { code: "ko", label: "Korean" },
  { code: "zh", label: "Chinese" },
  { code: "ru", label: "Russian" },
  { code: "pt", label: "Portuguese" },
];

const SOURCE_LABELS: Record<string, string> = {
  manual: "Manual captions",
  "auto-generated": "Auto-generated",
  translated: "Translated",
  whisper: "Whisper AI",
};

const SOURCE_COLORS: Record<string, string> = {
  manual: "badge-manual",
  "auto-generated": "badge-auto",
  translated: "badge-translated",
  whisper: "badge-whisper",
};

function TranscriptBadge({
  label,
  info,
}: {
  label: string;
  info: TranscriptInfo;
}) {
  return (
    <div className="transcript-badge">
      <span className="transcript-badge-label">Video {label}</span>
      <span className={`transcript-source-chip ${SOURCE_COLORS[info.source] ?? ""}`}>
        {SOURCE_LABELS[info.source] ?? info.source}
      </span>
      <span className="transcript-lang">
        {info.language_name} ({info.language})
        {!info.is_original && " · translated"}
      </span>
    </div>
  );
}

function generateSessionId(): string {
  return `session_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`;
}

export default function IngestForm({ onIngestComplete }: IngestFormProps) {
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [instagramUrl, setInstagramUrl] = useState("");
  const [preferredLanguage, setPreferredLanguage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [completedResult, setCompletedResult] = useState<IngestResult | null>(null);

  const handleComplete = useCallback(
    (jobStatus: { result: IngestResult | null }) => {
      if (jobStatus.result) {
        setCompletedResult(jobStatus.result);
        onIngestComplete(jobStatus.result);
      }
    },
    [onIngestComplete]
  );

  const handleError = useCallback((err: string) => {
    setError(err);
    setJobId(null);
  }, []);

  const { status, isPolling } = useJobPolling({
    jobId,
    interval: 1500,
    onComplete: handleComplete,
    onError: handleError,
  });

  const isProcessing = isPolling || isSubmitting;
  const currentStage = status?.stage || null;
  const progress = status?.progress || 0;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!youtubeUrl.trim() || !instagramUrl.trim()) return;

    setError(null);
    setCompletedResult(null);
    setIsSubmitting(true);

    const sessionId = generateSessionId();

    try {
      const response = await startIngestJob(
        youtubeUrl.trim(),
        instagramUrl.trim(),
        sessionId,
        preferredLanguage || undefined,
      );
      setJobId(response.job_id);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unexpected error.";
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCancel = async () => {
    if (jobId) {
      try {
        await cancelJob(jobId);
      } catch { /* ignore */ }
      setJobId(null);
    }
  };

  const handleRetry = () => {
    setError(null);
    setJobId(null);
    setCompletedResult(null);
  };

  // Determine which stages are done/active
  const getStageState = (stageKey: string) => {
    if (!currentStage) return "pending";
    if (currentStage === "failed") return "pending";
    if (currentStage === "completed" || stageKey === currentStage) {
      const currentIdx = STAGE_KEYS.indexOf(currentStage);
      const stageIdx = STAGE_KEYS.indexOf(stageKey);
      if (stageIdx < currentIdx) return "done";
      if (stageIdx === currentIdx) return currentStage === "completed" ? "done" : "active";
    }
    const currentIdx = STAGE_KEYS.indexOf(currentStage);
    const stageIdx = STAGE_KEYS.indexOf(stageKey);
    if (stageIdx < currentIdx) return "done";
    if (stageIdx === currentIdx) return "active";
    return "pending";
  };

  return (
    <div className="ingest-form-card">
      <div className="ingest-form-header">
        <div className="ingest-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
            <path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z" />
          </svg>
        </div>
        <div>
          <h2 className="ingest-form-title">Analyze Videos</h2>
          <p className="ingest-form-subtitle">
            Compare a YouTube and Instagram video side-by-side
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="ingest-form">
        <div className="form-field">
          <label htmlFor="youtube-url" className="form-label">
            <span className="label-badge youtube">YT</span>
            YouTube URL
          </label>
          <input
            id="youtube-url"
            type="url"
            className="form-input"
            placeholder="https://www.youtube.com/watch?v=..."
            value={youtubeUrl}
            onChange={(e) => setYoutubeUrl(e.target.value)}
            disabled={isProcessing}
            required
          />
        </div>

        <div className="form-field">
          <label htmlFor="instagram-url" className="form-label">
            <span className="label-badge instagram">IG</span>
            Instagram Reel URL
          </label>
          <input
            id="instagram-url"
            type="url"
            className="form-input"
            placeholder="https://www.instagram.com/reel/..."
            value={instagramUrl}
            onChange={(e) => setInstagramUrl(e.target.value)}
            disabled={isProcessing}
            required
          />
        </div>

        <div className="form-field">
          <label htmlFor="lang-select" className="form-label">
            <span className="label-badge lang">🌐</span>
            YouTube transcript language
          </label>
          <select
            id="lang-select"
            className="form-input form-select"
            value={preferredLanguage}
            onChange={(e) => setPreferredLanguage(e.target.value)}
            disabled={isProcessing}
          >
            {LANGUAGE_OPTIONS.map(({ code, label }) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
        </div>

        {/* Processing Stages */}
        {(isPolling || completedResult) && (
          <div className="processing-stages">
            {STAGES.map((stage) => {
              const state = getStageState(stage.key);
              return (
                <div
                  key={stage.key}
                  className={`stage-item ${state}`}
                >
                  <div className="stage-indicator">
                    {state === "done" ? "✓" : state === "active" ? "●" : ""}
                  </div>
                  <span>{stage.label}</span>
                </div>
              );
            })}

            {/* Progress bar */}
            {isPolling && (
              <div className="progress-bar-container">
                <div className="progress-bar-track">
                  <div
                    className="progress-bar-fill"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <div className="progress-label">
                  <span>{status?.stage_label || "Processing..."}</span>
                  <span>{progress}%</span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Transcript provenance badges */}
        {completedResult && (completedResult.transcript_a_info || completedResult.transcript_b_info) && (
          <div className="transcript-badges">
            {completedResult.transcript_a_info && (
              <TranscriptBadge label="A" info={completedResult.transcript_a_info} />
            )}
            {completedResult.transcript_b_info && (
              <TranscriptBadge label="B" info={completedResult.transcript_b_info} />
            )}
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="ingest-error" role="alert">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z" />
            </svg>
            <div>
              {error}
              <div style={{ marginTop: "8px" }}>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleRetry}
                >
                  Try again
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Action buttons */}
        <div style={{ display: "flex", gap: "8px" }}>
          <button
            type="submit"
            className="ingest-submit-btn"
            style={{ flex: 1 }}
            disabled={isProcessing || !youtubeUrl.trim() || !instagramUrl.trim()}
          >
            {isSubmitting ? (
              <>
                <div className="btn-spinner" />
                Submitting...
              </>
            ) : isPolling ? (
              <>
                <div className="btn-spinner" />
                Processing...
              </>
            ) : completedResult ? (
              "Re-analyze Videos"
            ) : (
              "Analyze Videos →"
            )}
          </button>

          {isPolling && (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleCancel}
            >
              Cancel
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
