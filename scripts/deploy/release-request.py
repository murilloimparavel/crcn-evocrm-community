#!/usr/bin/env python3
"""Aggregate scanned digest artifacts from this workflow run only."""
import json
import os
from pathlib import Path
import re
import sys
from readiness import IMAGE

MAP = {'auth': ['evocrm_auth', 'evocrm_auth_sidekiq'], 'crm': ['evocrm_crm', 'evocrm_crm_sidekiq'],
       'core': ['evocrm_core'], 'processor': ['evocrm_processor'], 'runtime': ['evocrm_bot_runtime'],
       'frontend': ['evocrm_frontend'], 'gateway': ['evocrm_gateway']}


def build(folder, sha):
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('Full release SHA required')
    components = {}
    files = list(Path(folder).glob('*.json'))
    if len(files) != len(MAP):
        raise ValueError('Exact seven image artifacts required')
    for file in files:
        value = json.loads(file.read_text())
        if not isinstance(value, dict) or len(value) != 1:
            raise ValueError('Invalid image artifact')
        name, image = next(iter(value.items()))
        if name not in MAP or name in components or not isinstance(image, str) or not IMAGE.fullmatch(image):
            raise ValueError('Unexpected/duplicate image component')
        if not image.startswith('ghcr.io/murilloimparavel/crcn-release-' + name + '@'):
            raise ValueError('Image repository does not match component')
        components[name] = image
    return {'schema_version': 1, 'release_sha': sha,
            'images': {service: components[name] for name, services in MAP.items() for service in services}}


if __name__ == '__main__':
    request = build(sys.argv[1], os.environ['RELEASE_SHA'])
    Path(sys.argv[2]).write_text(json.dumps(request))
