#!/usr/bin/env python3
"""Prepare promotion/rollback Compose locally; never calls Coolify or Docker.

Input/output may contain secrets: use private paths outside the checkout.
Only image references are changed; volumes/environment/networks are preserved.
"""
import argparse
import json
import os
from pathlib import Path
import yaml
from readiness import IMAGE, REQUIRED


def render(compose, images):
    if set(images) != REQUIRED:
        raise ValueError('Exact production application service set required')
    for service, image in images.items():
        if not IMAGE.fullmatch(image):
            raise ValueError(f'Digest required for {service}')
        if service not in compose['services']:
            raise ValueError(f'Missing service: {service}')
    for service, image in images.items():
        compose['services'][service]['image'] = image
    return compose


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('compose', type=Path)
    p.add_argument('manifest', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--rollback', action='store_true')
    a = p.parse_args()
    repo = Path(__file__).resolve().parents[2]
    for path in (a.compose, a.output):
        if path.resolve().is_relative_to(repo):
            p.error('Secret-bearing Compose must remain outside the checkout')
    manifest = json.loads(a.manifest.read_text())
    document = render(yaml.safe_load(a.compose.read_text()), manifest['previous_images' if a.rollback else 'images'])
    fd = os.open(a.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        yaml.safe_dump(document, f, sort_keys=False)
    print('Private candidate created; no deployment performed.')

if __name__ == '__main__':
    main()
