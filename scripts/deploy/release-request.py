#!/usr/bin/env python3
"""Aggregate scanned digest artifacts from this workflow run only."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from readiness import IMAGE

MAP = {'auth': ['evocrm_auth', 'evocrm_auth_sidekiq'], 'crm': ['evocrm_crm', 'evocrm_crm_sidekiq'],
       'core': ['evocrm_core'], 'processor': ['evocrm_processor'], 'runtime': ['evocrm_bot_runtime'],
       'frontend': ['evocrm_frontend'], 'gateway': ['evocrm_gateway']}
SOURCE_PATHS = {'auth': 'evo-auth-service-community', 'crm': 'evo-ai-crm-community',
                'core': 'evo-ai-core-service-community', 'processor': 'evo-ai-processor-community',
                'runtime': 'evo-bot-runtime', 'frontend': 'sofia-central-frontend'}
SOURCE_REPOSITORIES = {name: f'https://github.com/murilloimparavel/{path}'
                       for name, path in SOURCE_PATHS.items()}
SOURCE_REPOSITORIES['gateway'] = 'https://github.com/murilloimparavel/crcn-evocrm-community'
ROOT = Path(__file__).resolve().parents[2]


def pinned_source_sha(name, sha):
    if name == 'gateway':
        return sha
    path = SOURCE_PATHS[name]
    result = subprocess.run(['git', 'ls-tree', sha, '--', path], cwd=ROOT,
                            text=True, capture_output=True, check=True)
    fields = result.stdout.split()
    if len(fields) < 4 or fields[0] != '160000':
        raise ValueError(f'{name}: source path is not a pinned submodule')
    return fields[2]


def build(folder, sha):
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('Full release SHA required')
    checkout_sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                  text=True, capture_output=True, check=True).stdout.strip()
    if checkout_sha != sha:
        raise ValueError('Release SHA differs from the checked out source')
    components = {}
    files = list(Path(folder).glob('*.json'))
    if len(files) != len(MAP):
        raise ValueError('Exact seven image artifacts required')
    for file in files:
        value = json.loads(file.read_text())
        if not isinstance(value, dict) or set(value) != {
                'component', 'image', 'release_sha', 'source_sha', 'source_repository'}:
            raise ValueError('Invalid image artifact')
        name = value['component']
        image = value['image']
        if name not in MAP or name in components or not isinstance(image, str) or not IMAGE.fullmatch(image):
            raise ValueError('Unexpected/duplicate image component')
        if not image.startswith('ghcr.io/murilloimparavel/crcn-release-' + name + '@'):
            raise ValueError('Image repository does not match component')
        if value['release_sha'] != sha:
            raise ValueError(f'{name}: image artifact belongs to another release')
        source_sha = value['source_sha']
        if not isinstance(source_sha, str) or not re.fullmatch('[0-9a-f]{40}', source_sha):
            raise ValueError(f'{name}: full source revision required')
        if value['source_repository'] != SOURCE_REPOSITORIES[name]:
            raise ValueError(f'{name}: unexpected source repository')
        if source_sha != pinned_source_sha(name, sha):
            raise ValueError(f'{name}: image source differs from the pinned release input')
        components[name] = image
    return {'schema_version': 1, 'release_sha': sha,
            'images': {service: components[name] for name, services in MAP.items() for service in services}}


if __name__ == '__main__':
    request = build(sys.argv[1], os.environ['RELEASE_SHA'])
    Path(sys.argv[2]).write_text(json.dumps(request))
