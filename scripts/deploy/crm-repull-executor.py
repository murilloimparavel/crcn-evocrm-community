#!/usr/bin/env python3
"""Restricted host executor for an approved CRM-only repull.

Installed code and hooks must be root-owned and reviewed. The request contains
only an approved registry digest and source SHA. Production is disabled by default.
"""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

import yaml

ROOT = Path('/data/evocrm-deploy-executor')
RESOURCE = 'tzbydmxtjuilf4xq2gow9gcs'
DIRECTORY = Path('/data/coolify/services') / RESOURCE
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('repull_plan', HERE / 'crm-repull-plan.py')
plan_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan_module)
spec = importlib.util.spec_from_file_location('release_executor', HERE / 'release-executor.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
IMAGE = plan_module.IMAGE
SERVICES = plan_module.SERVICES
SHA = re.compile(r'[a-f0-9]{40}\Z')


class ReconciliationRequired(RuntimeError):
    pass


def run(args, timeout=120, output=False):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True)
    return result.stdout if output else None


def inspect(name):
    data = json.loads(run(['docker', 'inspect', name + '-' + RESOURCE], output=True))[0]
    return {'image_id': data['Image'], 'healthy': data['State'].get('Health', {}).get('Status') == 'healthy',
            'running': data['State']['Running'], 'container_id': data['Id'],
            'ref': data['Config']['Image']}


def digest_for(tag):
    # RepoDigests returned after pull represent the registry manifest digest.
    result = run(['docker', 'image', 'inspect', tag, '--format', '{{json .RepoDigests}}'], output=True)
    matches = [entry.split('@', 1)[1] for entry in json.loads(result)
               if entry.startswith('ghcr.io/murilloimparavel/evo-ai-crm-community@sha256:')]
    if len(matches) != 1:
        raise ValueError('Cannot establish a unique registry digest')
    return matches[0]


def compose(args, timeout=600):
    return run(['docker', 'compose', '--project-directory', str(DIRECTORY), '--project-name', RESOURCE,
                '-f', str(DIRECTORY / 'docker-compose.yml'), *args], timeout=timeout)


def wait_healthy(image_id, prior_ids, timeout=300):
    deadline, stable = time.monotonic() + timeout, 0
    while time.monotonic() < deadline:
        states = {name: inspect(name) for name in SERVICES}
        ok = all(s['running'] and s['healthy'] and s['image_id'] == image_id and
                 s['ref'] == IMAGE and s['container_id'] != prior_ids[name]
                 for name, s in states.items())
        stable = stable + 1 if ok else 0
        if stable >= 3:
            return states
        time.sleep(10)
    raise RuntimeError('CRM did not reach stable health')


