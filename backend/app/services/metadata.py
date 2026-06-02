from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import urllib.request
import urllib.parse

from app.models.schemas import VideoMetadata

logger = logging.getLogger(__name__)


def extract_youtube_id(url: str) -> str | None:
    patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([^&\s]+)',
        r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([^/?\s]+)',
        r'(?:https?://)?(?:www\.)?youtu\.be/([^/?\s]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def extract_instagram_id(url: str) -> str | None:
    match = re.search(r'instagram\.com/reel/([^/?\s]+)', url)
    if match:
        return match.group(1)
    return None


# ---------------------------------------------------------------------------
# ISO 8601 duration parser (PT1M30S → 90 seconds)
# ---------------------------------------------------------------------------

def _parse_iso_duration(duration_str: str) -> int:
    """Parse ISO 8601 duration string like 'PT1H2M30S' into total seconds."""
    match = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        duration_str or "PT0S",
    )
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


# ---------------------------------------------------------------------------
# Fallback 1: YouTube Data API v3 (needs YOUTUBE_API_KEY — gives FULL real data)
# ---------------------------------------------------------------------------

def _fetch_youtube_api_metadata(
    yt_id: str, video_id: str, url: str
) -> VideoMetadata | None:
    """
    Use YouTube Data API v3 to fetch real metadata.
    Requires YOUTUBE_API_KEY environment variable.
    Returns None if key is not set or API call fails.
    """
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        logger.info("[Metadata] YOUTUBE_API_KEY not set — skipping Data API fallback")
        return None

    api_url = (
        f"https://www.googleapis.com/youtube/v3/videos"
        f"?part=snippet,statistics,contentDetails"
        f"&id={yt_id}"
        f"&key={api_key}"
    )

    try:
        req = urllib.request.Request(
            api_url,
            headers={"User-Agent": "RagBot/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        items = data.get("items", [])
        if not items:
            logger.warning("[Metadata] YouTube Data API returned no items for %s", yt_id)
            return None

        item = items[0]
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        content_details = item.get("contentDetails", {})

        views = int(stats.get("viewCount", 0))
        likes = int(stats.get("likeCount", 0))
        comments = int(stats.get("commentCount", 0))

        duration_seconds = _parse_iso_duration(content_details.get("duration", "PT0S"))
        engagement_rate = round((likes + comments) / views * 100, 4) if views > 0 else 0.0

        # publishedAt is like "2024-01-15T10:30:00Z"
        raw_date = snippet.get("publishedAt", "")[:10]

        hashtags = [tag for tag in snippet.get("tags", []) if isinstance(tag, str)]

        # Get best thumbnail
        thumbs = snippet.get("thumbnails", {})
        thumbnail_url = (
            thumbs.get("maxres", {}).get("url")
            or thumbs.get("high", {}).get("url")
            or thumbs.get("medium", {}).get("url")
            or thumbs.get("default", {}).get("url")
            or f"https://img.youtube.com/vi/{yt_id}/0.jpg"
        )

        vm = VideoMetadata(
            video_id=video_id,
            url=url,
            title=snippet.get("title", "Untitled"),
            creator=snippet.get("channelTitle", "Unknown Creator"),
            follower_count=0,  # Not available from /videos endpoint
            views=views,
            likes=likes,
            comments=comments,
            engagement_rate=engagement_rate,
            hashtags=hashtags,
            upload_date=raw_date or "unknown",
            duration_seconds=duration_seconds,
            thumbnail_url=thumbnail_url,
        )

        logger.info(
            "[Metadata] ✓ YouTube Data API — video_id=%s  title='%s'  views=%d  likes=%d",
            video_id, vm.title[:50], vm.views, vm.likes,
        )
        return vm

    except Exception as exc:
        logger.warning("[Metadata] YouTube Data API fallback failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Fallback 2: YouTube oEmbed API (NO API key needed — gives title + creator)
# ---------------------------------------------------------------------------

def _fetch_youtube_oembed_metadata(
    yt_id: str, video_id: str, url: str
) -> VideoMetadata | None:
    """
    Use YouTube oEmbed API for basic metadata (no API key needed).
    Returns title, creator, and thumbnail — but NOT views/likes/comments.
    """
    oembed_url = (
        f"https://www.youtube.com/oembed"
        f"?url={urllib.parse.quote(url, safe='')}"
        f"&format=json"
    )

    try:
        req = urllib.request.Request(
            oembed_url,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        thumbnail_url = (
            data.get("thumbnail_url")
            or f"https://img.youtube.com/vi/{yt_id}/0.jpg"
        )

        vm = VideoMetadata(
            video_id=video_id,
            url=url,
            title=data.get("title", "YouTube Video"),
            creator=data.get("author_name", "YouTube Creator"),
            follower_count=0,
            views=0,       # oEmbed doesn't provide these
            likes=0,
            comments=0,
            engagement_rate=0.0,
            hashtags=[],
            upload_date="unknown",
            duration_seconds=60,
            thumbnail_url=thumbnail_url,
        )

        logger.info(
            "[Metadata] ✓ YouTube oEmbed — title='%s'  creator='%s'  (no view/like stats available)",
            vm.title[:50], vm.creator,
        )
        return vm

    except Exception as exc:
        logger.warning("[Metadata] YouTube oEmbed fallback failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Fallback for Instagram: oEmbed API
# ---------------------------------------------------------------------------

def _fetch_instagram_oembed_metadata(
    url: str, video_id: str
) -> VideoMetadata | None:
    """
    Try the Instagram oEmbed endpoint for basic metadata.
    Supports INSTAGRAM_ACCESS_TOKEN for Meta Graph API.
    """
    access_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
    if access_token:
        # Use official Facebook Graph API oEmbed
        oembed_url = (
            f"https://graph.facebook.com/v10.0/instagram_oembed"
            f"?url={urllib.parse.quote(url, safe='')}"
            f"&access_token={access_token}"
        )
    else:
        # Fallback to keyless
        oembed_url = (
            f"https://www.instagram.com/api/v1/oembed"
            f"?url={urllib.parse.quote(url, safe='')}"
        )

    try:
        req = urllib.request.Request(
            oembed_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        vm = VideoMetadata(
            video_id=video_id,
            url=url,
            title=data.get("title", "Instagram Reel"),
            creator=data.get("author_name", "Instagram Creator"),
            follower_count=0,
            views=0,
            likes=0,
            comments=0,
            engagement_rate=0.0,
            hashtags=[],
            upload_date="unknown",
            duration_seconds=30,
            thumbnail_url=data.get("thumbnail_url", ""),
        )

        logger.info(
            "[Metadata] ✓ Instagram oEmbed — title='%s'  creator='%s'",
            vm.title[:50], vm.creator,
        )
        return vm

    except Exception as exc:
        logger.warning("[Metadata] Instagram oEmbed fallback failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Main metadata fetcher with 3-tier fallback
# ---------------------------------------------------------------------------

def fetch_metadata(url: str, video_id: str) -> VideoMetadata:
    """
    Extract metadata for a given video URL.

    Fallback chain:
      1. yt-dlp (full metadata — works on local machines, blocked on datacenters)
      2. YouTube Data API v3 (full real metadata — needs YOUTUBE_API_KEY)
      3. YouTube oEmbed API (title + creator only — no API key needed)
      4. Static fallback (bare minimum so the pipeline doesn't crash)

    Args:
        url: The video URL (YouTube or Instagram).
        video_id: Label for this video — "A" or "B".

    Returns:
        A fully populated VideoMetadata instance.
    """
    logger.info("[Metadata] Fetching metadata for video_id=%s  url=%s", video_id, url[:80])
    fetch_start = time.time()
    
    # ── Tier 1: yt-dlp (best data, but blocked on datacenter IPs) ──────────
    from app.services.cookies import get_yt_dlp_cookies_opt

    try:
        with get_yt_dlp_cookies_opt() as cookies_opts:
            cmd = [
                "yt-dlp",
                "--dump-json",
                "--no-playlist",
                "--no-check-certificates",
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "--extractor-args", "youtube:player_client=ios,android,web",
            ]
            cmd.extend(cookies_opts)
            cmd.append(url)
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )
    except FileNotFoundError:
        logger.warning("[Metadata] yt-dlp not found — trying API fallbacks")
        result = None
    except subprocess.TimeoutExpired:
        logger.warning("[Metadata] yt-dlp timed out — trying API fallbacks")
        result = None

    # If yt-dlp succeeded, parse and return
    if result and result.returncode == 0:
        logger.info(
            "[Metadata] yt-dlp finished in %.1fs — exit_code=0",
            time.time() - fetch_start,
        )
        try:
            data: dict = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            logger.warning("[Metadata] yt-dlp returned non-JSON: %s", exc)
            data = None

        if data:
            views = int(data.get("view_count") or 0)
            likes = int(data.get("like_count") or 0)
            comments = int(data.get("comment_count") or 0)
            engagement_rate = round((likes + comments) / views * 100, 4) if views > 0 else 0.0

            raw_date: str = data.get("upload_date", "") or ""
            if len(raw_date) == 8 and raw_date.isdigit():
                upload_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
            else:
                upload_date = raw_date or "unknown"

            hashtags = [tag for tag in (data.get("tags") or []) if isinstance(tag, str)]
            thumbnail_url = data.get("thumbnail") or ""

            vm = VideoMetadata(
                video_id=video_id,
                url=url,
                title=data.get("title") or "Untitled",
                creator=data.get("uploader") or data.get("channel") or "Unknown Creator",
                follower_count=int(data.get("channel_follower_count") or 0),
                views=views,
                likes=likes,
                comments=comments,
                engagement_rate=engagement_rate,
                hashtags=hashtags,
                upload_date=upload_date,
                duration_seconds=int(data.get("duration") or 0),
                thumbnail_url=thumbnail_url,
            )

            logger.info(
                "[Metadata] ✓ yt-dlp — video_id=%s  title='%s'  creator='%s'  views=%d  likes=%d",
                video_id, vm.title[:50], vm.creator, vm.views, vm.likes,
            )
            return vm

    # yt-dlp failed — log it
    if result:
        logger.warning(
            "[Metadata] yt-dlp failed (exit %d) for %s — trying API fallbacks",
            result.returncode, url[:80],
        )

    # ── Tier 2 & 3: API fallbacks ──────────────────────────────────────────
    is_youtube = "youtube.com" in url or "youtu.be" in url
    is_instagram = "instagram.com" in url

    if is_youtube:
        yt_id = extract_youtube_id(url) or "unknown"

        # Tier 2: YouTube Data API v3 (real views, likes, comments)
        vm = _fetch_youtube_api_metadata(yt_id, video_id, url)
        if vm:
            return vm

        # Tier 3: YouTube oEmbed (at least real title + creator)
        vm = _fetch_youtube_oembed_metadata(yt_id, video_id, url)
        if vm:
            return vm

        # Tier 4: Static fallback (bare minimum)
        logger.warning("[Metadata] All YouTube fallbacks failed for %s — using static fallback", yt_id)
        return VideoMetadata(
            video_id=video_id,
            url=url,
            title=f"YouTube Video ({yt_id})",
            creator="Unknown Creator",
            follower_count=0,
            views=0,
            likes=0,
            comments=0,
            engagement_rate=0.0,
            hashtags=[],
            upload_date="unknown",
            duration_seconds=60,
            thumbnail_url=f"https://img.youtube.com/vi/{yt_id}/0.jpg",
        )

    elif is_instagram:
        # Tier 2: Instagram oEmbed
        vm = _fetch_instagram_oembed_metadata(url, video_id)
        if vm:
            return vm

        # Tier 3: Static fallback
        ig_id = extract_instagram_id(url) or "unknown"
        logger.warning("[Metadata] All Instagram fallbacks failed for %s — using static fallback", ig_id)
        return VideoMetadata(
            video_id=video_id,
            url=url,
            title=f"Instagram Reel ({ig_id})",
            creator="Unknown Creator",
            follower_count=0,
            views=0,
            likes=0,
            comments=0,
            engagement_rate=0.0,
            hashtags=[],
            upload_date="unknown",
            duration_seconds=30,
            thumbnail_url="",
        )

    else:
        stderr_snippet = (result.stderr[:500] if result and result.stderr else "no stderr")
        raise RuntimeError(
            f"yt-dlp failed and no API fallback available for URL {url}. "
            f"stderr: {stderr_snippet}"
        )
