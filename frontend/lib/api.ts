// ---------------------------------------------------------------------------
// API base URL — resolves dynamically at runtime.
//
// In local development (localhost), it calls the backend directly on port 8000.
// On deployed sites, it returns a relative URL ("") so Next.js middleware
// can dynamically proxy the requests to the backend at runtime.
// ---------------------------------------------------------------------------
function resolveApiBase(): string {
  if (typeof window !== "undefined") {
    const h = window.location.hostname;
    if (h === "localhost" || h === "127.0.0.1") {
      return "http://localhost:8000";
    }

    // Dynamic Resolution: Automatically derive backend URL from frontend URL
    // e.g. "ragbot-frontend-production.up.railway.app" -> "https://ragbot-backend-production.up.railway.app"
    if (h.includes("-frontend-")) {
      return "https://" + h.replace("-frontend-", "-backend-");
    }
  }
  return "";
}

export const API_BASE = resolveApiBase();

// ---------------------------------------------------------------------------
// TypeScript interfaces matching backend Pydantic models
// ---------------------------------------------------------------------------

export interface VideoMetadata {
  video_id: string; // "A" or "B"
  url: string;
  title: string;
  creator: string;
  follower_count: number;
  views: number;
  likes: number;
  comments: number;
  engagement_rate: number;
  hashtags: string[];
  upload_date: string;
  duration_seconds: number;
  thumbnail_url: string;
}

export type TranscriptSource = "manual" | "auto-generated" | "translated" | "whisper";

export interface TranscriptInfo {
  language: string;
  language_name: string;
  source: TranscriptSource;
  is_original: boolean;
  video_id_yt: string;
}

// Job-based ingest response (returned immediately)
export interface IngestJobResponse {
  job_id: string;
  session_id: string;
  status: "accepted";
}

// Job status (returned from polling)
export interface JobStatus {
  job_id: string;
  session_id: string;
  stage: string;
  stage_label: string;
  progress: number;
  error: string | null;
  error_stage: string | null;
  result: IngestResult | null;
  created_at: number;
  updated_at: number;
}

export interface IngestResult {
  session_id: string;
  video_a: VideoMetadata;
  video_b: VideoMetadata;
  status: string;
  transcript_a_info?: TranscriptInfo;
  transcript_b_info?: TranscriptInfo;
}

export interface SourceCitation {
  video_id: string;
  chunk_index: number;
  chunk_text: string;
}

// ---------------------------------------------------------------------------
// RAG Evaluation Metrics
// ---------------------------------------------------------------------------

export interface RAGMetrics {
  avg_similarity: number;
  top_similarity: number;
  lowest_similarity: number;
  num_chunks_used: number;
  video_a_chunks: number;
  video_b_chunks: number;
  retrieval_time_ms: number;
  generation_time_ms: number;
}

// ---------------------------------------------------------------------------
// SSE Event Types
// ---------------------------------------------------------------------------

export interface ChatTokenEvent {
  token: string;
}

export interface ChatDoneEvent {
  done: true;
  sources: SourceCitation[];
  metrics?: RAGMetrics;
}

export interface ChatErrorEvent {
  error: string;
}

// ---------------------------------------------------------------------------
// Feedback
// ---------------------------------------------------------------------------

export interface FeedbackRequest {
  session_id: string;
  message_id: string;
  rating: "up" | "down";
  comment?: string;
}

