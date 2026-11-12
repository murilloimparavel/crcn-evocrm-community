#!/usr/bin/env python3
"""Host-side Coolify Service adapter. Planning is read-only; production defaults off.

Run on the reviewed deployment executor, not on a PR runner. No SSH key is needed
by Actions. Secret-bearing snapshots must stay outside the repository.
"""
import argparse
import base64
import hashlib
import fcntl
import uuid
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

import yaml
from readiness import IMAGE, REQUIRED

RESOURCE = 'tzbydmxtjuilf4xq2gow9gcs'
STAGING_RESOURCE = 'w3ic7aoj22xbx6ljsb7evu6f'

def approved_resource(resource):
    if resource not in (RESOURCE, STAGING_RESOURCE):
        raise DeploymentError('Resource is not approved')

def approved_image(image, resource):
    return isinstance(image, str) and bool(IMAGE.fullmatch(image) or
        (resource == STAGING_RESOURCE and re.fullmatch(r'sha256:[0-9a-f]{64}', image)))


class DeploymentError(RuntimeError):
    pass


class ReconciliationRequired(DeploymentError):
    """An asynchronous deployment may still change running containers."""


def compose_hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def plan(current, images, resource=RESOURCE):
    """Validate all image changes before creating a candidate; preserve state."""
    approved_resource(resource)
    document = yaml.safe_load(current)
    if not isinstance(document, dict) or not isinstance(document.get('services'), dict):
        raise DeploymentError('Invalid current Compose')
    if set(images) != REQUIRED:
        raise DeploymentError('Exact production application service set required')
    for service, image in images.items():
        if service not in document['services'] or not approved_image(image, resource):
            raise DeploymentError('Missing service or unapproved image digest: ' + service)
    for service, image in images.items():
        document['services'][service]['image'] = image
    return {
        'resource': resource,
        'expected_compose_sha256': compose_hash(current),
        'previous_compose': current,
        'candidate_compose': yaml.safe_dump(document, sort_keys=False),
        'images': images,
    }


