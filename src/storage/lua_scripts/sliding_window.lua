local base_key = KEYS[1]
local now = tonumber(ARGV[1])
local window_size = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])

local current_window = math.floor(now / window_size)
local previous_window = current_window - 1

local key_curr = base_key .. ":" .. current_window
local key_prev = base_key .. ":" .. previous_window

-- Get previous window count
local count_prev = tonumber(redis.call('GET', key_prev) or 0)

-- Increment current window count
local count_curr = tonumber(redis.call('INCR', key_curr))
if count_curr == 1 then
    redis.call('EXPIRE', key_curr, math.ceil(window_size * 2))
end

-- Calculate estimated count using weighted interpolation
local time_into_current = now % window_size
local weight_curr = time_into_current / window_size
local weight_prev = 1.0 - weight_curr
local estimated_count = (count_prev * weight_prev) + count_curr

if estimated_count <= limit then
    local remaining = math.max(0, limit - estimated_count)
    return {1, remaining}
else
    -- Rollback the increment so blocked requests don't penalize the user
    redis.call('DECR', key_curr)
    return {0, 0}
end
