"""
transcript.py — Production-grade, fault-tolerant transcript extraction.

YouTube priority chain (attempts every candidate before moving on):
  1. Manual transcripts   — preferred language first, then any language
  2. Auto-generated        — preferred language first, then any language
  3. Translated            — preferred language → English → any
  4. Whisper fallback      — yt-dlp audio download → Faster-Whisper (local)

Each step iterates through ALL candidates.  Per-candidate fetch failures
(XMLParseError, HTTP errors, empty responses) are caught and logged so the
pipeline continues to the next candidate rather than crashing.

Retry with exponential backoff is applied inside each per-candidate fetch.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Optional
from xml.etree.ElementTree import ParseError as XMLParseError

import threading
import traceback

from faster_whisper import WhisperModel

from app.core.config import settings
from app.models.schemas import TranscriptInfo, TranscriptResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Whisper model singleton (thread-safe lazy init)
# ---------------------------------------------------------------------------
_whisper_model: WhisperModel | None = None
_whisper_lock = threading.Lock()


def _get_whisper_model() -> WhisperModel:
    """Return a cached WhisperModel instance (created once, reused)."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    with _whisper_lock:
        if _whisper_model is not None:          # double-check after lock
            return _whisper_model
        logger.info("[Whisper] Loading model 'base' (device=cpu, compute_type=int8) ...")
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
        logger.info("[Whisper] Model loaded successfully")
        return _whisper_model

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RETRY_ATTEMPTS = 3          # per-candidate fetch attempts
_RETRY_BASE_DELAY = 1.0      # seconds (doubles each retry)
_MIN_TRANSCRIPT_CHARS = 20   # discard transcripts shorter than this


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_youtube_video_id(url: str) -> str:
    """
    Extract the 11-character video ID from all common YouTube URL formats:
        https://www.youtube.com/watch?v=VIDEO_ID
        https://youtu.be/VIDEO_ID
        https://www.youtube.com/shorts/VIDEO_ID
        https://m.youtube.com/watch?v=VIDEO_ID
        https://www.youtube.com/embed/VIDEO_ID
    """
    match = re.search(
        r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})",
        url,
    )
    if match:
        return match.group(1)
    raise ValueError(
        f"Could not extract a YouTube video ID from: {url!r}. "
        "Please provide a standard youtube.com or youtu.be URL."
    )


def _segments_to_text(segments: list) -> str:
    """
    Flatten a list of transcript segment dicts into a single clean string.
    Handles both dict-style ({"text": ...}) and object-style (.text attribute).
    """
    parts = []
    for seg in segments:
        if isinstance(seg, dict):
            text = seg.get("text", "")
        else:
            text = getattr(seg, "text", "")
        cleaned = re.sub(r"\s+", " ", str(text)).strip()
        if cleaned:
            parts.append(cleaned)
    return " ".join(parts)


def _safe_fetch_transcript(transcript, attempt_label: str) -> Optional[str]:
    """
    Fetch a single youtube_transcript_api Transcript object with:
      - Exponential backoff retry for transient failures
      - Catches XMLParseError, HTTP errors, and any other exception
      - Validates that the result is non-empty

    Returns the transcript text string, or None if all attempts fail.
    """
    delay = _RETRY_BASE_DELAY
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            segments = transcript.fetch()

            if not segments:
                logger.warning(
                    "[YT-FETCH] %s returned empty segments (attempt %d/%d)",
                    attempt_label, attempt, _RETRY_ATTEMPTS,
                )
                return None

            text = _segments_to_text(segments)

            if len(text) < _MIN_TRANSCRIPT_CHARS:
                logger.warning(
                    "[YT-FETCH] %s text too short (%d chars) — skipping",
                    attempt_label, len(text),
                )
                return None

            logger.info(
                "[YT-FETCH] %s succeeded on attempt %d — %d chars",
                attempt_label, attempt, len(text),
            )
            return text

        except XMLParseError as exc:
            logger.warning(
                "[YT-FETCH] %s raised XMLParseError on attempt %d/%d: %s",
                attempt_label, attempt, _RETRY_ATTEMPTS, exc,
            )
        except Exception as exc:
            err_type = type(exc).__name__
            logger.warning(
                "[YT-FETCH] %s raised %s on attempt %d/%d: %s",
                attempt_label, err_type, attempt, _RETRY_ATTEMPTS, exc,
            )

        if attempt < _RETRY_ATTEMPTS:
            logger.debug(
                "[YT-FETCH] Backing off %.1fs before retry %d for %s",
                delay, attempt + 1, attempt_label,
            )
            time.sleep(delay)
            delay *= 2

    logger.error(
        "[YT-FETCH] %s failed after %d attempts — giving up on this candidate",
        attempt_label, _RETRY_ATTEMPTS,
    )
    return None