def write_state(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.crm-repull-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_request(data):
    if not isinstance(data, dict) or set(data) != {'schema_version', 'source_sha', 'expected_digest'}:
        raise ValueError('Unexpected request')
    if data['schema_version'] != 1 or not isinstance(data['source_sha'], str) or not SHA.fullmatch(data['source_sha']):
        raise ValueError('Full CRM source SHA required')
    if not isinstance(data['expected_digest'], str) or not plan_module.DIGEST.fullmatch(data['expected_digest']):
        raise ValueError('Full image manifest digest required')


def execute(request, config, client, folder):
    validate_request(request)
    if config.get('crm_repull_enabled') is not True or config.get('crm_repull_rehearsed') is not True:
        raise ValueError('CRM repull not enabled and rehearsed')
    state_path = folder / 'crm-repull-state.json'
    if state_path.exists() and json.loads(state_path.read_text()).get('phase') not in ('healthy', 'rolled-back'):
        raise ReconciliationRequired('Previous operation requires reconciliation')
    raw = client.current()
    states = {name: inspect(name) for name in SERVICES}
    # Pull both tags and compare the registry digest, then compare local image IDs.
    immutable = IMAGE.rsplit(':', 1)[0] + ':sha-' + request['source_sha']
    run(['docker', 'pull', immutable], timeout=600)
    run(['docker', 'pull', IMAGE], timeout=600)
    target = run(['docker', 'image', 'inspect', IMAGE, '--format', '{{.Id}}'], output=True).strip()
    pinned = run(['docker', 'image', 'inspect', immutable, '--format', '{{.Id}}'], output=True).strip()
    latest_digest = digest_for(IMAGE)
    if digest_for(immutable) != request['expected_digest'] or target != pinned:
        raise ValueError('Source tag, latest and approved digest do not match')
    candidate = plan_module.plan(raw, request['expected_digest'], latest_digest, states)
    if target == candidate['previous_image_id']:
        raise ValueError('Approved image is already running')
    with (folder / 'crm-repull.private.log').open('a') as log:
        release.run_hook(config, 'backup_command', log, request['source_sha'])
        release.run_hook(config, 'backup_verification_command', log, request['source_sha'])
        release.run_hook(config, 'crm_repull_storage_verification_command', log, request['source_sha'])
        release.run_hook(config, 'crm_repull_compatibility_command', log, request['source_sha'], request['expected_digest'])
        if hashlib.sha256(client.current().encode()).hexdigest() != candidate['compose_sha256']:
            raise ValueError('Coolify configuration changed before deployment')
        if digest_for(IMAGE) != request['expected_digest']:
            raise ValueError('Local latest changed before deployment')
        before = {name: inspect(name) for name in SERVICES}
        if any(before[name]['container_id'] != states[name]['container_id'] or
               before[name]['image_id'] != states[name]['image_id'] for name in SERVICES):
            raise ValueError('Running containers changed before deployment')
        rollback_tag = IMAGE.rsplit(':', 1)[0] + ':rollback-crm-repull-' + request['source_sha']
        run(['docker', 'tag', candidate['previous_image_id'], rollback_tag])
        state = {'phase': 'prepared', 'source_sha': request['source_sha'],
                 'expected_digest': request['expected_digest'], 'previous_image_id': candidate['previous_image_id'],
                 'target_image_id': target, 'rollback_tag': rollback_tag,
                 'compose_sha256': candidate['compose_sha256']}
        write_state(state_path, state)
        state['phase'] = 'draining'
        write_state(state_path, state)
        try:
            release.run_hook(config, 'crm_repull_drain_command', log)
        except Exception:
            state['phase'] = 'reconciliation-required'
            write_state(state_path, state)
            raise ReconciliationRequired('Worker drain outcome requires reconciliation') from None
        state['phase'] = 'deploying'
        write_state(state_path, state)
        try:
            # Synchronous Compose, no pulls or dependencies. Coolify config stays latest.
            compose(['up', '-d', '--no-deps', '--pull', 'never', '--force-recreate', *SERVICES])
            wait_healthy(target, {name: states[name]['container_id'] for name in SERVICES})
            if hashlib.sha256(client.current().encode()).hexdigest() != candidate['compose_sha256']:
                raise ReconciliationRequired('Coolify configuration drifted during deployment')
            try:
                release.run_hook(config, 'crm_repull_smoke_command', log, request['source_sha'])
            except subprocess.CalledProcessError as error:
                raise RuntimeError('Confirmed smoke check failure') from error
            release.run_hook(config, 'crm_repull_resume_command', log)
            state['phase'] = 'healthy'
            write_state(state_path, state)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, ReconciliationRequired):
            state['phase'] = 'reconciliation-required'
            write_state(state_path, state)
            raise ReconciliationRequired('Deployment outcome uncertain; do not start rollback automatically') from None
        except Exception:
            state['phase'] = 'rollback-pending'
            write_state(state_path, state)
            if hashlib.sha256(client.current().encode()).hexdigest() != candidate['compose_sha256']:
                raise ReconciliationRequired('Configuration drift; rollback requires reconciliation') from None
            current = {name: inspect(name)['container_id'] for name in SERVICES}
            # Restore the local latest alias only. The registry and Coolify stay unchanged.
            run(['docker', 'tag', candidate['previous_image_id'], IMAGE])
            try:
                compose(['up', '-d', '--no-deps', '--pull', 'never', '--force-recreate', *SERVICES])
                wait_healthy(candidate['previous_image_id'], current)
                release.run_hook(config, 'crm_repull_rollback_smoke_command', log, request['source_sha'])
            except Exception:
                state['phase'] = 'reconciliation-required'
                write_state(state_path, state)
                raise ReconciliationRequired('Rollback failed or its outcome is uncertain') from None
            try:
                release.run_hook(config, 'crm_repull_resume_command', log)
            except Exception:
                state['phase'] = 'reconciliation-required'
                write_state(state_path, state)
                raise ReconciliationRequired('Worker resume after rollback requires reconciliation') from None
            state['phase'] = 'rolled-back'
            write_state(state_path, state)
            raise RuntimeError('Deployment failed; prior CRM image restored and verified') from None


def main():
    os.umask(0o077)
    if os.geteuid() != 0:
        raise ValueError('Restricted root-owned executor required')
    config = release.read_private(ROOT / 'config.json')
    content = sys.stdin.read(4097)
    if len(content) > 4096:
        raise ValueError('Request too large')
    request = json.loads(content)
    validate_request(request)
    if config.get('crm_repull_enabled') is not True or config.get('crm_repull_rehearsed') is not True:
        raise ValueError('CRM repull not enabled and rehearsed')
    token_path = Path(config['coolify_token_file'])
    if token_path.is_symlink() or token_path.stat().st_uid != 0 or token_path.stat().st_mode & 0o077:
        raise ValueError('Coolify token must be private and root-owned')
    client = release.adapter.Coolify(config['coolify_url'], token_path.read_text().strip(), application_only=True)
    with (ROOT / 'deployment.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        execute(request, config, client, ROOT)
    print(json.dumps({'result': 'healthy', 'source_sha': request['source_sha'], 'digest': request['expected_digest']}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'result': 'failed', 'error_class': type(error).__name__}), file=sys.stderr)
        raise SystemExit(1)
