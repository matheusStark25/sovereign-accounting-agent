-- Redis Lua script for hierarchical rate limiting (IP, session, user)
-- KEYS: keys for counters
-- ARGV: limits and window
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local current = tonumber(redis.call('INCR', key))
if current == 1 then
  redis.call('EXPIRE', key, window)
end
if current > limit then
  return {0, current}
end
return {1, current}
