#!/bin/sh
# Run on a Docker host with the production images already present. This uses
# synthetic workers, an isolated network and a disposable Redis with no volumes.
set -eu
tag="queue-rehearsal-$$"
dir=$(mktemp -d)
cleanup() {
  docker rm -f "$tag-auth" "$tag-crm" "$tag-redis" >/dev/null 2>&1 || true
  docker network rm "$tag" >/dev/null 2>&1 || true
  rm -rf "$dir"
}
trap cleanup EXIT HUP INT TERM
chmod 755 "$dir"
cat > "$dir/jobs.rb" <<'RUBY'
require 'sidekiq'
require 'redis'
class SyntheticQueueJob
  include Sidekiq::Job
  def perform(value)
    Redis.new(url: ENV.fetch('REDIS_URL')).rpush('rehearsal:completed', value)
  end
end
RUBY
chmod 644 "$dir/jobs.rb"
docker network create --internal "$tag" >/dev/null
docker run -d --name "$tag-redis" --network "$tag" redis:alpine redis-server --save '' --appendonly no >/dev/null
for n in $(seq 1 30); do
  if docker exec "$tag-redis" redis-cli ping 2>/dev/null | grep -q PONG; then break; fi
  sleep 1
done
docker run -d --name "$tag-crm" --network "$tag" --entrypoint bundle -v "$dir:/fixtures:ro" -e "REDIS_URL=redis://$tag-redis:6379/1" "${CRM_IMAGE:?}" exec sidekiq -r /fixtures/jobs.rb -q default -c 1 >/dev/null
docker run -d --name "$tag-auth" --network "$tag" --entrypoint bundle -v "$dir:/fixtures:ro" -e "REDIS_URL=redis://$tag-redis:6379/3" "${AUTH_IMAGE:?}" exec sidekiq -r /fixtures/jobs.rb -q default -c 1 >/dev/null
for n in $(seq 1 45); do
  if [ "$(docker exec "$tag-redis" redis-cli -n 1 scard processes)" = 1 ] && [ "$(docker exec "$tag-redis" redis-cli -n 3 scard processes)" = 1 ]; then break; fi
  sleep 1
done
test "$(docker exec "$tag-redis" redis-cli -n 1 scard processes)" = 1
test "$(docker exec "$tag-redis" redis-cli -n 3 scard processes)" = 1
docker exec "$tag-crm" bundle exec ruby -r /fixtures/jobs.rb -e 'Sidekiq::Client.push("class" => "SyntheticQueueJob", "queue" => "default", "args" => ["crm"], "retry" => false)' >/dev/null
docker exec "$tag-auth" bundle exec ruby -r /fixtures/jobs.rb -e 'Sidekiq::Client.push("class" => "SyntheticQueueJob", "queue" => "default", "args" => ["auth"], "retry" => false)' >/dev/null
for n in $(seq 1 45); do
  if [ "$(docker exec "$tag-redis" redis-cli -n 1 llen rehearsal:completed)" = 1 ] && [ "$(docker exec "$tag-redis" redis-cli -n 3 llen rehearsal:completed)" = 1 ]; then break; fi
  sleep 1
done
test "$(docker exec "$tag-redis" redis-cli -n 1 lrange rehearsal:completed 0 -1)" = crm
test "$(docker exec "$tag-redis" redis-cli -n 3 lrange rehearsal:completed 0 -1)" = auth
# Simulate a quiesced rollback with a pending auth job and preserve a CRM retry.
docker stop -t 30 "$tag-auth" >/dev/null
docker stop -t 30 "$tag-crm" >/dev/null
docker exec "$tag-redis" redis-cli -n 1 zadd retry 4102444800 '{"class":"SyntheticQueueJob","args":["crm-retry"],"jid":"crm-retry"}' >/dev/null
docker exec "$tag-redis" redis-cli -n 3 lpush queue:default '{"class":"SyntheticQueueJob","args":["auth-rollback"],"jid":"auth-rollback","queue":"default"}' >/dev/null
pending=$(docker exec "$tag-redis" redis-cli -n 3 rpop queue:default)
docker exec "$tag-redis" redis-cli -n 1 lpush queue:default "$pending" >/dev/null
docker rm "$tag-auth" >/dev/null
docker run -d --name "$tag-auth" --network "$tag" --entrypoint bundle -v "$dir:/fixtures:ro" -e "REDIS_URL=redis://$tag-redis:6379/1" "${AUTH_IMAGE:?}" exec sidekiq -r /fixtures/jobs.rb -q default -c 1 >/dev/null
for n in $(seq 1 45); do
  if [ "$(docker exec "$tag-redis" redis-cli -n 1 llen rehearsal:completed)" = 2 ]; then break; fi
  sleep 1
done
test "$(docker exec "$tag-redis" redis-cli -n 1 lindex rehearsal:completed 1)" = auth-rollback
test "$(docker exec "$tag-redis" redis-cli -n 1 zcard retry)" = 1
test "$(docker exec "$tag-redis" redis-cli -n 3 llen queue:default)" = 0
printf '%s\n' 'PASS: real image runtimes isolated; synthetic pending job consumed after quiesced rollback; CRM retry retained'
