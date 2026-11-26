#!/usr/bin/env python3
"""Validate a CRM repull candidate without changing Coolify or Docker."""
import hashlib
import re

import yaml

IMAGE = 'ghcr.io/murilloimparavel/evo-ai-crm-community:latest'
SERVICES = ('evocrm_crm', 'evocrm_crm_sidekiq')
DIGEST = re.compile(r'sha256:[a-f0-9]{64}\Z')


def plan(raw, expected_digest, latest_digest, running):
    if not isinstance(expected_digest, str) or not DIGEST.fullmatch(expected_digest):
        raise ValueError('A full approved manifest digest is required')
    if latest_digest != expected_digest:
        raise ValueError('latest no longer matches the approved digest')
    document = yaml.safe_load(raw)
    if not isinstance(document, dict) or not isinstance(document.get('services'), dict):
        raise ValueError('Invalid Compose')
    for name in SERVICES:
        service = document['services'].get(name)
        state = running.get(name)
        if not isinstance(service, dict) or service.get('image') != IMAGE or not service.get('healthcheck'):
            raise ValueError('CRM service must use latest and have a healthcheck')
        if not isinstance(state, dict) or state.get('healthy') is not True:
            raise ValueError('Current CRM service is not healthy')
        if not isinstance(state.get('image_id'), str) or not DIGEST.fullmatch(state['image_id']):
            raise ValueError('Current image ID is required for rollback')
    if running[SERVICES[0]]['image_id'] != running[SERVICES[1]]['image_id']:
        raise ValueError('CRM and Sidekiq use different images')
    return {'compose_sha256': hashlib.sha256(raw.encode()).hexdigest(),
            'expected_digest': expected_digest,
            'previous_image_id': running[SERVICES[0]]['image_id'],
            'services': list(SERVICES)}
