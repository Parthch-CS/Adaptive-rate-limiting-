from abc import ABC, abstractmethod
from src.storage.redis_client import RedisClient

class BaseRateLimiter(ABC):
    def __init__(self, redis_client: RedisClient):
        self.redis_client = redis_client

    @abstractmethod
    async def check_limit(self, client_id: str, rate: float, capacity: float, window_seconds: int, requested: int = 1) -> tuple[bool, float, float]:
        """
        Check rate limit for client.
        
        Args:
            client_id: Unique identifier for the client (e.g. prefix + IP + endpoint)
            rate: Limit refill rate (or requests allowed per second/window)
            capacity: Maximum burst capacity (or threshold limit)
            window_seconds: Time window in seconds (used for sliding window)
            requested: Number of tokens/requests consumed (default: 1)
            
        Returns:
            Tuple of:
                - allowed (bool): True if request is allowed, False otherwise
                - remaining (float): Approximate remaining capacity/tokens/count
                - wait_time (float): Seconds to wait before retrying (0.0 if allowed)
        """
        pass
