# Run only inside the disposable Rails rehearsal with both workers stopped.
require 'redis'
require 'json'
require 'uri'
u = URI(ENV.fetch('REDIS_URL'))
raise 'unexpected isolated database' unless u.path == '/3'
u.path = '/1'
source_url = u.to_s
Sidekiq.configure_client { |c| c.redis = { url: source_url } }
source = Redis.new(url: source_url)
u.path = '/3'
target = Redis.new(url: u.to_s)
raise 'target not empty' unless target.dbsize.zero?

# Use real Rails producers, then seed a retry from an actual serialized job.
pending = Licensing::HeartbeatJob.perform_later(nil)
retry_job = Licensing::HeartbeatJob.perform_later(nil)
scheduled = Licensing::HeartbeatJob.set(wait: 3600).perform_later(nil)
raise 'enqueue failed' unless [pending, retry_job, scheduled].all?(&:successfully_enqueued?)
key = 'queue:licensing'
jobs = source.lrange(key, 0, -1)
find = ->(list, job) { list.find { |v| JSON.parse(v)['jid'] == job.provider_job_id } }
pending_raw = find.call(jobs, pending)
retry_raw = find.call(jobs, retry_job)
raise 'missing pending or retry fixture' unless pending_raw && retry_raw
raise 'retry fixture mismatch' unless source.lrem(key, 1, retry_raw) == 1
retry_score = Time.now.to_f + 7200
source.zadd('retry', retry_score, retry_raw)
schedule_raw = find.call(source.zrange('schedule', 0, -1), scheduled)
raise 'missing scheduled fixture' unless schedule_raw
schedule_score = source.zscore('schedule', schedule_raw)
# Markers model unrelated CRM jobs in front and behind the real Auth payload.
source.lpush(key, 'unrelated-new')
source.rpush(key, 'unrelated-old')
original = source.lrange(key, 0, -1)
ordered = File.read('/fixtures/ordered-rollback.lua')
transfer = File.read('/fixtures/atomic-transfer.lua')
def script(redis, script, args)
  redis.eval(script, keys: [], argv: args)
end
begin
  script(source, ordered, ['move', 1, 3, key, 'qa:journal', pending_raw, 'after_copy'])
  raise 'injected failure missing'
rescue Redis::CommandError => e
  raise unless e.message.include?('injected after copy')
end
raise 'rollback failed' unless script(source, ordered, ['rollback', 1, 3, key, 'qa:journal', pending_raw, 'none']) == 'restored'
raise 'order or duplication mismatch' unless source.lrange(key, 0, -1) == original && target.lrange(key, 0, -1).empty?
raise 'pending migration failed' unless script(source, ordered, ['move', 1, 3, key, 'qa:journal', pending_raw, 'none']) == 'moved'
[['schedule', schedule_raw, schedule_score], ['retry', retry_raw, retry_score]].each do |name, raw, score|
  raise 'sorted transfer failed' unless script(source, transfer, [1, 3, 'zset', name, raw, 'none']) == 'moved'
  raise 'score changed' unless target.zscore(name, raw) == score
end
raise 'pending rollback failed' unless script(source, ordered, ['rollback', 1, 3, key, 'qa:journal', pending_raw, 'none']) == 'restored'
[['schedule', schedule_raw, schedule_score], ['retry', retry_raw, retry_score]].each do |name, raw, score|
  raise 'sorted rollback failed' unless script(source, transfer, [3, 1, 'zset', name, raw, 'none']) == 'moved'
  raise 'score changed on rollback' unless source.zscore(name, raw) == score && target.zscore(name, raw).nil?
end
raise 'queue order changed on rollback' unless source.lrange(key, 0, -1) == original
['unrelated-new', pending_raw, 'unrelated-old'].each { |raw| raise 'fixture cleanup failed' unless source.lrem(key, 1, raw) == 1 }
raise 'scheduled cleanup failed' unless source.zrem('schedule', schedule_raw)
raise 'retry cleanup failed' unless source.zrem('retry', retry_raw)
puts 'PASS real ActiveJob payloads: pending, scheduled and retry migrated and restored with exact ordering and scores'
