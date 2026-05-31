from __future__ import annotations

import json
import logging
import subprocess
import time

from app.models.schemas import VideoMetadata

logger = logging.getLogger(__name__)


def fetch_metadata(url: str, video_id: str) -> VideoMetadata:
    """
    Use yt-dlp to extract metadata for a given URL.

    Args:
        url: The video URL (YouTube or Instagram).
        video_id: Label for this video — "A" or "B".

    Returns:
        A fully populated VideoMetadata instance.

    Raises:
        RuntimeError: If yt-dlp fails or returns unusable output.
    """
    logger.info("[Metadata] Fetching metadata for video_id=%s  url=%s", video_id, url[:80])
    fetch_start = time.time()
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-playlist", url],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "yt-dlp is not installed or not on PATH. Install it with: pip install yt-dlp"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"yt-dlp timed out while fetching metadata for: {url}")

    logger.info(
        "[Metadata] yt-dlp finished in %.1fs — exit_code=%d",
        time.time() - fetch_start, result.returncode,
    )

    if result.returncode != 0:
        stderr_snippet = result.stderr[:500] if result.stderr else "no stderr"
        raise RuntimeError(
            f"yt-dlp exited with code {result.returncode} for URL {url}. "
            f"stderr: {stderr_snippet}"
        )

    try:
        data: dict = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"yt-dlp returned non-JSON output for URL {url}: {exc}"
        )

    views: int = int(data.get("view_count") or 0)
    likes: int = int(data.get("like_count") or 0)
    comments: int = int(data.get("comment_count") or 0)

    if views > 0:
        engagement_rate = round((likes + comments) / views * 100, 4)
    else:
        engagement_rate = 0.0

    # Normalize the upload_date field (YYYYMMDD → YYYY-MM-DD when possible)
    raw_date: str = data.get("upload_date", "") or ""
    if len(raw_date) == 8 and raw_date.isdigit():
        upload_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
    else:
        upload_date = raw_date or "unknown"

    hashtags: list[str] = [
        tag for tag in (data.get("tags") or []) if isinstance(tag, str)
    ]

    thumbnail_url: str = data.get("thumbnail") or ""

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
        "[Metadata] ✓ video_id=%s  title='%s'  creator='%s'  views=%d  likes=%d",
        video_id, vm.title[:50], vm.creator, vm.views, vm.likes,
    )
    return vm
