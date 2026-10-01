from pgvector.psycopg import register_vector_async
from psycopg_pool import AsyncConnectionPool


async def open_pool(url: str, max_size: int = 10) -> AsyncConnectionPool:
    pool = AsyncConnectionPool(
        url, min_size=1, max_size=max_size, open=False, configure=register_vector_async
    )
    await pool.open(wait=True)
    return pool
