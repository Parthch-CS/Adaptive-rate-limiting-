import pytest
from unittest.mock import patch
from src.enforcement.algorithms.leaky_bucket import LeakyBucketLimiter

@pytest.mark.asyncio
async def test_leaky_bucket_in_memory(mock_redis_client):
    limiter = LeakyBucketLimiter(mock_redis_client)
    client_id = "test_client_lb"
    
    # Capacity = 3.0, Leak Rate = 1.0 per sec
    with patch('time.time', return_value=100.0):
        # 1st request (water level becomes 1.0)
        allowed, remaining, wait = await limiter.check_limit(client_id, rate=1.0, capacity=3.0, window_seconds=10, requested=1)
        assert allowed is True
        assert remaining == 2.0
        
        # 2nd request (water level becomes 2.0)
        allowed, remaining, wait = await limiter.check_limit(client_id, rate=1.0, capacity=3.0, window_seconds=10, requested=1)
        assert allowed is True
        assert remaining == 1.0
        
        # 3rd request (water level becomes 3.0)
        allowed, remaining, wait = await limiter.check_limit(client_id, rate=1.0, capacity=3.0, window_seconds=10, requested=1)
        assert allowed is True
        assert remaining == 0.0
        
        # 4th request should fail
        allowed, remaining, wait = await limiter.check_limit(client_id, rate=1.0, capacity=3.0, window_seconds=10, requested=1)
        assert allowed is False

    # Time passes: T = 101.0 (1 second later, leaks 1.0 unit of water, water level becomes 2.0)
    with patch('time.time', return_value=101.0):
        # Should allow 1 request (water level becomes 3.0 again)
        allowed, remaining, wait = await limiter.check_limit(client_id, rate=1.0, capacity=3.0, window_seconds=10, requested=1)
        assert allowed is True
        assert remaining == 0.0
        
        # Next request should fail
        allowed, remaining, wait = await limiter.check_limit(client_id, rate=1.0, capacity=3.0, window_seconds=10, requested=1)
        assert allowed is False
