"""
Vector Database & Memory - Supabase, pgvector, Qdrant, Chroma, mem0
Inspired by: supabase/supabase, pgvector/pgvector, qdrant/qdrant, chroma-core/chroma, mem0ai/mem0
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import json
import os
import httpx

from app.auth import get_current_active_user
from app.models import User

router = APIRouter(prefix="/api/vector", tags=["Vector Database & Memory"])

# ============================================================
# VECTOR DATABASE PROVIDERS
# ============================================================

VECTOR_PROVIDERS = {
    "pgvector": {
        "name": "pgvector",
        "description": "Open-source vector similarity search for PostgreSQL",
        "type": "postgres_extension",
        "features": ["sql_integration", "hybrid_search", "acid_compliant"],
        "github": "https://github.com/pgvector/pgvector",
        "website": "https://github.com/pgvector/pgvector",
    },
    "supabase": {
        "name": "Supabase Vector",
        "description": "PostgreSQL with pgvector + auth + realtime",
        "type": "managed_postgres",
        "features": ["vector_search", "auth", "realtime", "edge_functions"],
        "website": "https://supabase.com/dashboard",
        "github": "https://github.com/supabase/supabase",
    },
    "qdrant": {
        "name": "Qdrant",
        "description": "Vector search engine with filtering",
        "type": "dedicated_vector_db",
        "features": ["filtering", "payload_storage", "distributed"],
        "website": "https://qdrant.tech/",
        "github": "https://github.com/qdrant/qdrant",
    },
    "chroma": {
        "name": "Chroma",
        "description": "AI-native open-source embedding database",
        "type": "embedded_vector_db",
        "features": ["easy_setup", "python_first", "local"],
        "website": "https://www.trychroma.com/",
        "github": "https://github.com/chroma-core/chroma",
    },
    "redis": {
        "name": "Redis Vector",
        "description": "Vector search with Redis",
        "type": "in_memory",
        "features": ["caching", "speed", "pub_sub"],
        "github": "https://github.com/redis/redis",
    },
}


@router.get("/providers")
async def list_vector_providers():
    """List available vector database providers"""
    return {"providers": VECTOR_PROVIDERS, "total": len(VECTOR_PROVIDERS)}


# ============================================================
# COLLECTIONS / INDEXES
# ============================================================

COLLECTIONS_STORE: Dict[str, Any] = {}


@router.post("/collections", status_code=status.HTTP_201_CREATED)
async def create_collection(
    name: str,
    provider: str = "pgvector",
    dimension: int = 1536,
    distance_metric: str = "cosine",
    current_user: User = Depends(get_current_active_user),
):
    """Create a vector collection"""
    if provider not in VECTOR_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid provider. Options: {list(VECTOR_PROVIDERS.keys())}")

    if dimension not in [128, 256, 384, 512, 768, 1024, 1536, 3072, 4096]:
        raise HTTPException(status_code=400, detail=f"Unsupported dimension: {dimension}")

    collection_id = str(uuid.uuid4())
    COLLECTIONS_STORE[collection_id] = {
        "id": collection_id,
        "name": name,
        "provider": provider,
        "dimension": dimension,
        "distance_metric": distance_metric,
        "owner_id": current_user.id,
        "created_at": datetime.utcnow().isoformat(),
        "vector_count": 0,
        "status": "active",
    }

    return {
        "collection_id": collection_id,
        "name": name,
        "provider": provider,
        "dimension": dimension,
        "distance_metric": distance_metric,
        "status": "created",
    }


@router.get("/collections")
async def list_collections(
    current_user: User = Depends(get_current_active_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """List user's vector collections"""
    collections = [
        c for c in COLLECTIONS_STORE.values() if c["owner_id"] == current_user.id
    ]
    return {
        "collections": collections[skip:skip + limit],
        "total": len(collections),
    }


