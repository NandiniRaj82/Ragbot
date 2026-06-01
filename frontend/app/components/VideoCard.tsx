"use client";

import Image from "next/image";
import { VideoMetadata } from "@/lib/api";

interface VideoCardProps extends VideoMetadata {
  label: "A" | "B";
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toString();
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function VideoCard(props: VideoCardProps) {
  const {
    label,
    title,
    creator,
    follower_count,
    views,
    likes,
    comments,
    engagement_rate,
    hashtags,
    upload_date,
    duration_seconds,
    thumbnail_url,
  } = props;

  const colorClass = label === "A" ? "video-a" : "video-b";

  return (
    <div className={`video-card ${colorClass}`}>
      {/* Label badge */}
      <div className={`video-label-badge ${colorClass}`}>Video {label}</div>

      {/* Thumbnail */}
      <div className="video-thumbnail-wrapper">
        {thumbnail_url ? (
          <Image
            src={thumbnail_url}
            alt={title}
            fill
            className="video-thumbnail"
            unoptimized
          />
        ) : (
          <div className="video-thumbnail-placeholder">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="currentColor">
              <path d="M8 5v14l11-7z" />
            </svg>
          </div>
        )}
        {/* Duration chip */}
        <div className="video-duration">{formatDuration(duration_seconds)}</div>
      </div>

      {/* Card body */}
      <div className="video-card-body">
        {/* Title */}
        <h3 className="video-title">{title}</h3>

        {/* Creator row */}
        <div className="video-creator-row">
          <div className="creator-avatar">{creator.charAt(0).toUpperCase()}</div>
          <div className="creator-info">
            <span className="creator-name">{creator}</span>
            <span className="creator-followers">
              {formatNumber(follower_count)} followers
            </span>
          </div>
        </div>

        {/* Engagement rate — hero stat */}
        <div className={`engagement-rate-card ${colorClass}`}>
          <div className="engagement-rate-value">
            {engagement_rate.toFixed(2)}%
          </div>
          <div className="engagement-rate-label">Engagement Rate</div>
        </div>

        {/* Stats row */}
        <div className="stats-row">
          <div className="stat-item">
            <span className="stat-icon">👁</span>
            <span className="stat-value">{formatNumber(views)}</span>
            <span className="stat-label">Views</span>
          </div>
          <div className="stat-item">
            <span className="stat-icon">❤️</span>
            <span className="stat-value">{formatNumber(likes)}</span>
            <span className="stat-label">Likes</span>
          </div>
          <div className="stat-item">
            <span className="stat-icon">💬</span>
            <span className="stat-value">{formatNumber(comments)}</span>
            <span className="stat-label">Comments</span>
          </div>
        </div>

        {/* Hashtags */}
        {hashtags.length > 0 && (
          <div className="hashtag-list">
            {hashtags.slice(0, 6).map((tag, i) => (
              <span key={`${tag}-${i}`} className={`hashtag-chip ${colorClass}`}>
                #{tag}
              </span>
            ))}
          </div>

        )}

        {/* Footer meta */}
        <div className="video-meta-footer">
          <span className="meta-date">📅 {upload_date}</span>
        </div>
      </div>
    </div>
  );
}
