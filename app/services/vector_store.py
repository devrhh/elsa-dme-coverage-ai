"""ChromaDB wrapper - one physically separate collection per organization.

Retrieval is always scoped to a single org's collection object, so there is
no shared index a query could ever leak across, even if application code
forgot a metadata filter.
"""

import re
import uuid

import chromadb

from app.config import get_settings

settings = get_settings()
_client: chromadb.ClientAPI | None = None


def get_chroma_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=settings.chroma_persist_dir,
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
    return _client


def _collection_name(org_id: uuid.UUID) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", str(org_id))
    return f"org_{safe}"


def get_org_collection(org_id: uuid.UUID):
    client = get_chroma_client()
    return client.get_or_create_collection(name=_collection_name(org_id), metadata={"hnsw:space": "cosine"})


def add_chunks(
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    filename: str,
    chunks: list[dict],
    embeddings: list[list[float]],
) -> None:
    if not chunks:
        return
    collection = get_org_collection(org_id)
    ids = [f"{document_id}:{chunk['chunk_index']}" for chunk in chunks]
    documents = [chunk["text"] for chunk in chunks]
    metadatas = [
        {
            "document_id": str(document_id),
            "filename": filename,
            "page": chunk["page"] or 0,
            "section_heading": chunk.get("section_heading") or "",
            "content_type": chunk["content_type"],
            "chunk_index": chunk["chunk_index"],
        }
        for chunk in chunks
    ]
    collection.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)


def delete_document_chunks(org_id: uuid.UUID, document_id: uuid.UUID) -> None:
    collection = get_org_collection(org_id)
    collection.delete(where={"document_id": str(document_id)})


def delete_org_collection(org_id: uuid.UUID) -> None:
    client = get_chroma_client()
    try:
        client.delete_collection(name=_collection_name(org_id))
    except Exception:  # noqa: BLE001 - collection may not exist yet
        pass


def query_org_collection(org_id: uuid.UUID, query_embedding: list[float], top_k: int) -> dict:
    collection = get_org_collection(org_id)
    count = collection.count()
    if count == 0:
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    return collection.query(query_embeddings=[query_embedding], n_results=min(top_k, count))