export interface FeedbackResponse {
  status: "recorded";
  rating: "up" | "down";
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * POST /api/ingest — submit two video URLs. Returns a job_id immediately.
 * The backend processes in the background. Use pollJobStatus() to track progress.
 */
export async function startIngestJob(
  youtubeUrl: string,
  instagramUrl: string,
  sessionId: string,
  preferredLanguage?: string,
): Promise<IngestJobResponse> {
  const body: Record<string, string> = {
    youtube_url: youtubeUrl,
    instagram_url: instagramUrl,
    session_id: sessionId,
  };
  if (preferredLanguage) body.preferred_language = preferredLanguage;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (networkErr) {
    throw new Error(
      "Cannot reach the backend server. Is it running on port 8000?"
    );
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const errBody = await res.json();
      detail = errBody.detail || errBody.error || detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }

  return (await res.json()) as IngestJobResponse;
}

/**
 * GET /api/jobs/{jobId} — poll the status of an ingest job.
 */
export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
  if (!res.ok) {
    throw new Error(`Job status check failed: HTTP ${res.status}`);
  }
  return (await res.json()) as JobStatus;
}

/**
 * DELETE /api/jobs/{jobId} — cancel a running ingest job.
 */
export async function cancelJob(jobId: string): Promise<void> {
  await fetch(`${API_BASE}/api/jobs/${jobId}`, { method: "DELETE" });
}

/**
 * POST /api/chat — open an SSE stream for RAG chat.
 */
export async function streamChat(
  query: string,
  sessionId: string,
  onToken: (token: string) => void,
  onDone: (sources: SourceCitation[], metrics?: RAGMetrics) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, session_id: sessionId }),
      signal,
    });
  } catch (networkErr) {
    if (networkErr instanceof DOMException && networkErr.name === "AbortError") {
      throw networkErr;
    }
    throw new Error(
      "Cannot reach the backend server. Is it running on port 8000?"
    );
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const errBody = await res.json();
      detail = errBody.detail || errBody.error || detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }

  if (!res.body) {
    throw new Error("Response body is null — SSE stream unavailable.");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() ?? "";

      for (const event of events) {
        const line = event.trim();
        if (!line.startsWith("data:")) continue;

        const jsonStr = line.slice("data:".length).trim();
        if (!jsonStr) continue;

        let parsed: ChatTokenEvent | ChatDoneEvent | ChatErrorEvent;
        try {
          parsed = JSON.parse(jsonStr);
        } catch {
          continue;
        }

        if ("error" in parsed) {
          throw new Error(parsed.error);
        } else if ("done" in parsed && parsed.done) {
          onDone(parsed.sources, parsed.metrics);
          return;
        } else if ("token" in parsed) {
          onToken(parsed.token);
        }
      }
    }
  } finally {
    try {
      reader.releaseLock();
    } catch { /* reader may already be released */ }
  }
}

/**
 * POST /api/feedback — submit thumbs-up/down rating for a chat response.
 */
export async function submitFeedback(
  feedback: FeedbackRequest,
): Promise<FeedbackResponse> {
  const res = await fetch(`${API_BASE}/api/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(feedback),
  });

  if (!res.ok) {
    throw new Error(`Feedback submission failed: HTTP ${res.status}`);
  }

  return (await res.json()) as FeedbackResponse;
}

/**
 * POST /api/summary — stream an AI-generated comparison summary.
 */
export async function streamSummary(
  sessionId: string,
  onToken: (token: string) => void,
  onDone: () => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
      signal,
    });
  } catch (networkErr) {
    if (networkErr instanceof DOMException && networkErr.name === "AbortError") {
      throw networkErr;
    }
    throw new Error("Cannot reach the backend for summary generation.");
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const errBody = await res.json();
      detail = errBody.detail || errBody.error || detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }

  if (!res.body) {
    throw new Error("Response body is null — SSE stream unavailable.");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() ?? "";

      for (const event of events) {
        const line = event.trim();
        if (!line.startsWith("data:")) continue;

        const jsonStr = line.slice("data:".length).trim();
        if (!jsonStr) continue;

        let parsed: { token?: string; done?: boolean };
        try {
          parsed = JSON.parse(jsonStr);
        } catch {
          continue;
        }

        if (parsed.done) {
          onDone();
          return;
        } else if (parsed.token) {
          onToken(parsed.token);
        }
      }
    }
  } finally {
    try {
      reader.releaseLock();
    } catch { /* ignore */ }
  }
}
