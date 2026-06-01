"use client";

import Link from "next/link";

export default function LandingPage() {
  return (
    <div className="landing-page">
      {/* Navbar */}
      <nav className="navbar">
        <Link href="/" className="navbar-brand">
          <div className="navbar-logo">R</div>
          <span className="navbar-name">RAGBot</span>
        </Link>
        <div className="navbar-actions">
          <Link href="/login" className="btn btn-secondary btn-sm">
            Log In
          </Link>
          <Link href="/signup" className="btn btn-primary btn-sm">
            Sign Up →
          </Link>
        </div>
      </nav>

      {/* Hero */}
      <section className="hero">
        <div className="hero-badge">
          <span className="hero-badge-dot" />
          Powered by Gemini 2.5 Flash
        </div>
        <h1>Understand any video with AI-powered transcript analysis</h1>
        <p className="hero-subtitle">
          Paste a YouTube and Instagram URL. Get instant transcript extraction,
          engagement metrics, and ask questions grounded in real content.
        </p>
        <div className="hero-actions">
          <Link href="/dashboard" className="btn btn-primary">
            Start Analyzing →
          </Link>
          <a href="#how-it-works" className="btn btn-secondary">
            How it Works
          </a>
        </div>
      </section>

      {/* Features */}
      <section className="features-section">
        <h2>What you get</h2>
        <div className="features-grid">
          <div className="feature-card">
            <div className="feature-icon">📊</div>
            <h3>Side-by-side comparison</h3>
            <p>
              Compare engagement rates, views, likes, and comments between a
              YouTube video and an Instagram Reel in one view.
            </p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">🎯</div>
            <h3>Transcript-grounded answers</h3>
            <p>
              Every answer is backed by actual transcript chunks with clickable
              citations. No hallucination — only facts from your content.
            </p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">🌐</div>
            <h3>Multi-language support</h3>
            <p>
              Supports 20+ languages for YouTube captions. Falls back to local
              Whisper AI transcription for Instagram audio.
            </p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">⚡</div>
            <h3>Real-time streaming</h3>
            <p>
              Responses stream token-by-token via SSE. See the AI thinking in
              real-time, just like ChatGPT.
            </p>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="how-it-works" id="how-it-works">
        <h2>How it works</h2>
        <div className="steps-grid">
          <div className="step-card">
            <div className="step-number">1</div>
            <h3>Paste URLs</h3>
            <p>Enter any YouTube video URL and Instagram Reel URL</p>
          </div>
          <div className="step-card">
            <div className="step-number">2</div>
            <h3>Auto-process</h3>
            <p>We fetch metadata, extract transcripts, and build embeddings</p>
          </div>
          <div className="step-card">
            <div className="step-number">3</div>
            <h3>Ask questions</h3>
            <p>Chat with your videos using AI grounded in real transcript data</p>
          </div>
          <div className="step-card">
            <div className="step-number">4</div>
            <h3>Get insights</h3>
            <p>Receive cited, actionable analytics about content and performance</p>
          </div>
        </div>
      </section>

      {/* Supported Platforms */}
      <section className="features-section">
        <h2>Supported platforms</h2>
        <div className="features-grid">
          <div className="feature-card">
            <div className="feature-icon">▶️</div>
            <h3>YouTube</h3>
            <p>
              Full support for public videos. Automatic caption extraction with
              fallback to Whisper transcription.
            </p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">📱</div>
            <h3>Instagram Reels</h3>
            <p>
              Supports public Reels. Audio is downloaded and transcribed locally
              using Faster-Whisper AI.
            </p>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="cta-section">
        <div className="cta-card">
          <h2>Ready to analyze your videos?</h2>
          <p>No sign-up required. Paste two URLs and start chatting.</p>
          <Link href="/dashboard" className="btn btn-primary">
            Get Started Free →
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="footer">
        <p>
          Built with FastAPI, Next.js, Gemini 2.5 Flash, and ChromaDB. 
          Local embeddings powered by Sentence Transformers.
        </p>
      </footer>
    </div>
  );
}