def _build_result(
    text: str,
    language_code: str,
    language_name: str,
    source: str,
    is_original: bool,
    video_id: str,
) -> TranscriptResult:
    return TranscriptResult(
        transcript=text,
        info=TranscriptInfo(
            language=language_code,
            language_name=language_name,
            source=source,  # type: ignore[arg-type]
            is_original=is_original,
            video_id_yt=video_id,
        ),
    )


# ---------------------------------------------------------------------------
# Whisper fallback (shared by YouTube and Instagram)
# ---------------------------------------------------------------------------

def _find_ffmpeg() -> Optional[str]:
    """
    Locate the ffmpeg binary.  Tries shutil.which first, then searches
    common Windows installation directories (WinGet, Chocolatey, Scoop,
    manual installs).  Returns the full path to ffmpeg.exe or None.
    """
    # 1. Standard PATH lookup
    path = shutil.which("ffmpeg")
    if path:
        return path

    # 2. Search common Windows locations (winget, choco, scoop, manual)
    home = os.path.expanduser("~")
    search_roots = [
        os.path.join(home, "AppData", "Local", "Microsoft", "WinGet", "Packages"),
        os.path.join(home, "AppData", "Local", "Microsoft", "WinGet", "Links"),
        os.path.join(home, "scoop", "shims"),
        os.path.join(home, "scoop", "apps", "ffmpeg"),
        r"C:\ffmpeg",
        r"C:\ffmpeg\bin",
        r"C:\tools\ffmpeg",
        r"C:\tools\ffmpeg\bin",
        r"C:\ProgramData\chocolatey\bin",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\Program Files (x86)\ffmpeg\bin",
    ]

    for root in search_roots:
        if not os.path.isdir(root):
            continue
        # Walk up to 5 levels deep to find ffmpeg.exe
        for dirpath, _dirnames, filenames in os.walk(root):
            # Limit search depth to avoid scanning the whole disk
            depth = dirpath.replace(root, "").count(os.sep)
            if depth > 5:
                continue
            if "ffmpeg.exe" in filenames:
                found = os.path.join(dirpath, "ffmpeg.exe")
                logger.info("[Whisper] Found ffmpeg at non-PATH location: %s", found)
                return found

    return None


def _find_ffprobe() -> Optional[str]:
    """Locate ffprobe — checks PATH first, then the same dir as ffmpeg."""
    path = shutil.which("ffprobe")
    if path:
        return path

    # If ffmpeg was found in a non-standard location, ffprobe is likely next to it
    ffmpeg_path = _find_ffmpeg()
    if ffmpeg_path:
        ffprobe_candidate = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe.exe")
        if os.path.isfile(ffprobe_candidate):
            return ffprobe_candidate

    return None


# Cache the discovered ffmpeg directory so we don't re-scan the disk every call
_ffmpeg_dir_cache: Optional[str] = None


def _get_ffmpeg_dir() -> Optional[str]:
    """Return the directory containing ffmpeg, or None if not found."""
    global _ffmpeg_dir_cache
    if _ffmpeg_dir_cache is not None:
        return _ffmpeg_dir_cache

    ffmpeg_path = _find_ffmpeg()
    if ffmpeg_path:
        _ffmpeg_dir_cache = os.path.dirname(ffmpeg_path)
        logger.info("[Whisper] Cached ffmpeg directory: %s", _ffmpeg_dir_cache)
        return _ffmpeg_dir_cache

    return None


