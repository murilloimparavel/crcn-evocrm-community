#!/usr/bin/env python3
"""Validate release evidence without contacting or modifying production."""
import argparse
import datetime as dt
import json
import re
from pathlib import Path

SHA = re.compile(r'[0-9a-f]{40}')
IMAGE = re.compile(r'ghcr\.io/murilloimparavel/[a-z0-9._-]+@sha256:[0-9a-f]{64}')
REQUIRED = {'evocrm_gateway', 'evocrm_auth', 'evocrm_auth_sidekiq', 'evocrm_crm',
            'evocrm_crm_sidekiq', 'evocrm_core', 'evocrm_processor',
            'evocrm_bot_runtime', 'evocrm_frontend'}
CONTROLS = ('ci', 'module_tests', 'integration_tests', 'security_scan',
            'backup_restore', 'volume_restore', 'migration_rehearsal',
            'healthchecks', 'rollback_rehearsal', 'serialized_deploy',
            'github_access_control', 'coolify_adapter')


def validate(data, expected_sha=None, now=None):
    errors = []
    now = now or dt.datetime.now(dt.timezone.utc)
    if data.get('schema_version') != 1:
        errors.append('schema_version must be 1')
    sha = data.get('release_sha', '')
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        errors.append('release_sha must be a full commit SHA')
    if expected_sha and sha != expected_sha:
        errors.append('release_sha differs from checked out commit')
    if data.get('coolify_service_uuid') != 'tzbydmxtjuilf4xq2gow9gcs':
        errors.append('unexpected Coolify resource')
    for field in ('images', 'previous_images'):
        images = data.get(field, {})
        if not isinstance(images, dict) or set(images) != REQUIRED:
            errors.append(f'{field}: exact production service set required')
            continue
        for service, image in images.items():
            if not isinstance(image, str) or not IMAGE.fullmatch(image):
                errors.append(f'{field}.{service}: personal GHCR digest required')
        for web, worker in [('evocrm_auth', 'evocrm_auth_sidekiq'), ('evocrm_crm', 'evocrm_crm_sidekiq')]:
            if images[web] != images[worker]:
                errors.append(f'{field}: web and worker images differ for {web}')
    if data.get('migration_strategy') != 'expand-contract':
        errors.append('migration strategy must preserve application rollback compatibility')
    for control in CONTROLS:
        evidence = data.get('evidence', {}).get(control, {})
        if not isinstance(evidence, dict):
            errors.append(f'{control}: missing evidence')
            continue
        if evidence.get('passed') is not True or evidence.get('release_sha') != sha:
            errors.append(f'{control}: successful evidence for this release required')
        url = evidence.get('url', '')
        if not isinstance(url, str) or not url.startswith('https://'):
            errors.append(f'{control}: HTTPS audit evidence required')
    try:
        value = data.get('backup_verified_at')
        if not isinstance(value, str):
            raise ValueError('missing timestamp')
        stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        age = (now - stamp).total_seconds()
        if age < 0 or age > 86400:
            errors.append('restored backup evidence must be less than 24 hours old')
    except (KeyError, ValueError, TypeError):
        errors.append('backup_verified_at: timezone-aware ISO timestamp required')
    if data.get('backup_offsite_verified') is not True:
        errors.append('offsite backup verification required')
    if data.get('activation_approved') is not True:
        errors.append('production activation has not been approved')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--expected-sha')
    args = parser.parse_args()
    errors = validate(json.loads(args.manifest.read_text()), args.expected_sha)
    print(json.dumps({'ready': not errors, 'blockers': errors}, indent=2))
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
