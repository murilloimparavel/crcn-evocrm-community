-- Rehearsal only. Single-item transfer between logical DBs on standalone Redis.
-- The caller must freeze producers and consumers; this does not solve ordering,
-- job ownership, in-flight work, journaling, or Redis Cluster compatibility.
local source, target = tonumber(ARGV[1]), tonumber(ARGV[2])
local kind, key, payload, inject = ARGV[3], ARGV[4], ARGV[5], ARGV[6]
if not source or not target or source == target or source < 0 or target < 0 then
  return redis.error_reply('invalid databases')
end
if kind ~= 'list' and kind ~= 'zset' then return redis.error_reply('invalid type') end
redis.call('SELECT', source)
local source_type = redis.call('TYPE', key).ok
if source_type ~= kind then return redis.error_reply('source type mismatch') end
local score = nil
if kind == 'list' then
  local count = 0
  for _, v in ipairs(redis.call('LRANGE', key, 0, -1)) do if v == payload then count = count + 1 end end
  if count ~= 1 then return redis.error_reply('source job must be unique') end
else
  score = redis.call('ZSCORE', key, payload)
  if not score then return redis.error_reply('source job missing') end
end
redis.call('SELECT', target)
local target_type = redis.call('TYPE', key).ok
if target_type ~= 'none' and target_type ~= kind then return redis.error_reply('target type mismatch') end
if kind == 'list' then
  for _, v in ipairs(redis.call('LRANGE', key, 0, -1)) do
    if v == payload then return redis.error_reply('job already at target') end
  end
elseif redis.call('ZSCORE', key, payload) then return redis.error_reply('job already at target') end
if inject == 'fail' then return redis.error_reply('injected failure before write') end
-- Redis script errors do not roll back earlier writes. Copy first so a write
-- error cannot silently lose the only copy; duplicate copies need reconciliation.
redis.call('SELECT', target)
if kind == 'list' then redis.call('LPUSH', key, payload) else redis.call('ZADD', key, score, payload) end
if inject == 'after_copy' then return redis.error_reply('injected failure after copy') end
redis.call('SELECT', source)
if kind == 'list' then redis.call('LREM', key, 1, payload) else redis.call('ZREM', key, payload) end
return 'moved'