def _check_whisper_prerequisites() -> Optional[str]:
    """
    Verify that yt-dlp and ffmpeg are available before attempting download.
    Returns the ffmpeg directory path (for --ffmpeg-location) or None if
    ffmpeg is on PATH.  Raises RuntimeError if yt-dlp is missing.
    """
    ytdlp_path = shutil.which("yt-dlp")
    ffmpeg_dir = _get_ffmpeg_dir()
    ffmpeg_on_path = shutil.which("ffmpeg") is not None

    logger.info(
        "[Whisper] Pre-flight: yt-dlp=%s  ffmpeg_dir=%s  ffmpeg_on_path=%s",
        ytdlp_path or "NOT FOUND",
        ffmpeg_dir or "NOT FOUND",
        ffmpeg_on_path,
    )

    if not ytdlp_path:
        raise RuntimeError(
            "yt-dlp is not installed or not on PATH. "
            "Install with: pip install yt-dlp"
        )

    if not ffmpeg_dir:
        raise RuntimeError(
            "ffmpeg is not installed. yt-dlp needs ffmpeg to extract audio. "
            "Install with: winget install Gyan.FFmpeg  /  "
            "choco install ffmpeg  /  "
            "Download from https://ffmpeg.org/download.html"
        )

    # Return the dir only if ffmpeg is NOT on PATH (so we pass --ffmpeg-location)
    return ffmpeg_dir if not ffmpeg_on_path else None


