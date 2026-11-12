#!/usr/bin/env python3
"""Test synthetic transfers on an isolated disposable standalone Redis."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

LUA = Path(__file__).with_name('atomic-transfer.lua')


def main():
    with tempfile.TemporaryDirectory(prefix='queue-transfer-') as temp:
        sock = os.path.join(temp, 'redis.sock')
        server = subprocess.Popen(['redis-server', '--port', '0', '--unixsocket', sock,
                                   '--save', '', '--appendonly', 'no'], stdout=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if os.path.exists(sock): break
                time.sleep(.02)
            def cli(*args):
                return subprocess.check_output(['redis-cli', '-s', sock, '--raw', *map(str, args)], text=True).strip()
            def db(n, *args): return cli('-n', n, *args)
            def move(src, dst, kind, key, job, failure='none'):
                return cli('--eval', LUA, ',', src, dst, kind, key, job, failure)
            for kind, key in [('list', 'queue:licensing'), ('zset', 'schedule'), ('zset', 'retry')]:
                job = json.dumps({'class': 'ActiveJob::QueueAdapters::SidekiqAdapter::JobWrapper',
                                  'wrapped': 'Licensing::HeartbeatJob', 'jid': key,
                                  'args': [{'job_class': 'Licensing::HeartbeatJob',
                                            'job_id': 'synthetic-' + key, 'arguments': [None]}]})
                if kind == 'list': db(1, 'LPUSH', key, job)
                else: db(1, 'ZADD', key, 4102444800, job)
                assert 'injected failure' in move(1, 3, kind, key, job, 'fail')
                assert db(3, 'TYPE', key) == 'none'
                assert 'injected failure after copy' in move(1, 3, kind, key, job, 'after_copy')
                assert db(1, 'TYPE', key) == kind and db(3, 'TYPE', key) == kind
                # Reconcile by removing only the duplicate destination copy.
                if kind == 'list': db(3, 'LREM', key, 1, job)
                else: db(3, 'ZREM', key, job)
                assert move(1, 3, kind, key, job) == 'moved'
                assert 'source' in move(1, 3, kind, key, job)
                if kind == 'zset': assert db(3, 'ZSCORE', key, job) == '4102444800'
                assert move(3, 1, kind, key, job) == 'moved'
                if kind == 'list': assert db(1, 'LRANGE', key, 0, -1) == job
                else: assert db(1, 'ZSCORE', key, job) == '4102444800'
                assert db(3, 'TYPE', key) == 'none'
            job = json.dumps({'jid': 'duplicate'})
            db(1, 'LPUSH', 'queue:default', job)
            db(3, 'LPUSH', 'queue:default', job)
            assert 'already at target' in move(1, 3, 'list', 'queue:default', job)
            assert db(1, 'LLEN', 'queue:default') == '1'
            assert db(3, 'LLEN', 'queue:default') == '1'
            db(1, 'ZADD', 'retry-conflict', 100, job)
            db(3, 'SET', 'retry-conflict', 'unexpected-type')
            assert 'target type mismatch' in move(1, 3, 'zset', 'retry-conflict', job)
            assert db(1, 'ZSCORE', 'retry-conflict', job) == '100'
            # Naive reverse transfer changes relative order in a mixed queue.
            db(1, 'RPUSH', 'queue:mixed', 'new-crm', 'auth-job', 'old-crm')
            assert move(1, 3, 'list', 'queue:mixed', 'auth-job') == 'moved'
            assert move(3, 1, 'list', 'queue:mixed', 'auth-job') == 'moved'
            assert db(1, 'LRANGE', 'queue:mixed', 0, -1).splitlines() == ['auth-job', 'new-crm', 'old-crm']
            print('PASS: synthetic queue, schedule and retry transfer; pre-write failure, repeat and rollback')
        finally:
            server.terminate(); server.wait(timeout=5)


if __name__ == '__main__': main()
