#!/usr/bin/env python3
"""Exercise queue separation on a disposable Redis, without production data."""
import json
import os
import subprocess
import tempfile
import time


def main():
    with tempfile.TemporaryDirectory(prefix="evocrm-redis-rehearsal-") as folder:
        socket = os.path.join(folder, "redis.sock")
        server = subprocess.Popen(
            ["redis-server", "--port", "0", "--unixsocket", socket, "--save", "", "--appendonly", "no"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(100):
                if os.path.exists(socket):
                    break
                if server.poll() is not None:
                    raise RuntimeError("Redis failed to start")
                time.sleep(0.02)
            else:
                raise RuntimeError("Redis socket did not appear")

            def redis(database, *arguments):
                return subprocess.check_output(
                    ["redis-cli", "-s", socket, "-n", str(database), "--raw", *map(str, arguments)],
                    text=True,
                ).strip()

            crm_job = json.dumps({"class": "Webhooks::EvolutionHubEventsJob", "jid": "crm-test"})
            auth_job = json.dumps({"class": "Licensing::HeartbeatJob", "jid": "auth-test"})
            redis(1, "LPUSH", "queue:default", crm_job)
            redis(1, "ZADD", "retry", 100, crm_job)
            redis(3, "LPUSH", "queue:default", auth_job)
            assert json.loads(redis(3, "RPOP", "queue:default"))["jid"] == "auth-test"
            assert json.loads(redis(1, "RPOP", "queue:default"))["jid"] == "crm-test"
            assert json.loads(redis(1, "ZRANGE", "retry", 0, -1))["jid"] == "crm-test"
            assert redis(3, "ZCARD", "retry") == "0"

            # A quiesced queue can be drained before returning producers to the old DB.
            redis(3, "LPUSH", "queue:default", auth_job)
            pending = redis(3, "RPOP", "queue:default")
            redis(1, "LPUSH", "queue:default", pending)
            assert json.loads(redis(1, "RPOP", "queue:default"))["jid"] == "auth-test"
            assert json.loads(redis(1, "ZRANGE", "retry", 0, -1))["jid"] == "crm-test"
            print("PASS: isolated synthetic queues, preserved retry and quiesced rollback")
        finally:
            server.terminate()
            server.wait(timeout=5)


if __name__ == "__main__":
    main()
