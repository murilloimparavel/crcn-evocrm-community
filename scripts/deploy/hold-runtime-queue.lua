-- Run only with runtime stopped and CRM ingress/Sidekiq drained. Preserve every
-- queued turn and receipt; never decode payloads or issue messages. ARGV contains
-- the complete, sorted ZRANGE snapshot supplied by the operator.
local ready, held = KEYS[1], KEYS[2]
if ready ~= 'bot_runtime:durable:ready' or not string.match(held, '^bot_runtime:rollback:held:[%w_-]+$') then return redis.error_reply('invalid queue keys') end
if redis.call('EXISTS', held) ~= 0 then return redis.error_reply('hold key already exists') end
local kind = redis.call('TYPE', ready).ok
if kind ~= 'none' and kind ~= 'zset' then return redis.error_reply('invalid queue type') end
local entries = redis.call('ZRANGE', ready, 0, -1)
if #entries ~= #ARGV then return redis.error_reply('queue changed') end
for i, key in ipairs(entries) do
  if key ~= ARGV[i] then return redis.error_reply('queue changed') end
  if not string.match(key, '^bot_runtime:durable:%d+:%d+$') then return redis.error_reply('invalid turn key') end
  if redis.call('EXISTS', key) ~= 1 then return redis.error_reply('turn missing') end
  if redis.call('EXISTS', key .. ':lease') ~= 0 then return redis.error_reply('active lease') end
end
if #entries == 0 then return 0 end
redis.call('RENAME', ready, held)
return #entries
