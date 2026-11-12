#!/bin/sh
# Disposable Sidekiq cutover; synthetic jobs in the real Auth image.
set -eu
tag="queueflight-$$"
dir=$(mktemp -d)
cleanup() {
  docker rm -f "$tag-old" "$tag-new" "$tag-redis" >/dev/null 2>&1 || true
  docker network rm "$tag" >/dev/null 2>&1 || true
  rm -rf "$dir"
}
trap cleanup EXIT HUP INT TERM
chmod 755 "$dir"
cp "$ORDERED_LUA" "$dir/ordered.lua"
cp "$TRANSFER_LUA" "$dir/transfer.lua"
cat > "$dir/jobs.rb" <<'RUBY'
require 'sidekiq'
require 'redis'
class SyntheticCutoverJob
  include Sidekiq::Job
  def perform(id)
    r = Redis.new(url: ENV.fetch('REDIS_URL'))
    if id == 'running'
      r.rpush('qa:started', id)
      raise 'test release timeout' unless r.blpop('qa:release', timeout: 60)
    end
    r.rpush('qa:completed', id)
  end
end
RUBY
chmod 644 "$dir"/*
docker network create --internal "$tag" >/dev/null
docker run -d --name "$tag-redis" --network "$tag" -v "$dir:/fixtures:ro" redis:alpine redis-server --save '' --appendonly no >/dev/null
for n in $(seq 1 30); do docker exec "$tag-redis" redis-cli ping 2>/dev/null | grep -q PONG && break; sleep 1; done
docker run -d --name "$tag-old" --network "$tag" --entrypoint bundle -v "$dir:/fixtures:ro" -e "REDIS_URL=redis://$tag-redis:6379/1" "${AUTH_IMAGE:?}" exec sidekiq -r /fixtures/jobs.rb -q default -c 1 >/dev/null
for n in $(seq 1 45); do [ "$(docker exec "$tag-redis" redis-cli -n 1 scard processes)" = 1 ] && break; sleep 1; done
test "$(docker exec "$tag-redis" redis-cli -n 1 scard processes)" = 1
docker exec "$tag-old" bundle exec ruby -r /fixtures/jobs.rb -e 'Sidekiq::Client.push("class"=>"SyntheticCutoverJob", "queue"=>"default", "args"=>["running"], "retry"=>false)' >/dev/null
for n in $(seq 1 45); do [ "$(docker exec "$tag-redis" redis-cli -n 1 llen qa:started)" = 1 ] && break; sleep 1; done
test "$(docker exec "$tag-redis" redis-cli -n 1 lindex qa:started 0)" = running
docker kill --signal TSTP "$tag-old" >/dev/null
docker exec "$tag-old" bundle exec ruby -r /fixtures/jobs.rb -e 'Sidekiq::Client.push("class"=>"SyntheticCutoverJob", "queue"=>"default", "args"=>["arrived-during-cut"], "retry"=>false)' >/dev/null
test "$(docker exec "$tag-redis" redis-cli -n 1 llen queue:default)" = 1
docker exec "$tag-redis" redis-cli -n 1 lpush qa:release go >/dev/null
for n in $(seq 1 45); do [ "$(docker exec "$tag-redis" redis-cli -n 1 llen qa:completed)" = 1 ] && break; sleep 1; done
test "$(docker exec "$tag-redis" redis-cli -n 1 lindex qa:completed 0)" = running
test "$(docker exec "$tag-redis" redis-cli -n 1 llen queue:default)" = 1
docker stop -t 30 "$tag-old" >/dev/null
payload=$(docker exec "$tag-redis" redis-cli -n 1 --raw lindex queue:default 0)
test "$(docker exec "$tag-redis" redis-cli --raw --eval /fixtures/ordered.lua , move 1 3 queue:default qa:journal "$payload" none)" = moved
docker run -d --name "$tag-new" --network "$tag" --entrypoint bundle -v "$dir:/fixtures:ro" -e "REDIS_URL=redis://$tag-redis:6379/3" "$AUTH_IMAGE" exec sidekiq -r /fixtures/jobs.rb -q default -c 1 >/dev/null
for n in $(seq 1 45); do [ "$(docker exec "$tag-redis" redis-cli -n 3 llen qa:completed)" = 1 ] && break; sleep 1; done
test "$(docker exec "$tag-redis" redis-cli -n 3 lindex qa:completed 0)" = arrived-during-cut
docker stop -t 30 "$tag-new" >/dev/null
result=$(docker exec "$tag-redis" redis-cli --raw --eval /fixtures/ordered.lua , rollback 1 3 queue:default qa:journal "$payload" none)
case "$result" in *'queue drift'*) ;; *) exit 1 ;; esac
test "$(docker exec "$tag-redis" redis-cli -n 1 llen qa:completed)" = 1
test "$(docker exec "$tag-redis" redis-cli -n 3 llen qa:completed)" = 1
test "$(docker exec "$tag-redis" redis-cli -n 1 llen queue:default)" = 0
# The test-only completion marker is an authoritative receipt for this fixture.
# Real jobs do not necessarily have this receipt; do not copy this to production.
docker exec "$tag-redis" redis-cli -n 1 del qa:journal >/dev/null
docker rm "$tag-new" >/dev/null
docker run -d --name "$tag-new" --network "$tag" --entrypoint bundle -v "$dir:/fixtures:ro" -e "REDIS_URL=redis://$tag-redis:6379/3" "$AUTH_IMAGE" exec sidekiq -r /fixtures/jobs.rb -q default -c 1 >/dev/null
for n in $(seq 1 45); do [ "$(docker exec "$tag-redis" redis-cli -n 3 scard processes)" = 1 ] && break; sleep 1; done
docker kill --signal TSTP "$tag-new" >/dev/null
docker exec "$tag-new" bundle exec ruby -r /fixtures/jobs.rb -e '
  r = Redis.new(url: ENV.fetch("REDIS_URL"))
  Sidekiq::Client.push("class"=>"SyntheticCutoverJob", "queue"=>"default", "args"=>["pending-after-cut"], "retry"=>false)
  Sidekiq::Client.push("class"=>"SyntheticCutoverJob", "queue"=>"default", "args"=>["scheduled-after-cut"], "at"=>Time.now.to_f+3600)
  jid = Sidekiq::Client.push("class"=>"SyntheticCutoverJob", "queue"=>"default", "args"=>["retry-after-cut"])
  raw = r.lrange("queue:default",0,-1).find { |s| JSON.parse(s)["jid"] == jid }
  raise "missing retry" unless raw && r.lrem("queue:default",1,raw) == 1
  r.zadd("retry",Time.now.to_f+7200,raw)
' >/dev/null
docker stop -t 30 "$tag-new" >/dev/null
pending=$(docker exec "$tag-redis" redis-cli -n 3 --raw lindex queue:default 0)
scheduled=$(docker exec "$tag-redis" redis-cli -n 3 --raw zrange schedule 0 0)
retry=$(docker exec "$tag-redis" redis-cli -n 3 --raw zrange retry 0 0)
schedule_score=$(docker exec "$tag-redis" redis-cli -n 3 --raw zscore schedule "$scheduled")
retry_score=$(docker exec "$tag-redis" redis-cli -n 3 --raw zscore retry "$retry")
test -n "$pending"; test -n "$scheduled"; test -n "$retry"
test "$(docker exec "$tag-redis" redis-cli --raw --eval /fixtures/ordered.lua , move 3 1 queue:default qa:journal "$pending" none)" = moved
test "$(docker exec "$tag-redis" redis-cli --raw --eval /fixtures/transfer.lua , 3 1 zset schedule "$scheduled" none)" = moved
test "$(docker exec "$tag-redis" redis-cli --raw --eval /fixtures/transfer.lua , 3 1 zset retry "$retry" none)" = moved
test "$(docker exec "$tag-redis" redis-cli -n 1 --raw zscore schedule "$scheduled")" = "$schedule_score"
test "$(docker exec "$tag-redis" redis-cli -n 1 --raw zscore retry "$retry")" = "$retry_score"
docker rm "$tag-old" >/dev/null
docker run -d --name "$tag-old" --network "$tag" --entrypoint bundle -v "$dir:/fixtures:ro" -e "REDIS_URL=redis://$tag-redis:6379/1" "$AUTH_IMAGE" exec sidekiq -r /fixtures/jobs.rb -q default -c 1 >/dev/null
for n in $(seq 1 45); do [ "$(docker exec "$tag-redis" redis-cli -n 1 llen qa:completed)" = 2 ] && break; sleep 1; done
test "$(docker exec "$tag-redis" redis-cli -n 1 lindex qa:completed 1)" = pending-after-cut
test "$(docker exec "$tag-redis" redis-cli -n 3 llen qa:completed)" = 1
test "$(docker exec "$tag-redis" redis-cli -n 1 zcard schedule)" = 1
test "$(docker exec "$tag-redis" redis-cli -n 1 zcard retry)" = 1
printf '%s\n' 'PASS: in-flight drained, post-cut completed not replayed, pending restored, schedule and retry scores retained'
