import redis.asyncio as redis
from core.config import settings

class RedisManager:
    def __init__(self):
        self.client = None

    async def init_pool(self):

        self.client = redis.ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=100,
            decode_responses=True
        )
        self.redis = redis.Redis(connection_pool=self.client)

    async def close(self):
        await self.client.disconnect()

redis_manager = RedisManager()