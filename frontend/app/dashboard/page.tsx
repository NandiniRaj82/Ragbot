"use client";

import { useState, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { VideoMetadata, IngestResult } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import IngestForm from "../components/IngestForm";
import VideoCard from "../components/VideoCard";
import ChatPanel from "../components/ChatPanel";
import SummaryCard from "../components/SummaryCard";
import Link from "next/link";

export default function DashboardPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [videoA, setVideoA] = useState<VideoMetadata | null>(null);
  const [videoB, setVideoB] = useState<VideoMetadata | null>(null);

  // Redirect to login if not authenticated (after loading completes)
  useEffect(() => {
    if (!loading && !user) {
      router.push("/login");
    }
  }, [user, loading, router]);

  const handleIngestComplete = useCallback((result: IngestResult) => {
    setSessionId(result.session_id);
    setVideoA(result.video_a);
    setVideoB(result.video_b);
  }, []);

  const handleLogout = async () => {
    await logout();
    router.push("/");
  };

  // Show nothing while checking auth state
  if (loading) {
    return (
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: "100vh",
        color: "var(--text-muted)",
        fontSize: "14px",
      }}>
        Loading...
      </div>
    );
  }

  // If not logged in, don't render (redirect is happening)
  if (!user) return null;

  const videoMetadataForChat =
    videoA && videoB ? { A: videoA, B: videoB } : null;

  return (
    <>
      {/* Top nav */}
      <nav className="navbar" style={{ borderBottom: "1px solid var(--border-default)", background: "var(--bg-primary)" }}>
        <Link href="/" className="navbar-brand">
          <div className="navbar-logo">R</div>
          <span className="navbar-name">RAGBot</span>
        </Link>
        <div className="user-menu">
          <span className="user-email">{user.email}</span>
          <button className="logout-btn" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </nav>

      <main className="app-layout">
        {/* Left column */}
        <div className="left-column">
          <IngestForm onIngestComplete={handleIngestComplete} />

          {videoA && videoB && (
            <>
              <div className="video-cards-grid">
                <VideoCard label="A" {...videoA} />
                <VideoCard label="B" {...videoB} />
              </div>

              {/* AI-generated comparison summary */}
              <SummaryCard sessionId={sessionId} />
            </>
          )}

          {!videoA && !videoB && (
            <div className="placeholder-cards">
              <div className="placeholder-card video-a-placeholder">
                <div className="placeholder-icon">▶️</div>
                <p className="placeholder-label">Video A</p>
                <p className="placeholder-hint">YouTube</p>
              </div>
              <div className="placeholder-card video-b-placeholder">
                <div className="placeholder-icon">📱</div>
                <p className="placeholder-label">Video B</p>
                <p className="placeholder-hint">Instagram Reel</p>
              </div>
            </div>
          )}
        </div>

        {/* Right column — Chat */}
        <div className="right-column">
          <ChatPanel
            sessionId={sessionId}
            videoMetadata={videoMetadataForChat}
          />
        </div>
      </main>
    </>
  );
}
