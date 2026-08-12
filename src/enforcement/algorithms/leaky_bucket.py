import time
import logging
from typing import Tuple, Dict
from src.enforcement.algorithms.base import BaseRateLimiter
from src.storage.redis_client import RedisClient

logger = logging.getLogger("arl.enforcement.leaky_bucket")

class LeakyBucketLimiter(BaseRateLimiter):
    def __init__(self, redis_client: RedisClient):
        super().__init__(redis_client)
        # In-memory fallback: client_id -> (water_level, last_leak_time)
        self._fallback_db: Dict[str, Tuple[float, float]] = {}

    async def check_limit(self, client_id: str, rate: float, capacity: float, window_seconds: int, requested: int = 1) -> Tuple[bool, float, float]:
        now = time.time()
        
        # Check if Redis is initialized and connected
        if self.redis_client.client:
            try:
                key = f"rate:lb:{client_id}"
                
                # Run Redis Lua script
                # KEYS[1] = key
                # ARGV[1] = now, ARGV[2] = capacity, ARGV[3] = rate (leak_rate), ARGV[4] = requested
                result = await self.redis_client.run_script(
                    "leaky_bucket",
                    keys=[key],
                    args=[str(now), str(capacity), str(rate), str(requested)]
                )
                
                if result is not None:
                    allowed, remaining_capacity = result
                    return bool(allowed), float(remaining_capacity), 0.0
            except Exception as e:
                logger.error(f"Redis Leaky Bucket failed, falling back to in-memory: {e}")

        # Fallback to local in-memory Leaky Bucket
        return self._check_in_memory(client_id, rate, capacity, requested, now)

    def _check_in_memory(self, client_id: str, rate: float, capacity: float, requested: int, now: float) -> Tuple[bool, float, float]:
        state = self._fallback_db.get(client_id)
        if state is None:
            water_level = float(requested)
            self._fallback_db[client_id] = (water_level, now)
            return True, capacity - water_level, 0.0
            
        last_water, last_leak_time = state
        elapsed = max(0.0, now - last_leak_time)
        leaked = elapsed * rate
        water_level = max(0.0, last_water - leaked)
        
        if water_level + requested <= capacity:
            water_level += requested
            self._fallback_db[client_id] = (water_level, now)
            return True, capacity - water_level, 0.0
        else:
            self._fallback_db[client_id] = (water_level, now)
            return False, capacity - water_level, 0.0
            
    def clear_fallback_db(self):
        self._fallback_db.clear()
