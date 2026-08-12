local key = KEYS[1]
local now = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local leak_rate = tonumber(ARGV[3]) -- tokens/sec drained
local requested = tonumber(ARGV[4]) or 1

-- Retrieve existing state
local data = redis.call('HMGET', key, 'water_level', 'last_leak_time')
local water_level = tonumber(data[1])
local last_leak_time = tonumber(data[2])

if not water_level or not last_leak_time then
    -- First request, initialize bucket
    water_level = requested
    last_leak_time = now
    redis.call('HMSET', key, 'water_level', water_level, 'last_leak_time', last_leak_time)
    local ttl = math.ceil(capacity / leak_rate)
    redis.call('EXPIRE', key, ttl)
    return {1, capacity - water_level}
else
    -- Leak water based on elapsed time
    local elapsed = math.max(0, now - last_leak_time)
    local leaked = elapsed * leak_rate
    water_level = math.max(0.0, water_level - leaked)
    last_leak_time = now
    
    if water_level + requested <= capacity then
        water_level = water_level + requested
        redis.call('HMSET', key, 'water_level', water_level, 'last_leak_time', last_leak_time)
        local ttl = math.ceil(capacity / leak_rate)
        redis.call('EXPIRE', key, ttl)
        return {1, capacity - water_level}
    else
        -- Save the leaked state anyway
        redis.call('HMSET', key, 'water_level', water_level, 'last_leak_time', last_leak_time)
        local ttl = math.ceil(capacity / leak_rate)
        redis.call('EXPIRE', key, ttl)
        return {0, capacity - water_level}
    end
end
