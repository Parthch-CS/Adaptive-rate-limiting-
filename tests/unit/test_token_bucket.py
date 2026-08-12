import pytest
from unittest.mock import patch
from src.enforcement.algorithms.token_bucket import TokenBucketLimiter

@pytest.mark.asyncio
async def test_token_bucket_in_memory(mock_redis_client):
    limiter = TokenBucketLimiter(mock_redis_client)
    client_id = "test_client_tb"
    
    # Capacity = 4.0, Rate = 2.0 per sec
    with patch('time.time', return_value=100.0):
        # Consume 1st token
        allowed, remaining, wait = await limiter.check_limit(client_id, rate=2.0, capacity=4.0, window_seconds=10, requested=1)
        assert allowed is True
        assert remaining == 3.0
        assert wait == 0.0
        
        # Consume remaining 3 tokens
        for i in range(3):
            allowed, remaining, wait = await limiter.check_limit(client_id, rate=2.0, capacity=4.0, window_seconds=10, requested=1)
            assert allowed is True
            
        # 5th request should fail
        allowed, remaining, wait = await limiter.check_limit(client_id, rate=2.0, capacity=4.0, window_seconds=10, requested=1)
        assert allowed is False
        assert wait == 0.5 # (1 needed token - 0 tokens) / 2.0 rate = 0.5 sec

    # Time passes: T = 101.0 (1 second later, refills 2.0 tokens)
    with patch('time.time', return_value=101.0):
        # 1st request should succeed (refilled tokens: 2.0, remaining: 1.0)
        allowed, remaining, wait = await limiter.check_limit(client_id, rate=2.0, capacity=4.0, window_seconds=10, requested=1)
        assert allowed is True
        
        # 2nd request should succeed (remaining: 0.0)
        allowed, remaining, wait = await limiter.check_limit(client_id, rate=2.0, capacity=4.0, window_seconds=10, requested=1)
        assert allowed is True
        
        # 3rd request should fail
        allowed, remaining, wait = await limiter.check_limit(client_id, rate=2.0, capacity=4.0, window_seconds=10, requested=1)
        assert allowed is False
        assert wait == 0.5
