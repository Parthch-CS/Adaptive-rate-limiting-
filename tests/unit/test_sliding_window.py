import pytest
from unittest.mock import patch
from src.enforcement.algorithms.sliding_window import SlidingWindowLimiter

@pytest.mark.asyncio
async def test_sliding_window_in_memory(mock_redis_client):
    limiter = SlidingWindowLimiter(mock_redis_client)
    client_id = "test_client_sw"
    
    # window_seconds = 10, capacity (limit) = 5.0
    # First window: T = 100.0 to 110.0
    # At T = 105.0 (midpoint of current window)
    with patch('time.time', return_value=105.0):
        for i in range(5):
            allowed, remaining, wait = await limiter.check_limit(client_id, rate=0.5, capacity=5.0, window_seconds=10, requested=1)
            assert allowed is True
            
        # 6th request should fail
        allowed, remaining, wait = await limiter.check_limit(client_id, rate=0.5, capacity=5.0, window_seconds=10, requested=1)
        assert allowed is False
        
    # Second window: T = 115.0 (midpoint of second window)
    # The previous window (T=100-110) had 5 requests.
    # At T = 115.0, time_into_current = 115.0 % 10 = 5.0
    # weight_curr = 5.0 / 10.0 = 0.5, weight_prev = 0.5
    # The estimated count = (count_prev * 0.5) + count_curr + 1
    # 1st request: (5 * 0.5) + 0 + 1 = 3.5 <= 5.0 (Allowed, count_curr becomes 1)
    # 2nd request: (5 * 0.5) + 1 + 1 = 4.5 <= 5.0 (Allowed, count_curr becomes 2)
    # 3rd request: (5 * 0.5) + 2 + 1 = 5.5 > 5.0 (Blocked)
    with patch('time.time', return_value=115.0):
        # 1st request should be allowed
        allowed, remaining, wait = await limiter.check_limit(client_id, rate=0.5, capacity=5.0, window_seconds=10, requested=1)
        assert allowed is True
        
        # 2nd request should be allowed
        allowed, remaining, wait = await limiter.check_limit(client_id, rate=0.5, capacity=5.0, window_seconds=10, requested=1)
        assert allowed is True
        
        # 3rd request should be blocked
        allowed, remaining, wait = await limiter.check_limit(client_id, rate=0.5, capacity=5.0, window_seconds=10, requested=1)
        assert allowed is False