def _whisper_transcribe_url(
    url: str,
    video_id: str,
    context_label: str = "URL",
) -> TranscriptResult:
    logger.info("[Whisper] === START _whisper_transcribe_url for %s ===", context_label)

    # ── Pre-flight ──────────────────────────────────────────────────────
    logger.info("[Whisper] Step 1/6: Checking prerequisites ...")
    try:
        ffmpeg_location = _check_whisper_prerequisites()
    except RuntimeError:
        logger.exception("[Whisper] Pre-flight FAILED")
        raise
    logger.info("[Whisper] Step 1/6: Prerequisites OK (ffmpeg_location=%s)", ffmpeg_location)

    tmp_dir = tempfile.mkdtemp(prefix="ragbot_audio_")
    tmp_template = os.path.join(tmp_dir, "audio.%(ext)s")
    actual_path = os.path.join(tmp_dir, "audio.mp3")

    try:
        # ── Download audio ──────────────────────────────────────────────
        logger.info("[Whisper] Step 2/6: Downloading audio for %s into %s", context_label, tmp_dir)

        cmd = [
            "yt-dlp",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--no-playlist",
            "--force-overwrites",
            "--no-check-certificates",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "--extractor-args", "youtube:player_client=ios,android,web",
            "-o",
            tmp_template,
        ]

        if ffmpeg_location:
            cmd.extend(["--ffmpeg-location", ffmpeg_location])

        cmd.append(url)
        logger.info("[Whisper] Running command: %s", " ".join(cmd))

        dl_start = time.time()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
        )
        dl_elapsed = time.time() - dl_start

        logger.info(
            "[Whisper] yt-dlp finished in %.1fs — exit_code=%d",
            dl_elapsed, result.returncode,
        )
        if result.stdout:
            logger.debug("[Whisper] yt-dlp stdout (last 500 chars): %s", result.stdout[-500:])
        if result.stderr:
            logger.warning("[Whisper] yt-dlp stderr (last 500 chars): %s", result.stderr[-500:])

        if result.returncode != 0:
            raise RuntimeError(
                f"yt-dlp failed for {context_label} "
                f"(exit {result.returncode}): {result.stderr[:1000]}"
            )

        # ── Locate audio file ───────────────────────────────────────────
        logger.info("[Whisper] Step 3/6: Locating audio file ...")
        if not os.path.exists(actual_path):
            files = [
                os.path.join(tmp_dir, f)
                for f in os.listdir(tmp_dir)
                if os.path.isfile(os.path.join(tmp_dir, f))
            ]
            logger.info("[Whisper] audio.mp3 not found; files in temp dir: %s", files)

            if not files:
                raise RuntimeError("yt-dlp succeeded but no audio file was created.")

            files.sort(key=lambda p: os.path.getsize(p), reverse=True)
            actual_path = files[0]
            logger.info("[Whisper] Using largest file instead: %s", actual_path)

        file_size = os.path.getsize(actual_path)

        if file_size == 0:
            raise RuntimeError("Downloaded audio file is empty.")

        logger.info(
            "[Whisper] Step 3/6: Audio ready — path=%s  size=%.2f MB",
            actual_path,
            file_size / (1024 * 1024),
        )

        # ── Load Whisper model ──────────────────────────────────────────
        logger.info("[Whisper] Step 4/6: Acquiring Whisper model ...")
        model_start = time.time()
        model = _get_whisper_model()
        logger.info(
            "[Whisper] Step 4/6: Model ready in %.2fs",
            time.time() - model_start,
        )

        # ── Transcribe ──────────────────────────────────────────────────
        logger.info("[Whisper] Step 5/6: Starting transcription of %s ...", actual_path)
        transcribe_start = time.time()
        segments, info = model.transcribe(actual_path)
        logger.info(
            "[Whisper] model.transcribe() returned (generator + info) in %.2fs  "
            "detected_language=%s  language_probability=%.2f",
            time.time() - transcribe_start,
            info.language,
            info.language_probability,
        )

        # ── Materialise lazy segments ───────────────────────────────────
        logger.info("[Whisper] Step 6/6: Iterating segments (this is where actual decoding happens) ...")
        parts: list[str] = []
        seg_count = 0
        iter_start = time.time()
        try:
            for segment in segments:
                seg_count += 1
                logger.info(
                    "[Whisper]   segment #%d  start=%.2f  end=%.2f  text_len=%d",
                    seg_count, segment.start, segment.end, len(segment.text),
                )
                stripped = segment.text.strip()
                if stripped:
                    parts.append(stripped)
        except Exception as seg_exc:
            logger.error(
                "[Whisper] EXCEPTION while iterating segments at segment #%d: %s",
                seg_count + 1, seg_exc,
            )
            logger.error("[Whisper] Traceback:\n%s", traceback.format_exc())
            raise RuntimeError(
                f"Whisper segment iteration failed at segment #{seg_count + 1}: {seg_exc}"
            ) from seg_exc

        iter_elapsed = time.time() - iter_start
        logger.info(
            "[Whisper] Segments collected: %d segments in %.2fs",
            seg_count, iter_elapsed,
        )

        text = " ".join(parts)
        detected_lang = info.language

        logger.info(
            "[Whisper] Transcript length=%d chars  language=%s",
            len(text), detected_lang,
        )

        if not text or len(text) < _MIN_TRANSCRIPT_CHARS:
            raise RuntimeError(
                f"Whisper returned empty/too-short transcript "
                f"({len(text)} chars)."
            )

        logger.info("[Whisper] === END _whisper_transcribe_url for %s (SUCCESS) ===", context_label)

        return _build_result(
            text=text,
            language_code=detected_lang,
            language_name=detected_lang.title(),
            source="whisper",
            is_original=True,
            video_id=video_id,
        )

    except Exception:
        logger.error(
            "[Whisper] === END _whisper_transcribe_url for %s (FAILED) ===",
            context_label,
        )
        logger.error("[Whisper] Traceback:\n%s", traceback.format_exc())
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
# ---------------------------------------------------------------------------
# YouTube transcript (multi-language, fully fault-tolerant)
# ---------------------------------------------------------------------------

