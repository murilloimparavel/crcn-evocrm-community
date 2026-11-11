#!/usr/bin/env python3
"""Pause and promote one runtime with its durable queue held; never replay.

This leaves ingress paused and the queue held for explicit reconciliation. Use
only on the fixed CRCN resources, under their existing deployment lock. Failure
also leaves ingress paused for an operator to inspect.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

ROOT = Path('/data/evocrm-staging')
PRODUCTION = 'tzbydmxtjuilf4xq2gow9gcs'
STAGING = 'w3ic7aoj22xbx6ljsb7evu6f'
CANDIDATE = 'ghcr.io/murilloimparavel/evo-bot-runtime@sha256:a8d915c85af1e1d3d8d1eea6d0cc276e45173633ede524fc65efbd3e1a8e0173'
STAGE_IMAGE = 'sha256:a8d915c85af1e1d3d8d1eea6d0cc276e45173633ede524fc65efbd3e1a8e0173'
EXPECTED_MODULE = '6326eb52fe5e8ce0075af1a2e0236eab1ee1b5f7b7d11a15e4b08e33fd5647e1'
EXPECTED_LUA = '26295603b37c4b319933ab170d5adffd691d7d89a922daed526d893f80d3f79c'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verified(path, digest):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError('reviewed deployment script hash mismatch')
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resource', choices=['staging', 'production'], required=True)
    parser.add_argument('--simulate-failure', action='store_true')
    args = parser.parse_args()
    if args.resource == 'production' and args.simulate_failure:
        raise ValueError('failure simulation is staging only')
    os.umask(0o077)
    resource = PRODUCTION if args.resource == 'production' else STAGING
    image = CANDIDATE if resource == PRODUCTION else STAGE_IMAGE
    token_path = Path('/data/evocrm-deploy-executor/coolify-token.private') if resource == PRODUCTION else ROOT / 'coolify-token.private'
    work = Path('/data/evocrm-deploy-executor') if resource == PRODUCTION else ROOT / 'runtime-only-validation'
    lock_path = work / 'deployment.lock'
    release_id = uuid.uuid4().hex
    held = 'bot_runtime:rollback:held:release-' + release_id
    runtime = 'evocrm_bot_runtime-' + resource
    worker = 'evocrm_crm_sidekiq-' + resource
    redis = 'redis-' + resource
    sys_path = str(ROOT / 'adapter')
    import sys
    sys.path.insert(0, sys_path)
    adapter = load('adapter', ROOT / 'adapter/coolify-service.py')
    bootstrap = load('bootstrap', ROOT / 'bootstrap-coolify.py')
    module_path = ROOT / 'runtime-only-validation/runtime-only-promote.py'
    verified(module_path, EXPECTED_MODULE)
    promoter = load('promoter', module_path)
    lua = verified(ROOT / 'runtime-only-validation/hold-runtime-queue.lua', EXPECTED_LUA).decode()
    client = adapter.Coolify(bootstrap.API.removesuffix('/api/v1'), token_path.read_text().strip(), enabled=True, resource=resource, application_only=True)
    log_path = work / ('runtime-release-' + release_id + '.private.log')
    state_path = work / ('runtime-release-' + release_id + '.json')
    state = {'resource': args.resource, 'release_id': release_id, 'phase': 'preflight', 'held': held}

    def phase(value):
        state['phase'] = value
        temp = state_path.with_suffix('.tmp')
        temp.write_text(json.dumps(state))
        os.replace(temp, state_path)
        print(value, flush=True)

    def run(cmd, timeout=120, **kw):
        return subprocess.run(cmd, check=True, timeout=timeout, stdout=log, stderr=log, **kw)

    def out(cmd, timeout=120):
        return subprocess.check_output(cmd, text=True, stderr=log, timeout=timeout).strip()

    auth_mode = None
    def redis_cmd(*parts):
        if auth_mode is None:
            raise RuntimeError('Redis authentication not verified')
        setup = ':' if auth_mode == 'inherited' else 'export REDISCLI_AUTH="${REDIS_PASSWORD:-}"'
        cmd = ['docker', 'exec', redis, 'sh', '-c', setup + '; exec redis-cli -n 1 --raw "$@"', '--', *parts]
        return out(cmd)

    ruby_prefix = "p=Sidekiq::ProcessSet.new.find{|x|x['hostname']==Socket.gethostname}; abort 'worker missing' unless p; "
    def worker_ruby(code):
        return ['docker', 'exec', worker, 'bundle', 'exec', 'ruby', '-rsidekiq/api', '-rsocket', '-e', ruby_prefix + code]

    with lock_path.open('a') as lock, log_path.open('a') as log:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Verify authentication before stopping any service. An environment
        # variable may exist even when the running Redis does not require it.
        auth_mode = 'inherited'
        if redis_cmd('PING') != 'PONG':
            auth_mode = 'password'
            if redis_cmd('PING') != 'PONG':
                raise RuntimeError('Redis authentication could not be verified')
        release = promoter.plan(adapter, client.current(), image, resource)
        if out(['docker', 'image', 'inspect', image, '--format', '{{.Id}}']) != STAGE_IMAGE:
            raise RuntimeError('candidate image identity mismatch')
        names = out(['docker', 'ps', '--filter', 'name=evocrm_bot_runtime-' + resource, '--format', '{{.Names}}']).splitlines()
        if names != [runtime]:
            raise RuntimeError('unexpected runtime replica count')
        old_id = out(['docker', 'inspect', runtime, '--format', '{{.Image}}'])
        expected_old = out(['docker', 'image', 'inspect', release['old_image'], '--format', '{{.Id}}'])
        if old_id != expected_old:
            raise RuntimeError('active runtime differs from Coolify configuration')
        state['old_image_id'] = old_id
        phase('draining')
        run(worker_ruby("p.quiet!; deadline=Time.now+120; loop do; x=Sidekiq::ProcessSet.new.find{|q|q['hostname']==Socket.gethostname}; break if x && x['quiet'].to_s=='true' && x['busy'].to_i==0; abort 'drain timeout' if Time.now>deadline; sleep 2; end"), 150)
        run(['docker', 'stop', '-t', '30', runtime], 45)
        keys = redis_cmd('ZRANGE', 'bot_runtime:durable:ready', '0', '-1').splitlines()
        if not keys or any(not re.fullmatch(r'bot_runtime:durable:[0-9]+:[0-9]+', k) for k in keys):
            raise RuntimeError('queue empty or contains unexpected keys; ingress remains paused')
        deadline = time.monotonic() + 70
        while any(redis_cmd('EXISTS', key + ':lease') != '0' for key in keys):
            if time.monotonic() > deadline:
                raise RuntimeError('leases did not expire; ingress remains paused')
            time.sleep(2)
        if redis_cmd('ZRANGE', 'bot_runtime:durable:ready', '0', '-1').splitlines() != keys:
            raise RuntimeError('queue changed while draining; ingress remains paused')
        phase('backup')
        directory = Path('/var/backups/evocrm-redis-reconcile') if resource == PRODUCTION else work / 'backups'
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        backup = directory / (release_id + '.rdb')
        setup = ':' if auth_mode == 'inherited' else 'export REDISCLI_AUTH="${REDIS_PASSWORD:-}"'
        cmd = ['docker', 'exec', redis, 'sh', '-c', setup + '; exec redis-cli --rdb -']
        with backup.open('xb') as destination:
            subprocess.run(cmd, stdout=destination, stderr=log, timeout=600, check=True)
            destination.flush(); os.fsync(destination.fileno())
        redis_image = out(['docker', 'inspect', redis, '--format', '{{.Image}}'])
        run(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'redis-check-rdb', '--mount', f'type=bind,src={backup},dst=/snapshot.rdb,readonly', redis_image, '/snapshot.rdb'], 180)
        restore = 'codex-runtime-restore-' + release_id[:12]
        try:
            run(['docker', 'run', '-d', '--network', 'none', '--user', '0:0', '--entrypoint', 'redis-server', '--name', restore, '--mount', f'type=bind,src={backup},dst=/data/dump.rdb,readonly', redis_image, '--dir', '/data', '--dbfilename', 'dump.rdb', '--save', '', '--appendonly', 'no'], 30)
            for _ in range(30):
                try:
                    if out(['docker', 'exec', restore, 'redis-cli', 'ping'], 3) == 'PONG': break
                except subprocess.SubprocessError: pass
                time.sleep(1)
            else: raise RuntimeError('isolated backup restore did not start')
            restored = out(['docker', 'exec', restore, 'redis-cli', '-n', '1', '--raw', 'ZRANGE', 'bot_runtime:durable:ready', '0', '-1']).splitlines()
            if restored != keys:
                raise RuntimeError('restored queue differs from live paused queue')
        finally:
            subprocess.run(['docker', 'rm', '-f', restore], stdout=log, stderr=log, timeout=30, check=False)
        state['backup'] = str(backup); state['turn_count'] = len(keys)
        phase('holding')
        if redis_cmd('EVAL', lua, '2', 'bot_runtime:durable:ready', held, *keys) != str(len(keys)):
            raise RuntimeError('queue hold failed; ingress remains paused')

        def guard():
            quiet = out(worker_ruby("puts(p['quiet'].to_s); abort 'worker busy' unless p['busy'].to_i==0"), 45).splitlines()[-1]
            if quiet != 'true': raise RuntimeError('CRM worker is not drained')
            if redis_cmd('EXISTS', 'bot_runtime:durable:ready') != '0': raise RuntimeError('new ready queue appeared')
            if redis_cmd('ZRANGE', held, '0', '-1').splitlines() != keys: raise RuntimeError('held queue changed')
            if any(redis_cmd('EXISTS', key + ':lease') != '0' for key in keys): raise RuntimeError('runtime lease appeared')

        guard()
        phase('promoting')
        health = adapter.DockerHealth(timeout=360, stable_rounds=2, interval=5, resource=resource)
        def smoke():
            if args.simulate_failure: raise RuntimeError('intentional staging failure')
        try:
            promoter.promote(client, release, health, guard, work / 'runtime-recovery', smoke)
        except RuntimeError as error:
            if args.simulate_failure and str(error) == 'Promotion failed; previous runtime configuration restored':
                state['rollback_tested'] = True
                guard(); phase('rollback_tested'); return
            phase('attention_required'); raise
        guard()
        phase('candidate_healthy_queue_held_ingress_paused')

if __name__ == '__main__':
    main()
