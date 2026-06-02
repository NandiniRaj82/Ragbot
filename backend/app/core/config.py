from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    GEMINI_API_KEY: str
    YOUTUBE_API_KEY: str = ""  # Optional: enables YouTube Data API v3 for real metadata
    INSTAGRAM_COOKIES: str = ""  # Optional: file path or raw Netscape cookie content to avoid yt-dlp bans
    INSTAGRAM_ACCESS_TOKEN: str = ""  # Optional: Meta Graph API access token for oEmbed fallback
    CHROMA_DB_PATH: str = "./chroma_db"
    FRONTEND_URL: str = "http://localhost:3000"
    MAX_VIDEO_DURATION_SECONDS: int = 1800  # 30 minutes


settings = Settings()
