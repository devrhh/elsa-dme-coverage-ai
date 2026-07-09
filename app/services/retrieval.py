"""Retrieval: embed the question, search only the requesting org's Chroma
collection, and compute a similarity-based confidence signal used to decide
whether the LLM should even be called."""

import uuid

from app.config import get_settings
from app.services import embeddings, vector_store

settings = get_settings()


def retrieve_chunks(org_id: uuid.UUID, question: str, top_k: int | None = None) -> list[dict]:
    query_embedding = embeddings.embed_query(question)
    results = vector_store.query_org_collection(org_id, query_embedding, top_k or settings.retrieval_top_k)

    ids = results["ids"][0] if results.get("ids") else []
    documents = results["documents"][0] if results.get("documents") else []
    metadatas = results["metadatas"][0] if results.get("metadatas") else []
    distances = results["distances"][0] if results.get("distances") else []

    chunks = []
    for chunk_id, text, metadata, distance in zip(ids, documents, metadatas, distances):
        similarity = max(0.0, 1 - distance)  # Chroma cosine distance -> similarity
        chunks.append(
            {
                "chunk_id": chunk_id,
                "text": text,
                "similarity": similarity,
                "document_id": metadata.get("document_id"),
                "filename": metadata.get("filename"),
                "page": metadata.get("page"),
                "section_heading": metadata.get("section_heading") or None,
                "content_type": metadata.get("content_type"),
            }
        )
    return chunks


def is_retrieval_weak(chunks: list[dict], threshold: float | None = None) -> bool:
    threshold = settings.retrieval_similarity_threshold if threshold is None else threshold
    if not chunks:
        return True
    return chunks[0]["similarity"] < threshold
