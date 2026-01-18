# core/db_session.py

import asyncpg
from core.config import settings

class DatabaseManager:
    """
    Enterprise Async PostgreSQL connection manager.
    Handles connection pooling for high-concurrency vector DB lookups.
    """
    def __init__(self):
        self.pool = None

    async def init_pool(self):
        try:
            self.pool = await asyncpg.create_pool(
                dsn=settings.POSTGRES_URL,
                min_size=2,
                max_size=10, # Cap the connections to avoid DB overload
                command_timeout=60
            )
            print("[DB] PostgreSQL Async Pool initialized successfully.")
        except Exception as e:
            print(f"[DB Error] Failed to initialize PostgreSQL pool: {e}")
            raise

    async def close(self):
        if self.pool:
            await self.pool.close()
            print("[DB] PostgreSQL connections closed safely.")

db_manager = DatabaseManager()