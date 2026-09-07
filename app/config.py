from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    # Set GOOGLE_GENAI_USE_VERTEXAI=True with a project to route Gemini through
    # Vertex AI on Google Cloud instead of the AI Studio endpoint.
    google_genai_use_vertexai: bool = False
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_database: str = "cinecompute"
    clickhouse_secure: bool = False
    clickhouse_verify: bool = True
    clickhouse_connect_timeout: int = 15
    clickhouse_query_timeout: int = 60
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