class Coolify:
    def __init__(self, url, token, enabled=False, opener=None, resource=RESOURCE, application_only=False):
        approved_resource(resource)
        self.resource = resource
        self.application_only = application_only
        self._app_paths = {}
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise DeploymentError('Coolify must use HTTPS without embedded credentials')
        if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise DeploymentError('Use the Coolify origin, without path, query or fragment')
        if not token:
            raise DeploymentError('Coolify token is required')
        self.url, self.token, self.enabled = url.rstrip('/'), token, enabled
        # Do not follow redirects with an Authorization header.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        self.opener = opener or urllib.request.build_opener(NoRedirect)

    def request(self, method, path, payload=None):
        service = '/services/' + self.resource
        allowed = {('GET', service), ('PATCH', service)}
        if self.application_only:
            allowed.add(('GET', service + '/applications'))
            allowed.update(('POST', path) for path in self._app_paths.values())
        else:
            allowed.add(('POST', '/deploy'))
        if (method, path) not in allowed:
            raise DeploymentError('Endpoint outside the approved resource contract')
        if method != 'GET' and not self.enabled:
            raise DeploymentError('Production mutations are disabled')
        if method == 'POST' and path == '/deploy' and payload != {'uuid': self.resource}:
            raise DeploymentError('Deployment outside the approved resource')
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.url + '/api/v1' + path, data=data,
            method=method, headers={'Authorization': 'Bearer ' + self.token,
                'Accept': 'application/json', 'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            # Never log response bodies, request data or tokens.
            raise DeploymentError('Coolify request failed with HTTP ' + str(error.code)) from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise DeploymentError('Coolify request failed without a verified response') from None

    def current(self):
        result = self.request('GET', '/services/' + self.resource)
        if result.get('uuid') != self.resource or not isinstance(result.get('docker_compose_raw'), str):
            raise DeploymentError('Unexpected resource or missing sensitive-read permission')
        return result['docker_compose_raw']

    def set_compose(self, raw):
        return self.request('PATCH', '/services/' + self.resource,
            {'docker_compose_raw': base64.b64encode(raw.encode()).decode(), 'instant_deploy': False})

    def discover_applications(self):
        service = '/services/' + self.resource
        response = self.request('GET', service + '/applications')
        paths = {}
        if not isinstance(response, list):
            raise DeploymentError('Unexpected Coolify application list')
        for app in response:
            name, uuid = app.get('name'), app.get('uuid')
            if name not in REQUIRED or app.get('deleted_at') or app.get('is_removed_from_compose'):
                continue
            if name in paths or not isinstance(uuid, str) or not re.fullmatch(r'[a-z0-9-]{8,64}', uuid):
                raise DeploymentError('Unexpected or duplicate application identity')
            paths[name] = service + '/applications/' + uuid + '/start'
        if set(paths) != REQUIRED:
            raise DeploymentError('Missing required Coolify applications')
        self._app_paths = paths

    def start_application(self, name):
        if not self.application_only or name not in self._app_paths:
            raise DeploymentError('Application outside the approved target set')
        result = self.request('POST', self._app_paths[name], {})
        if not isinstance(result, dict) or result.get('message') != 'Service application deploy request queued.':
            raise DeploymentError('Coolify did not confirm the application was queued')

    def deploy(self):
        # In Coolify 4.5.3, Service deploys do NOT return an application
        # deployment UUID. Completion must be verified against actual containers.
        return self.request('POST', '/deploy', {'uuid': self.resource})


class DockerHealth:
    def __init__(self, timeout=600, stable_rounds=3, interval=10, resource=RESOURCE):
        approved_resource(resource)
        self.resource = resource
        self.timeout, self.stable_rounds, self.interval = timeout, stable_rounds, interval

    def wait(self, images):
        deadline, stable = time.monotonic() + self.timeout, 0
        while time.monotonic() < deadline:
            passed = True
            for service, image in images.items():
                result = subprocess.run(['docker', 'inspect', service + '-' + self.resource],
                    capture_output=True, text=True, timeout=15)
                try:
                    container = json.loads(result.stdout)[0]
                    passed &= (result.returncode == 0 and container['Config']['Image'] == image
                        and container['State']['Running'] is True
                        and container['State'].get('Health', {}).get('Status') == 'healthy')
                except (ValueError, IndexError, KeyError):
                    passed = False
            stable = stable + 1 if passed else 0
            if stable >= self.stable_rounds:
                return
            time.sleep(self.interval)
        raise DeploymentError('Requested images did not reach stable healthy runtime state')


APPLICATION_ORDER = ('evocrm_auth', 'evocrm_crm', 'evocrm_processor', 'evocrm_core',
                     'evocrm_bot_runtime', 'evocrm_auth_sidekiq', 'evocrm_crm_sidekiq',
                     'evocrm_frontend', 'evocrm_gateway')


def apply_images(client, images, changed, health):
    if getattr(client, 'application_only', False) is True:
        client.discover_applications()
        for name in APPLICATION_ORDER:
            if name in changed:
                try:
                    client.start_application(name)
                    health.wait({name: images[name]})
                except Exception:
                    raise ReconciliationRequired(
                        f'Coolify start could not be confirmed for {name}'
                    ) from None
    else:
        client.deploy()
    health.wait(images)


def _promote(client, release, health, smoke, state_dir):
    """Called only after external lock/backup/migration/evidence/approval gates.

    A failure in PATCH/deploy is ambiguous: it may have reached Coolify before
    the response was lost. Attempt application rollback after any attempted write.
    Never roll back the database. Return failure even if application recovery passes.
    """
    if not client.enabled:
        raise DeploymentError('Production mutations are disabled')
    if release['resource'] != getattr(client, 'resource', RESOURCE):
        raise DeploymentError('Release/client resource mismatch')
    previous = client.current()
    if compose_hash(previous) != release['expected_compose_sha256']:
        raise DeploymentError('Coolify configuration drifted after the approved snapshot')
    # Save the recovery material before any attempted mutation. These files
    # contain environment data and must never become CI artifacts or git files.
    recovery = state_dir / ('recovery-' + uuid.uuid4().hex + '.json')
    descriptor = os.open(recovery, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump({'resource': release['resource'], 'previous_compose': previous,
                   'candidate_compose': release['candidate_compose']}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    previous_doc = yaml.safe_load(previous)
    candidate_doc = yaml.safe_load(release['candidate_compose'])
    previous_images = {s: previous_doc['services'][s]['image'] for s in REQUIRED}
    if not isinstance(candidate_doc, dict) or not isinstance(candidate_doc.get('services'), dict):
        raise DeploymentError('Invalid candidate Compose')
    if set(candidate_doc['services']) != set(previous_doc['services']):
        raise DeploymentError('Candidate changes the service set')
    if {k: v for k, v in candidate_doc.items() if k != 'services'} != {
        k: v for k, v in previous_doc.items() if k != 'services'
    }:
        raise DeploymentError('Candidate changes shared Compose configuration')
    if any(candidate_doc['services'][s] != previous_doc['services'][s]
           for s in set(previous_doc['services']) - REQUIRED):
        raise DeploymentError('Candidate changes a non-application service')
    if any(candidate_doc['services'][s].get('image') != release['images'][s] for s in REQUIRED):
        raise DeploymentError('Candidate images differ from the release manifest')
    changed = {name for name in REQUIRED
               if previous_doc['services'][name] != candidate_doc['services'][name]}
    if not changed:
        health.wait(previous_images)
        smoke()
        return
    try:
        client.set_compose(release['candidate_compose'])
        apply_images(client, release['images'], changed, health)
        smoke()
    except Exception as error:
        # Preserve concurrent operator edits rather than overwriting unknown state.
        try:
            observed = client.current()
            if compose_hash(observed) not in (compose_hash(previous), compose_hash(release['candidate_compose'])):
                raise DeploymentError('Rollback blocked by concurrent Coolify configuration changes')
            client.set_compose(previous)
            # An accepted start without a confirmed outcome can still race a
            # rollback. Restore desired configuration and leave jobs for reconciliation.
            if isinstance(error, ReconciliationRequired):
                raise error
            apply_images(client, previous_images, changed, health)
        except Exception:
            raise ReconciliationRequired('Promotion failed; application rollback needs operator attention') from None
        raise DeploymentError('Promotion failed; previous application images restored and verified') from None



def promote(client, release, health, smoke, state_dir):
    """Serialize the host executor and retain a private recovery snapshot."""
    if not client.enabled:
        raise DeploymentError('Production mutations are disabled')
    state_dir = Path(state_dir).resolve()
    repo = Path(__file__).resolve().parents[2]
    if (repo / '.git').exists() and state_dir.is_relative_to(repo):
        raise DeploymentError('Recovery snapshots must remain outside checkout')
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if state_dir.stat().st_mode & 0o077:
        raise DeploymentError('Recovery directory must have private permissions')
    descriptor = os.open(state_dir / 'deployment.lock', os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeploymentError('Another deployment owns the resource lock') from None
        return _promote(client, release, health, smoke, state_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('compose', type=Path, help='private source Compose outside checkout')
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    if (repo / '.git').exists() and args.compose.resolve().is_relative_to(repo):
        parser.error('Secret-bearing Compose must remain outside checkout')
    release = plan(args.compose.read_text(), json.loads(args.manifest.read_text())['images'])
    # CLI intentionally exposes only planning. Production orchestration/activation
    # requires reviewed staging evidence and the external lock/migration executor.
    print(json.dumps({'resource': RESOURCE, 'compose_sha256': release['expected_compose_sha256'],
        'services': sorted(release['images']), 'mutations': False}, indent=2))


if __name__ == '__main__':
    main()
