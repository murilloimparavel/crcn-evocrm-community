#!/usr/bin/env python3
"""Runtime-only Coolify promotion primitives; callers must keep ingress paused.

The whole existing Compose is checked for drift and restored on failure. Other
services are neither rewritten semantically nor restarted. The caller owns the
lock, backup, queue hold and worker drain; the guard must verify them.
"""
import hashlib
import json
import os
from pathlib import Path
import uuid
import yaml

SERVICE = 'evocrm_bot_runtime'


def fingerprint(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def plan(adapter, raw, candidate, resource):
    if not adapter.approved_image(candidate, resource):
        raise ValueError('Candidate must be an approved immutable image')
    doc = yaml.safe_load(raw)
    services = doc.get('services', {})
    if not adapter.REQUIRED.issubset(services):
        raise ValueError('Incomplete application set')
    old = services[SERVICE]
    if not adapter.approved_image(old.get('image'), resource) or not old.get('healthcheck'):
        raise ValueError('Runtime rollback image or healthcheck is not verified')
    previous = old['image']
    if previous == candidate:
        raise ValueError('Candidate is already configured')
    old['image'] = candidate
    candidate_raw = yaml.safe_dump(doc, sort_keys=False)
    expected = yaml.safe_load(raw)
    expected['services'][SERVICE]['image'] = candidate
    if yaml.safe_load(candidate_raw) != expected:
        raise ValueError('Unexpected configuration change')
    return {'previous': raw, 'candidate': candidate_raw, 'old_image': previous,
            'new_image': candidate, 'resource': resource}


def promote(client, release, health, guard, state_dir, smoke):
    if not client.enabled or client.resource != release['resource']:
        raise ValueError('Invalid deployment client')
    guard()
    if fingerprint(client.current()) != fingerprint(release['previous']):
        raise RuntimeError('Coolify configuration drifted')
    state_dir = Path(state_dir)
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = state_dir / ('runtime-recovery-' + uuid.uuid4().hex + '.json')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(release, output)
        output.flush()
        os.fsync(output.fileno())
    attempted_start = False
    settled = False
    try:
        guard()
        client.set_compose(release['candidate'])
        client.discover_applications()
        attempted_start = True
        client.start_application(SERVICE)
        health.wait({SERVICE: release['new_image']})
        settled = True
        guard()
        smoke()
    except Exception as failure:
        observed = client.current()
        if fingerprint(observed) not in (fingerprint(release['previous']), fingerprint(release['candidate'])):
            raise RuntimeError('Configuration drift; keep ingress paused and reconcile') from failure
        guard()
        client.set_compose(release['previous'])
        if attempted_start and not settled:
            raise RuntimeError('Start outcome uncertain; keep ingress paused and reconcile Coolify job') from failure
        if settled:
            guard()
            client.discover_applications()
            client.start_application(SERVICE)
            health.wait({SERVICE: release['old_image']})
            guard()
        raise RuntimeError('Promotion failed; previous runtime configuration restored') from failure
    return path
