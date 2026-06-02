from __future__ import annotations

import contextlib
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

@contextlib.contextmanager
def get_yt_dlp_cookies_opt():
    """
    Check if INSTAGRAM_COOKIES environment variable is set.
    It can be:
      1. A path to an existing cookie file (e.g. "./cookies.txt")
      2. Raw Netscape-formatted cookie content
    
    Yields:
        A list of arguments to append to the yt-dlp command, e.g. ["--cookies", "/path/to/temp_cookies.txt"],
        or an empty list if not configured.
    """
    cookies_val = os.environ.get("INSTAGRAM_COOKIES", "").strip()
    if not cookies_val:
        yield []
        return

    # Case 1: It is a path to an existing file
    if os.path.exists(cookies_val):
        logger.info("[Cookies] Using cookies from file path: %s", cookies_val)
        yield ["--cookies", cookies_val]
        return

    # Case 2: It is raw cookie data. Write it to a temporary file.
    temp_cookie_file = None
    try:
        # Create a temporary file to store the raw cookies text
        fd, temp_cookie_file = tempfile.mkstemp(suffix="_cookies.txt", prefix="ragbot_")
        logger.info("[Cookies] Writing raw cookies from environment to temporary file: %s", temp_cookie_file)
        
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(cookies_val)
            
        yield ["--cookies", temp_cookie_file]
    except Exception as exc:
        logger.error("[Cookies] Failed to write temporary cookie file: %s", exc)
        yield []
    finally:
        # Clean up the temporary file immediately after use
        if temp_cookie_file and os.path.exists(temp_cookie_file):
            try:
                os.remove(temp_cookie_file)
                logger.info("[Cookies] Successfully removed temporary cookies file")
            except Exception as exc:
                logger.warning("[Cookies] Failed to remove temporary cookies file: %s", exc)
