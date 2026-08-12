local key = KEYS[1]
local now = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local refill_rate = tonumber(ARGV[3])
local requested = tonumber(ARGV[4]) or 1

-- Retrieve existing state
local data = redis.call('HMGET', key, 'tokens', 'last_updated')
local tokens = tonumber(data[1])
local last_updated = tonumber(data[2])

if not tokens or not last_updated then
    -- First request, initialize bucket
    tokens = capacity - requested
    last_updated = now
    redis.call('HMSET', key, 'tokens', tokens, 'last_updated', last_updated)
    local ttl = math.ceil(capacity / refill_rate)
    redis.call('EXPIRE', key, ttl)
    return {1, tokens, 0}
else
    -- Refill tokens based on elapsed time
    local elapsed = math.max(0, now - last_updated)
    local refilled = tokens + (elapsed * refill_rate)
    tokens = math.min(capacity, refilled)
    last_updated = now
    
    if tokens >= requested then
        tokens = tokens - requested
        redis.call('HMSET', key, 'tokens', tokens, 'last_updated', last_updated)
        local ttl = math.ceil(capacity / refill_rate)
        redis.call('EXPIRE', key, ttl)
        return {1, tokens, 0}
    else
        redis.call('HMSET', key, 'tokens', tokens, 'last_updated', last_updated)
        local ttl = math.ceil(capacity / refill_rate)
        redis.call('EXPIRE', key, ttl)
        local wait_time = (requested - tokens) / refill_rate
        return {0, tokens, wait_time}
    end
end
