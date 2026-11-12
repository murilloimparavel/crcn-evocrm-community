-- REHEARSAL ONLY: one synthetic list job, standalone Redis, quiesced clients.
-- Journal permits reconciliation after a partial write; it is not durable proof
-- across Redis loss and must not be used as a production migration procedure.
local mode, src, dst, key, journal, payload, inject = ARGV[1], tonumber(ARGV[2]), tonumber(ARGV[3]), ARGV[4], ARGV[5], ARGV[6], ARGV[7]
if not src or not dst or src == dst or key == journal then return redis.error_reply('invalid input') end
local function read(db, k)
  redis.call('SELECT', db)
  local t = redis.call('TYPE', k).ok
  if t ~= 'none' and t ~= 'list' then return nil end
  return redis.call('LRANGE', k, 0, -1)
end
local function equal(a, b)
  if #a ~= #b then return false end
  for i = 1, #a do if a[i] ~= b[i] then return false end end
  return true
end
local function replace(db, k, values)
  redis.call('SELECT', db); redis.call('DEL', k)
  for _, value in ipairs(values) do redis.call('RPUSH', k, value) end
end
redis.call('SELECT', src)
local saved = redis.call('GET', journal)
if mode == 'move' then
  if saved then return redis.error_reply('journal already exists') end
  local before, target = read(src, key), read(dst, key)
  if not before or not target or #target ~= 0 then return redis.error_reply('invalid queue state') end
  local after, count = {}, 0
  for _, value in ipairs(before) do
    if value == payload then count = count + 1 else after[#after + 1] = value end
  end
  if count ~= 1 then return redis.error_reply('job must occur once') end
  redis.call('SELECT', src)
  redis.call('SET', journal, cjson.encode({before=before, after=after, target=target, payload=payload}))
  if inject == 'after_journal' then return redis.error_reply('injected after journal') end
  redis.call('SELECT', dst); redis.call('LPUSH', key, payload)
  if inject == 'after_copy' then return redis.error_reply('injected after copy') end
  redis.call('SELECT', src); redis.call('LREM', key, 1, payload)
  return 'moved'
elseif mode == 'rollback' then
  if not saved then return redis.error_reply('journal missing') end
  local j = cjson.decode(saved)
  local actual, target = read(src, key), read(dst, key)
  if not actual or not target then return redis.error_reply('invalid queue type') end
  if equal(actual, j.before) and equal(target, j.target) then
    redis.call('SELECT', src); redis.call('DEL', journal); return 'restored'
  end
  if not (equal(actual, j.before) or equal(actual, j.after)) or not equal(target, {j.payload}) then
    return redis.error_reply('queue drift; manual reconciliation required')
  end
  replace(src, key, j.before)
  replace(dst, key, j.target)
  redis.call('SELECT', src); redis.call('DEL', journal)
  return 'restored'
end
return redis.error_reply('invalid mode')
