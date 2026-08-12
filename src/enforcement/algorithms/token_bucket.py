import time
import logging
from typing import Tuple, Dict
from src.enforcement.algorithms.base import BaseRateLimiter
from src.storage.redis_client import RedisClient

logger = logging.getLogger("arl.enforcement.token_bucket")

class TokenBucketLimiter(BaseRateLimiter):
    def __init__(self, redis_client: RedisClient):
        super().__init__(redis_client)
        # In-memory fallback database when Redis is down
        self._fallback_db: Dict[str, Tuple[float, float]] = {}

    async def check_limit(self, client_id: str, rate: float, capacity: float, window_seconds: int, requested: int = 1) -> Tuple[bool, float, float]:
        now = time.time()
        
        # Check if Redis is initialized and connected
        if self.redis_client.client:
            try:
                # Key format: config prefix + rate limit algorithm identifier + client_id
                key = f"rate:tb:{client_id}"
                
                # Run Redis Lua script
                # KEYS[1] = key
                # ARGV[1] = now, ARGV[2] = capacity, ARGV[3] = refill_rate, ARGV[4] = requested
                result = await self.redis_client.run_script(
                    "token_bucket",
                    keys=[key],
                    args=[str(now), str(capacity), str(rate), str(requested)]
                )
                
                if result is not None:
                    allowed, remaining, wait_time = result
                    return bool(allowed), float(remaining), float(wait_time)
            except Exception as e:
                logger.error(f"Redis Token Bucket failed, falling back to in-memory: {e}")

        # Fallback to local in-memory Token Bucket
        return self._check_in_memory(client_id, rate, capacity, requested, now)

    def _check_in_memory(self, client_id: str, rate: float, capacity: float, requested: int, now: float) -> Tuple[bool, float, float]:
        state = self._fallback_db.get(client_id)
        if state is None:
            tokens = capacity - requested
            self._fallback_db[client_id] = (tokens, now)
            return True, tokens, 0.0
        
        last_tokens, last_updated = state
        elapsed = max(0.0, now - last_updated)
        tokens = min(capacity, last_tokens + (elapsed * rate))
        
        if tokens >= requested:
            tokens -= requested
            self._fallback_db[client_id] = (tokens, now)
            return True, tokens, 0.0
        else:
            self._fallback_db[client_id] = (tokens, now)
            wait_time = (requested - tokens) / rate
            return False, tokens, wait_time
            
    def clear_fallback_db(self):
        self._fallback_db.clear()
