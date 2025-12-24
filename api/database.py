"""Database connection and queries for Neon PostgreSQL with pgvector."""

import os
import asyncpg
from contextlib import asynccontextmanager
from typing import AsyncGenerator

DATABASE_URL = os.environ.get("DATABASE_URL", "")


class Database:
    """Async database connection manager for Neon PostgreSQL."""

    _pool: asyncpg.Pool | None = None

    @classmethod
    async def get_pool(cls) -> asyncpg.Pool:
        """Get or create connection pool."""
        if cls._pool is None:
            cls._pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=1,
                max_size=5,
                command_timeout=30,
            )
        return cls._pool

    @classmethod
    async def close(cls) -> None:
        """Close the connection pool."""
        if cls._pool:
            await cls._pool.close()
            cls._pool = None


@asynccontextmanager
async def get_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """Get a database connection from the pool."""
    pool = await Database.get_pool()
    async with pool.acquire() as conn:
        yield conn


async def search_articles_hybrid(
    query_embedding: list[float],
    query_text: str,
    limit: int = 5,
    similarity_threshold: float = 0.3
) -> list[dict]:
    """
    Hybrid search combining vector similarity and keyword matching.
    Matches the query pattern used in lost.london/app/api/hume-tool/route.ts

    Args:
        query_embedding: Vector embedding of the query
        query_text: Original query text for keyword matching
        limit: Maximum number of results
        similarity_threshold: Minimum similarity score

    Returns:
        List of matching articles with scores
    """
    import json

    async with get_connection() as conn:
        # Convert embedding to JSON string for PostgreSQL
        embedding_json = json.dumps(query_embedding)

        # Get first word for partial matching
        first_word = query_text.split()[0] if query_text.split() else ""

        results = await conn.fetch("""
            WITH
            vector_results AS (
                SELECT id, 1 - (embedding <=> $1::vector) as vector_score
                FROM knowledge_chunks
                ORDER BY embedding <=> $1::vector
                LIMIT 50
            ),
            keyword_results AS (
                SELECT id,
                    CASE
                        WHEN LOWER(content) LIKE '%' || $2 || '%' THEN 0.30
                        WHEN LOWER(title) LIKE '%' || $2 || '%' THEN 0.25
                        WHEN LOWER(title) LIKE '%' || $3 || '%' THEN 0.10
                        ELSE 0
                    END as keyword_score,
                    CASE
                        WHEN title LIKE 'Vic Keegan%Lost London%' THEN 0.10
                        WHEN source_type = 'article' THEN 0.05
                        ELSE 0
                    END as type_boost
                FROM knowledge_chunks
            )
            SELECT
                kc.id::text,
                kc.title,
                kc.content,
                kc.source_type,
                (COALESCE(vr.vector_score, 0) * 0.6) +
                (COALESCE(kr.keyword_score, 0) * 0.4) +
                COALESCE(kr.type_boost, 0) as score
            FROM knowledge_chunks kc
            LEFT JOIN vector_results vr ON kc.id = vr.id
            LEFT JOIN keyword_results kr ON kc.id = kr.id
            WHERE vr.id IS NOT NULL OR kr.keyword_score > 0
            ORDER BY score DESC
            LIMIT $4
        """, embedding_json, query_text.lower(), first_word.lower(), limit)

        return [dict(r) for r in results]


async def get_cached_response(query: str) -> dict | None:
    """
    Check if we have a cached response for this query or its variations.

    Returns cached response if found, None otherwise.
    """
    query_lower = query.lower().strip()

    async with get_connection() as conn:
        # Check if query matches any variation
        result = await conn.fetchrow("""
            SELECT normalized_query, response_text, article_titles
            FROM vic_response_cache
            WHERE response_text IS NOT NULL
              AND ($1 = ANY(variations) OR normalized_query = $1)
        """, query_lower)

        if result and result['response_text']:
            # Update hit count
            await conn.execute("""
                UPDATE vic_response_cache
                SET hit_count = hit_count + 1, last_hit_at = NOW()
                WHERE normalized_query = $1
            """, result['normalized_query'])

            return {
                "response": result['response_text'],
                "articles": result['article_titles'] or [],
                "cached": True
            }

    return None


async def cache_response(query: str, response: str, article_titles: list[str]) -> None:
    """
    Cache a response for a query.

    If the query matches an existing variation, updates that entry.
    Otherwise creates a new cache entry.
    """
    query_lower = query.lower().strip()

    async with get_connection() as conn:
        # Check if this query matches an existing cache entry's variations
        existing = await conn.fetchrow("""
            SELECT normalized_query FROM vic_response_cache
            WHERE $1 = ANY(variations) OR normalized_query = $1
        """, query_lower)

        if existing:
            # Update existing entry with response
            await conn.execute("""
                UPDATE vic_response_cache
                SET response_text = $1, article_titles = $2, last_hit_at = NOW()
                WHERE normalized_query = $3
            """, response, article_titles, existing['normalized_query'])
        else:
            # Create new cache entry
            await conn.execute("""
                INSERT INTO vic_response_cache (normalized_query, variations, response_text, article_titles)
                VALUES ($1, ARRAY[$1], $2, $3)
                ON CONFLICT (normalized_query) DO UPDATE
                SET response_text = $2, article_titles = $3, last_hit_at = NOW()
            """, query_lower, response, article_titles)


