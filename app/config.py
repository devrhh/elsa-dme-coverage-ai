from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration. All safety caps/timeouts live here so they are
    easy to audit and tune in one place (coverage PDFs are untrusted input)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM (chat/answer-generation) - Groq's OpenAI-compatible API. Embeddings
    # are handled separately by a local, offline model (see
    # app/services/embeddings.py) since Groq has no embeddings endpoint.
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_chat_model: str = "llama-3.3-70b-versatile"
    llm_request_timeout_seconds: float = 30.0
    llm_max_retries: int = 2

    # Postgres
    database_url: str = "postgresql+psycopg2://coverage:coverage@localhost:5432/coverage_qa"

    # Storage
    upload_dir: str = "data/uploads"
    chroma_persist_dir: str = "data/chroma"
    embedding_model_cache_dir: str = "data/models"

    # Upload / extraction caps (defense against untrusted PDF input)
    max_upload_mb: int = 25
    max_pdf_pages: int = 300
    max_extracted_chars: int = 2_000_000
    pdf_extraction_timeout_seconds: int = 60

    # Chunking
    chunk_size_tokens: int = 550
    chunk_overlap_tokens: int = 120
    embedding_encoding: str = "cl100k_base"

    # Retrieval
    retrieval_top_k: int = 5
    retrieval_similarity_threshold: float = 0.3


@lru_cache
def get_settings() -> Settings:
    return Settings()
