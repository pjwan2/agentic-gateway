# api/middlewares/context_injector.py

import asyncpg
from fastapi import Request

class HermesMemoryInjector:
    def __init__(self, db_pool: asyncpg.Pool):
        self.db_pool = db_pool

    async def _fetch_user_profile(self, user_id: str) -> str:
        # Fallback if DB pool isn't ready
        if not self.db_pool:
            return "No memory context available (DB disconnected)."

        query = "SELECT profile_summary FROM user_memories WHERE user_id = $1"
        
        try:
            async with self.db_pool.acquire() as conn:
                record = await conn.fetchrow(query, user_id)
                if record:
                    return record['profile_summary']
                return "No prior memory context available."
        except asyncpg.exceptions.UndefinedTableError:
            # Defensive code: if the table doesn't exist yet, don't crash the gateway
            print("[Warning] 'user_memories' table not found. Skipping memory injection.")
            return "No prior memory context available."
        except Exception as e:
            print(f"[Error] Memory fetch failed: {e}")
            return "No prior memory context available."

    async def inject(self, request: Request, raw_prompt: str) -> str:
        # user_id is set by AuthMiddleware on request.state — trusted, not spoofable
        user_id = getattr(request.state, "user_id", "anonymous")
        if user_id == "anonymous":
            return raw_prompt
            
        user_memory = await self._fetch_user_profile(user_id)
        
        # Assemble the Augmented Prompt invisibly
        augmented_prompt = f"""
<System_Memory>
You are an intelligent agent. Rely on the following historical profile to personalize your analysis:
{user_memory}
</System_Memory>

<User_Current_Query>
{raw_prompt}
</User_Current_Query>
        """
        return augmented_prompt