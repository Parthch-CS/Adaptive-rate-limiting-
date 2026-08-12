import time
import math
import logging
from typing import Tuple, Dict
from src.enforcement.algorithms.base import BaseRateLimiter
from src.storage.redis_client import RedisClient

logger = logging.getLogger("arl.enforcement.sliding_window")

class SlidingWindowLimiter(BaseRateLimiter):
    def __init__(self, redis_client: RedisClient):
        super().__init__(redis_client)
        # In-memory fallback: client_id -> { window_id: count }
        self._fallback_db: Dict[str, Dict[int, int]] = {}

    async def check_limit(self, client_id: str, rate: float, capacity: float, window_seconds: int, requested: int = 1) -> Tuple[bool, float, float]:
        now = time.time()
        # In sliding window, standard limits are represented as "capacity" requests allowed in "window_seconds"
        limit = capacity
        
        # Check if Redis is initialized and connected
        if self.redis_client.client:
            try:
                key = f"rate:sw:{client_id}"
                
                # Run Redis Lua script
                # KEYS[1] = key
                # ARGV[1] = now, ARGV[2] = window_seconds, ARGV[3] = limit
                result = await self.redis_client.run_script(
                    "sliding_window",
                    keys=[key],
                    args=[str(now), str(window_seconds), str(limit)]
                )
                
                if result is not None:
                    allowed, remaining = result
                    return bool(allowed), float(remaining), 0.0
            except Exception as e:
                logger.error(f"Redis Sliding Window failed, falling back to in-memory: {e}")

        # Fallback to local in-memory Sliding Window
        return self._check_in_memory(client_id, limit, window_seconds, now)

    def _check_in_memory(self, client_id: str, limit: float, window_seconds: int, now: float) -> Tuple[bool, float, float]:
        current_window = math.floor(now / window_seconds)
        previous_window = current_window - 1
        
        if client_id not in self._fallback_db:
            self._fallback_db[client_id] = {}
            
        windows = self._fallback_db[client_id]
        
        # Cleanup old windows to prevent memory leaks
        keys_to_delete = [w for w in windows if w < previous_window]
        for w in keys_to_delete:
            del windows[w]
            
        count_curr = windows.get(current_window, 0)
        count_prev = windows.get(previous_window, 0)
        
        # Weighted interpolation
        time_into_current = now % window_seconds
        weight_curr = time_into_current / window_seconds
        weight_prev = 1.0 - weight_curr
        estimated_count = (count_prev * weight_prev) + count_curr + 1 # +1 to simulate the request we are trying to make
        
        if estimated_count <= limit:
            windows[current_window] = count_curr + 1
            remaining = max(0.0, limit - estimated_count)
            return True, remaining, 0.0
        else:
            return False, 0.0, 0.0
            
    def clear_fallback_db(self):
        self._fallback_db.clear()
