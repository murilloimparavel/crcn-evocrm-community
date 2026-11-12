#!/usr/bin/env python3
"""Rehearse exact queue ordering and fail-closed recovery on disposable Redis."""
import os
from pathlib import Path
import subprocess
import tempfile
import time

SCRIPT = Path(__file__).with_name('ordered-rollback.lua')


def main():
    with tempfile.TemporaryDirectory(prefix='queue-order-') as temp:
        sock = os.path.join(temp, 'redis.sock')
        server = subprocess.Popen(['redis-server', '--port', '0', '--unixsocket', sock, '--save', '', '--appendonly', 'no'], stdout=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if os.path.exists(sock): break
                time.sleep(.02)
            def cli(*args):
                return subprocess.check_output(['redis-cli', '-s', sock, '--raw', *map(str,args)], text=True).strip()
            def db(n,*args): return cli('-n',n,*args)
            def run(mode, fail='none'): return cli('--eval',SCRIPT,',',mode,1,3,'queue:default','qa:journal','auth',fail)
            for failure in ('none','after_journal','after_copy'):
                db(1,'RPUSH','queue:default','new-crm','auth','old-crm')
                result=run('move',failure)
                assert result == 'moved' if failure == 'none' else 'injected' in result
                assert run('rollback') == 'restored'
                assert db(1,'LRANGE','queue:default',0,-1).splitlines() == ['new-crm','auth','old-crm']
                assert db(3,'TYPE','queue:default') == 'none'
                db(1,'DEL','queue:default')
            db(1,'RPUSH','queue:default','new-crm','auth','old-crm')
            assert run('move') == 'moved'
            db(1,'LPUSH','queue:default','concurrent')
            assert 'queue drift' in run('rollback')
            assert db(3,'LRANGE','queue:default',0,-1) == 'auth'
            assert db(1,'EXISTS','qa:journal') == '1'
            print('PASS: exact synthetic ordering restored, duplicate reconciled, concurrent changes block rollback')
        finally:
            server.terminate(); server.wait(timeout=5)


if __name__ == '__main__': main()
