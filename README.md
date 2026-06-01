# RAGBot — AI-Powered Social Media Video Analyzer

> Compare any YouTube video and Instagram Reel with AI-powered RAG (Retrieval-Augmented Generation) analysis. Get transcript-grounded insights, engagement metrics, and content strategy recommendations.


## Tech Stack

| Component | Technology |
|-----------|-----------|
| **Frontend** | Next.js 14, React, TypeScript |
| **Backend** | FastAPI, Python 3.11+ |
| **LLM** | Google Gemini 2.5 Flash |
| **Embeddings** | Sentence Transformers (all-MiniLM-L6-v2) |
| **Vector Store** | ChromaDB (persistent, local) |
| **Transcription** | YouTube Transcript API + Faster-Whisper (local) |
| **Media** | yt-dlp + FFmpeg |
| **Memory** | LangGraph MemorySaver (multi-turn conversation) |
| **Rate Limiting** | slowapi |

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- FFmpeg installed and on PATH
- Google Gemini API key ([get one here](https://aistudio.google.com/apikey))

### Backend Setup

```bash
cd ragbot/backend

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate 

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# Run the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend Setup

```bash
cd ragbot/frontend

# Install dependencies
npm install

# Run dev server
npm run dev
```

### Usage

1. Open http://localhost:3000
2. Click "Start Analyzing" to go to the dashboard
3. Paste a YouTube video URL and an Instagram Reel URL
4. Select transcript language preference (optional)
5. Click "Analyze Videos"
6. Watch real-time processing stages (validating → metadata → transcript → embedding → storing)
7. Once complete, ask questions in the chat panel

## Features

### Core Pipeline
- **Parallel metadata fetch** — yt-dlp extracts video metadata for both URLs simultaneously
- **Multi-source transcription** — YouTube: manual captions → auto-generated → translated → Whisper fallback. Instagram: yt-dlp audio download → Faster-Whisper
- **Local embeddings** — all-MiniLM-L6-v2 runs on CPU, no API key needed, ~5ms per batch
- **RAG retrieval** — top-6 chunks via ChromaDB cosine similarity
- **Streaming chat** — SSE token-by-token streaming from Gemini 2.5 Flash
- **Multi-turn memory** — LangGraph MemorySaver persists conversation history per session

### Job-Based Architecture
- `POST /api/ingest` returns job_id in <100ms
- Frontend polls `GET /api/jobs/{id}` for real-time progress
- 8 stages with automatic progress percentage
- Cancel button to abort long-running jobs



## API Reference

### `POST /api/ingest`
Submit two video URLs for analysis. Returns a job_id immediately.

**Request:**
```json
{
  "youtube_url": "https://www.youtube.com/watch?v=...",
  "instagram_url": "https://www.instagram.com/reel/...",
  "session_id": "session_abc123",
  "preferred_language": "en"
}
```

**Response:**
```json
{
  "job_id": "job_abc123def456",
  "session_id": "session_abc123",
  "status": "accepted"
}
```

### `GET /api/jobs/{job_id}`
Poll processing status.

**Response:**
```json
{
  "job_id": "job_abc123def456",
  "stage": "transcribing",
  "stage_label": "Extracting transcript",
  "progress": 50,
  "error": null,
  "result": null
}
```

### `POST /api/chat`
SSE-streamed RAG response.

**Request:**
```json
{
  "query": "Why did Video A get more engagement?",
  "session_id": "session_abc123"
}
```