@router.get("/collections/{collection_id}")
async def get_collection(
    collection_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Get collection details"""
    if collection_id not in COLLECTIONS_STORE:
        raise HTTPException(status_code=404, detail="Collection not found")

    collection = COLLECTIONS_STORE[collection_id]
    if collection["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    return collection


@router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Delete a vector collection"""
    if collection_id not in COLLECTIONS_STORE:
        raise HTTPException(status_code=404, detail="Collection not found")

    collection = COLLECTIONS_STORE[collection_id]
    if collection["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    del COLLECTIONS_STORE[collection_id]


# ============================================================
# VECTORS (Store & Search)
# ============================================================

VECTORS_STORE: Dict[str, List[Dict[str, Any]]] = {}


@router.post("/collections/{collection_id}/vectors")
async def upsert_vectors(
    collection_id: str,
    vectors: List[Dict[str, Any]],
    current_user: User = Depends(get_current_active_user),
):
    """Upsert vectors into a collection"""
    if collection_id not in COLLECTIONS_STORE:
        raise HTTPException(status_code=404, detail="Collection not found")

    collection = COLLECTIONS_STORE[collection_id]
    if collection["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if collection_id not in VECTORS_STORE:
        VECTORS_STORE[collection_id] = []

    inserted = 0
    for vec in vectors:
        vector_id = vec.get("id", str(uuid.uuid4()))
        embedding = vec.get("embedding", [])
        metadata = vec.get("metadata", {})

        if len(embedding) != collection["dimension"]:
            raise HTTPException(
                status_code=400,
                detail=f"Embedding dimension {len(embedding)} != collection dimension {collection['dimension']}"
            )

        VECTORS_STORE[collection_id].append({
            "id": vector_id,
            "embedding": embedding,
            "metadata": metadata,
            "created_at": datetime.utcnow().isoformat(),
        })
        inserted += 1

    collection["vector_count"] = len(VECTORS_STORE[collection_id])

    return {
        "collection_id": collection_id,
        "inserted": inserted,
        "total_vectors": collection["vector_count"],
    }


@router.post("/collections/{collection_id}/search")
async def search_vectors(
    collection_id: str,
    query_vector: List[float],
    top_k: int = Query(5, ge=1, le=100),
    threshold: Optional[float] = Query(None, ge=0.0, le=1.0),
    filter_metadata: Optional[Dict[str, Any]] = None,
    current_user: User = Depends(get_current_active_user),
):
    """Search for similar vectors"""
    if collection_id not in COLLECTIONS_STORE:
        raise HTTPException(status_code=404, detail="Collection not found")

    collection = COLLECTIONS_STORE[collection_id]
    if collection["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if len(query_vector) != collection["dimension"]:
        raise HTTPException(
            status_code=400,
            detail=f"Query vector dimension {len(query_vector)} != collection dimension {collection['dimension']}"
        )

    vectors = VECTORS_STORE.get(collection_id, [])
    if not vectors:
        return {
            "collection_id": collection_id,
            "results": [],
            "total": 0,
        }

    # Cosine similarity search (mock)
    import math
    results = []
    for vec in vectors:
        emb = vec["embedding"]
        # Cosine similarity
        dot = sum(a * b for a, b in zip(query_vector, emb))
        norm_a = math.sqrt(sum(a * a for a in query_vector))
        norm_b = math.sqrt(sum(a * a for a in emb))
        similarity = dot / (norm_a * norm_b) if norm_a * norm_b > 0 else 0

        if threshold is not None and similarity < threshold:
            continue

        if filter_metadata:
            match = all(vec["metadata"].get(k) == v for k, v in filter_metadata.items())
            if not match:
                continue

        results.append({
            "id": vec["id"],
            "similarity": round(similarity, 4),
            "metadata": vec["metadata"],
            "embedding": emb if top_k <= 3 else None,  # Don't return full embeddings for large results
        })

    # Sort by similarity descending
    results.sort(key=lambda x: x["similarity"], reverse=True)
    results = results[:top_k]

    return {
        "collection_id": collection_id,
        "query_dimension": len(query_vector),
        "results": results,
        "total": len(results),
    }


@router.delete("/collections/{collection_id}/vectors/{vector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vector(
    collection_id: str,
    vector_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Delete a vector from collection"""
    if collection_id not in VECTORS_STORE:
        raise HTTPException(status_code=404, detail="Collection not found")

    VECTORS_STORE[collection_id] = [
        v for v in VECTORS_STORE[collection_id] if v["id"] != vector_id
    ]

    if collection_id in COLLECTIONS_STORE:
        COLLECTIONS_STORE[collection_id]["vector_count"] = len(VECTORS_STORE[collection_id])


# ============================================================
# MEMORY (mem0-style)
# ============================================================

MEMORIES_STORE: Dict[str, List[Dict[str, Any]]] = {}


@router.post("/memory/add", status_code=status.HTTP_201_CREATED)
async def add_memory(
    user_id: str,
    content: str,
    embedding: Optional[List[float]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    current_user: User = Depends(get_current_active_user),
):
    """Add a memory entry (mem0-style)"""
    memory_id = str(uuid.uuid4())
    entry = {
        "id": memory_id,
        "user_id": user_id,
        "content": content,
        "embedding": embedding,
        "metadata": metadata or {},
        "created_at": datetime.utcnow().isoformat(),
    }

    if user_id not in MEMORIES_STORE:
        MEMORIES_STORE[user_id] = []
    MEMORIES_STORE[user_id].append(entry)

    return {
        "memory_id": memory_id,
        "user_id": user_id,
        "content": content[:100] + "..." if len(content) > 100 else content,
        "status": "added",
    }


@router.get("/memory/search")
async def search_memory(
    user_id: str,
    query: str,
    limit: int = Query(5, ge=1, le=50),
    current_user: User = Depends(get_current_active_user),
):
    """Search user's memories (semantic search)"""
    memories = MEMORIES_STORE.get(user_id, [])
    if not memories:
        return {
            "user_id": user_id,
            "query": query,
            "results": [],
            "total": 0,
        }

    # Simple text matching (mock semantic search)
    results = []
    query_lower = query.lower()
    for mem in memories:
        score = 0.0
        if query_lower in mem["content"].lower():
            score = 0.9
        elif any(word in mem["content"].lower() for word in query_lower.split()):
            score = 0.5
        if score > 0:
            results.append({**mem, "relevance_score": score})

    results.sort(key=lambda x: x["relevance_score"], reverse=True)
    results = results[:limit]

    return {
        "user_id": user_id,
        "query": query,
        "results": results,
        "total": len(results),
    }


@router.get("/memory/{user_id}")
async def list_memories(
    user_id: str,
    current_user: User = Depends(get_current_active_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """List user's memories"""
    memories = MEMORIES_STORE.get(user_id, [])
    return {
        "user_id": user_id,
        "memories": memories[skip:skip + limit],
        "total": len(memories),
    }


@router.delete("/memory/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Delete a memory entry"""
    for user_id, memories in MEMORIES_STORE.items():
        MEMORIES_STORE[user_id] = [m for m in memories if m["id"] != memory_id]
    return


# ============================================================
# HYBRID SEARCH (Vector + Text)
# ============================================================

@router.post("/collections/{collection_id}/hybrid-search")
async def hybrid_search(
    collection_id: str,
    query_text: str,
    query_vector: List[float],
    top_k: int = Query(5, ge=1, le=100),
    vector_weight: float = Query(0.7, ge=0.0, le=1.0),
    text_weight: float = Query(0.3, ge=0.0, le=1.0),
    current_user: User = Depends(get_current_active_user),
):
    """Hybrid search combining vector similarity and text matching"""
    if collection_id not in COLLECTIONS_STORE:
        raise HTTPException(status_code=404, detail="Collection not found")

    collection = COLLECTIONS_STORE[collection_id]
    if collection["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    vectors = VECTORS_STORE.get(collection_id, [])
    if not vectors:
        return {
            "collection_id": collection_id,
            "results": [],
            "total": 0,
        }

    import math
    results = []
    query_lower = query_text.lower()

    for vec in vectors:
        # Vector similarity
        emb = vec["embedding"]
        dot = sum(a * b for a, b in zip(query_vector, emb))
        norm_a = math.sqrt(sum(a * a for a in query_vector))
        norm_b = math.sqrt(sum(a * a for a in emb))
        vector_sim = dot / (norm_a * norm_b) if norm_a * norm_b > 0 else 0

        # Text match
        content_str = json.dumps(vec.get("metadata", {})).lower()
        text_score = 1.0 if query_lower in content_str else 0.3

        # Combined score
        combined = (vector_weight * vector_sim) + (text_weight * text_score)

        results.append({
            "id": vec["id"],
            "vector_score": round(vector_sim, 4),
            "text_score": round(text_score, 4),
            "combined_score": round(combined, 4),
            "metadata": vec["metadata"],
        })

    results.sort(key=lambda x: x["combined_score"], reverse=True)
    results = results[:top_k]

    return {
        "collection_id": collection_id,
        "results": results,
        "total": len(results),
    }