def fetch_youtube_transcript(
    url: str,
    preferred_language: Optional[str] = None,
) -> TranscriptResult:
    """
    Fetch the best available transcript for a YouTube video.

    Priority chain
    ──────────────
    1.  Manual transcripts (preferred language first, then all others)
    2.  Auto-generated transcripts (preferred language first, then all others)
    3.  Translated transcripts (preferred → English → any other)
    4.  Whisper fallback (yt-dlp + OpenAI whisper-1)

    Each candidate is fetched with up to _RETRY_ATTEMPTS attempts and
    full exception handling (XMLParseError, HTTP, empty response, etc.).
    A candidate is only accepted if the resulting text is non-empty.

    The API never crashes with an unhandled exception.  Unrecoverable
    situations (age-restricted, region-blocked, completely unavailable)
    raise a clear RuntimeError with a human-readable message.

    Args:
        url:                Full YouTube video URL.
        preferred_language: BCP-47 code to prioritise (e.g. 'en', 'hi', 'te').
                            When None the best available language is chosen.

    Returns:
        TranscriptResult with transcript text and full provenance metadata.
    """
    from youtube_transcript_api import (
        YouTubeTranscriptApi,
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
    )
    from youtube_transcript_api._errors import TranslationLanguageNotAvailable

    video_id = _extract_youtube_video_id(url)
    logger.info(
        "[YT] Starting transcript pipeline — video_id=%s  preferred_lang=%s",
        video_id, preferred_language or "auto",
    )

    # ── List available transcripts ──────────────────────────────────────────
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
    except TranscriptsDisabled:
        logger.warning("[YT] Transcripts disabled for %s — Whisper fallback", video_id)
        try:
            return _whisper_transcribe_url(url, video_id, f"YouTube:{video_id}")
        except Exception as e:
            logger.error("[YT] Whisper fallback also failed for %s: %s", video_id, e)
            return _build_result(
                text=f"[Transcript unavailable — transcripts are disabled for this video and audio download was blocked. Video ID: {video_id}]",
                language_code="en", language_name="English",
                source="manual", is_original=False, video_id=video_id,
            )
    except NoTranscriptFound:
        logger.warning("[YT] No transcripts at all for %s — Whisper fallback", video_id)
        try:
            return _whisper_transcribe_url(url, video_id, f"YouTube:{video_id}")
        except Exception as e:
            logger.error("[YT] Whisper fallback also failed for %s: %s", video_id, e)
            return _build_result(
                text=f"[Transcript unavailable — no captions found and audio download was blocked. Video ID: {video_id}]",
                language_code="en", language_name="English",
                source="manual", is_original=False, video_id=video_id,
            )
    except VideoUnavailable:
        raise RuntimeError(
            f"YouTube video '{video_id}' is unavailable "
            "(private, deleted, age-restricted, or geo-blocked)."
        )
    except Exception as exc:
        msg = str(exc).lower()
        if "age" in msg:
            raise RuntimeError(
                f"YouTube video '{video_id}' is age-restricted and cannot be accessed."
            )
        if any(k in msg for k in ("region", "country", "geo", "not available")):
            raise RuntimeError(
                f"YouTube video '{video_id}' is not available in your region."
            )
        logger.warning(
            "[YT] Unexpected error listing transcripts for %s: %s — Whisper fallback",
            video_id, exc,
        )
        try:
            return _whisper_transcribe_url(url, video_id, f"YouTube:{video_id}")
        except Exception as e:
            logger.error("[YT] Whisper fallback also failed for %s: %s", video_id, e)
            return _build_result(
                text=f"[Transcript unavailable — caption listing failed and audio download was blocked. Video ID: {video_id}]",
                language_code="en", language_name="English",
                source="manual", is_original=False, video_id=video_id,
            )

    # ── Partition and log all available transcripts ─────────────────────────
    manual_transcripts: list = []
    auto_transcripts: list = []
    for t in transcript_list:
        bucket = auto_transcripts if t.is_generated else manual_transcripts
        bucket.append(t)
        logger.info(
            "[YT] Available: lang=%s (%s)  is_generated=%s  is_translatable=%s",
            t.language_code, t.language, t.is_generated, t.is_translatable,
        )

    logger.info(
        "[YT] %s — %d manual, %d auto-generated transcripts found",
        video_id, len(manual_transcripts), len(auto_transcripts),
    )

    # ── Build ordered candidate lists based on preferred language ───────────
    def _order_by_preference(candidates: list) -> list:
        """Put preferred-language candidates first, keep relative order."""
        if not preferred_language:
            return list(candidates)
        preferred = [
            t for t in candidates
            if t.language_code.lower().startswith(preferred_language.lower())
        ]
        rest = [
            t for t in candidates
            if not t.language_code.lower().startswith(preferred_language.lower())
        ]
        return preferred + rest

    # ── Step 1 & 2: Attempt every manual then every auto transcript ──────────
    for bucket_name, candidates in [
        ("manual", _order_by_preference(manual_transcripts)),
        ("auto-generated", _order_by_preference(auto_transcripts)),
    ]:
        for t in candidates:
            label = f"{video_id}/{t.language_code}/{bucket_name}"
            logger.info("[YT] Trying %s ...", label)

            text = _safe_fetch_transcript(t, attempt_label=label)
            if text:
                logger.info(
                    "[YT] ✓ Accepted: %s | chars=%d", label, len(text)
                )
                return _build_result(
                    text=text,
                    language_code=t.language_code,
                    language_name=t.language,
                    source=bucket_name,
                    is_original=True,
                    video_id=video_id,
                )
            logger.warning("[YT] ✗ Skipped (failed/empty): %s", label)

    # ── Step 3: Translation fallback ────────────────────────────────────────
    all_transcripts = manual_transcripts + auto_transcripts
    translatable = [t for t in all_transcripts if t.is_translatable]

    # Build target language priority: preferred → English → skip
    target_langs: list[str] = []
    if preferred_language and preferred_language.lower() != "en":
        target_langs.append(preferred_language)
    target_langs.append("en")

    for target_lang in target_langs:
        for t in translatable:
            label = f"{video_id}/{t.language_code}→{target_lang}/translated"
            logger.info("[YT] Trying translation: %s ...", label)
            try:
                translated = t.translate(target_lang)
                text = _safe_fetch_transcript(translated, attempt_label=label)
                if text:
                    logger.info("[YT] ✓ Accepted translation: %s | chars=%d", label, len(text))
                    return _build_result(
                        text=text,
                        language_code=target_lang,
                        language_name=target_lang,
                        source="translated",
                        is_original=False,
                        video_id=video_id,
                    )
                logger.warning("[YT] ✗ Translation empty/failed: %s", label)
            except (TranslationLanguageNotAvailable, Exception) as exc:
                logger.warning("[YT] Translation %s unavailable: %s", label, exc)
                continue

    # ── Step 4 & 5: Whisper fallback ────────────────────────────────────────
    logger.warning(
        "[YT] All %d caption strategies exhausted for %s — falling back to Whisper",
        len(manual_transcripts) + len(auto_transcripts) + len(translatable),
        video_id,
    )
    try:
        return _whisper_transcribe_url(url, video_id, context_label=f"YouTube:{video_id}")
    except Exception as whisper_exc:
        logger.error(
            "[YT] Whisper fallback also failed for %s: %s — returning fallback transcript",
            video_id, whisper_exc,
        )
        return _build_result(
            text=(
                f"[Transcript unavailable — YouTube blocked automated access from this server. "
                f"Video ID: {video_id}, URL: {url}. "
                f"The video exists but its transcript could not be extracted in this environment.]"
            ),
            language_code="en",
            language_name="English",
            source="manual",
            is_original=False,
            video_id=video_id,
        )


# ---------------------------------------------------------------------------
# Instagram / generic yt-dlp + Whisper transcript
# ---------------------------------------------------------------------------

def fetch_instagram_transcript(url: str) -> TranscriptResult:
    """
    Download audio from an Instagram Reel (or any yt-dlp-compatible URL)
    and transcribe with OpenAI whisper-1.

    Returns:
        TranscriptResult with source='whisper'.
    """
    try:
        return _whisper_transcribe_url(
            url,
            video_id="instagram",
            context_label=f"Instagram:{url[:80]}",
        )
    except Exception as exc:
        logger.error(
            "[Instagram] Whisper transcription failed for %s: %s — returning fallback",
            url[:80], exc,
        )
        return _build_result(
            text=(
                f"[Transcript unavailable — Instagram blocked automated audio download from this server. "
                f"URL: {url}. The reel exists but its audio could not be extracted in this environment.]"
            ),
            language_code="en",
            language_name="English",
            source="whisper",
            is_original=False,
            video_id="instagram",
        )
