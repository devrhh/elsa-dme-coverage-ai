"""Local embeddings via fastembed, running BAAI/bge-large-en-v1.5.

Runs fully offline (the ~1.2GB ONNX model is downloaded once and cached
locally) - no API key or per-request network call. fastembed ships a
pre-quantized ONNX export of the model, so it avoids a torch dependency
while reusing the onnxruntime already pulled in by chromadb.
"""

from fastembed import TextEmbedding

from app.config import get_settings

settings = get_settings()
_MODEL_NAME = "BAAI/bge-large-en-v1.5"
_model: TextEmbedding | None = None


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        # Explicit, persistent cache_dir under data/ (mirrors upload_dir /
        # chroma_persist_dir) rather than fastembed's default of the OS temp
        # dir, which can be wiped between restarts/container rebuilds and
        # would otherwise trigger a surprise ~1.2GB re-download.
        kwargs = dict(
            model_name=_MODEL_NAME,
            providers=["CPUExecutionProvider"],
            cache_dir=settings.embedding_model_cache_dir,
        )
        try:
            # Once cached, skip fastembed's HuggingFace "is there a newer
            # revision?" metadata check - it's a network call on every cold
            # start otherwise, and unnecessary for a pinned model version.
            _model = TextEmbedding(local_files_only=True, **kwargs)
        except Exception:  # noqa: BLE001 - not cached yet, fall through to a real download
            _model = TextEmbedding(**kwargs)
    return _model


def embed_texts(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    """Embed a list of chunk texts, batching to bound peak memory usage.

    Uses `passage_embed` rather than the generic `embed` - fastembed's BGE
    implementation applies the model's recommended asymmetric-retrieval
    convention (a distinct handling for indexed passages vs. search queries)
    under that method, matching how `embed_query` embeds questions below.
    """
    model = _get_model()
    # fastembed's embed methods return numpy float32 arrays; cast to native
    # Python floats since Chroma's input validation rejects numpy scalars.
    return [[float(x) for x in vec] for vec in model.passage_embed(texts, batch_size=batch_size)]


def embed_query(text: str) -> list[float]:
    return [float(x) for x in next(iter(_get_model().query_embed(text)))]
