#!/usr/bin/env python3
"""Host-only QA of the synthetic staging stack. Always stop it; never remove data."""
import argparse
import tempfile
from readiness import IMAGE, REQUIRED
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
import yaml

RESOURCE = 'w3ic7aoj22xbx6ljsb7evu6f'
ROOT = Path('/data/evocrm-staging')
COMPOSE = Path('/data/coolify/services') / RESOURCE / 'docker-compose.yml'


def validate(document, network):
    if network.get('Internal') is not True or network.get('Name') != RESOURCE:
        raise ValueError('Staging requires its own internal network')
    for name, service in document['services'].items():
        if any(service.get(key) for key in ('network_mode', 'privileged', 'devices', 'volumes_from', 'cap_add', 'pid', 'ipc', 'uts', 'userns_mode')):
            raise ValueError('Unsafe staging service: ' + name)
        if service.get('container_name', name + '-' + RESOURCE) != name + '-' + RESOURCE:
            raise ValueError('Container name outside staging: ' + name)
        networks = service.get('networks', {})
        if set(networks) != {RESOURCE}:
            raise ValueError('Unexpected staging network: ' + name)
        for port in service.get('ports', []):
            if isinstance(port, str):
                allowed = port.startswith('127.0.0.1:')
            else:
                allowed = port.get('host_ip') == '127.0.0.1'
            if not allowed:
                raise ValueError('Public staging port: ' + name)
        for mount in service.get('volumes', []):
            source = mount.split(':', 1)[0] if isinstance(mount, str) else mount.get('source', '')
            if source.startswith('/'):
                if not Path(source).resolve().is_relative_to(ROOT):
                    raise ValueError('Non-staging bind mount: ' + name)
            else:
                definition = document.get('volumes', {}).get(source, {}) or {}
                if definition.get('driver_opts'):
                    raise ValueError('Staging volume must not map a host device: ' + name)
                if isinstance(mount, dict) and mount.get('type') == 'bind':
                    raise ValueError('Relative bind mounts are not allowed')
                actual = definition.get('name', source)
                if not actual.startswith(RESOURCE + '_'):
                    raise ValueError('Non-staging volume: ' + name)
        if not service.get('healthcheck'):
            raise ValueError('Missing staging healthcheck: ' + name)


def staging_network():
    # Coolify may remove an unused network while the ephemeral stack is stopped.
    with (ROOT / 'network.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            raw = subprocess.check_output(['docker', 'network', 'inspect', RESOURCE], stderr=subprocess.PIPE)
        except subprocess.CalledProcessError:
            subprocess.run(['docker', 'network', 'create', '--internal', '--attachable', RESOURCE],
                           check=True, capture_output=True, timeout=30)
            raw = subprocess.check_output(['docker', 'network', 'inspect', RESOURCE])
        network = json.loads(raw)[0]
        if network.get('Name') != RESOURCE or network.get('Internal') is not True:
            raise ValueError('Staging network must remain internal')
        return network


def private_replace(path, content):
    fd, temporary = tempfile.mkstemp(prefix='.staging-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def command(args, log, timeout=600):
    result = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Staging operation failed; inspect private host log')


def stop_stack(log):
    # Include one-off migration containers: compose stop alone can leave those
    # running after the client or controller is killed.
    query = ['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=' + RESOURCE]
    identifiers = subprocess.check_output(query, timeout=15).decode().split()
    import re
    if any(not re.fullmatch('[0-9a-f]{12,64}', value) for value in identifiers):
        raise RuntimeError('Unexpected staging container identifier')
    if identifiers:
        command(['docker', 'stop', '--time', '30', *identifiers], log, 120)
    if subprocess.check_output(query, timeout=15).strip():
        raise RuntimeError('Staging containers are still running')


def api_routes(compose, destination):
    ruby = 'puts JSON.generate(Rails.application.routes.routes.map { |r| "#{r.verb} #{r.path.spec}" }.select { |r| r.include?("/api/v1/") }.sort)'
    with destination.open('w') as log:
        command(compose + ['run', '-T', '--rm', '--no-deps', '--entrypoint', 'bundle',
                           'evocrm_crm', 'exec', 'rails', 'runner', ruby], log, 300)
    for line in reversed(destination.read_text().splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, list) and value and all(isinstance(v, str) and '/api/v1/' in v for v in value):
            return set(value)
    raise RuntimeError('Cannot establish CRM API contract')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stop-only', action='store_true')
    parser.add_argument('--allow-local-candidate', action='store_true', help='staging-only local immutable image IDs')
    parser.add_argument('--candidate', type=Path, help='private release manifest with exact image digests')
    args = parser.parse_args()
    os.umask(0o077)
    metadata = json.loads((ROOT / 'metadata.json').read_text())
    if metadata['service_uuid'] != RESOURCE:
        raise ValueError('Unexpected staging resource')
    if args.stop_only:
        with (ROOT / 'cycle.private.log').open('a') as log:
            stop_stack(log)
        return
    network = staging_network()
    original = COMPOSE.read_text()
    document = yaml.safe_load(original)
    validate(document, network)
    candidate = original
    if args.candidate:
        images = json.loads(args.candidate.read_text())['images']
        def approved_image(value):
            if not isinstance(value, str):
                return False
            if IMAGE.fullmatch(value):
                return True
            if args.allow_local_candidate:
                import re
                return bool(re.fullmatch('sha256:[0-9a-f]{64}', value))
            return False
        if set(images) != REQUIRED or any(not approved_image(v) for v in images.values()):
            raise ValueError('Exact approved image digest set required')
        for web, worker in [('evocrm_auth', 'evocrm_auth_sidekiq'), ('evocrm_crm', 'evocrm_crm_sidekiq')]:
            if images[web] != images[worker]:
                raise ValueError('Web/worker images must match')
        for name, image in images.items():
            document['services'][name]['image'] = image
        candidate = yaml.safe_dump(document, sort_keys=False)
    compose = ['docker', 'compose', '--project-name', RESOURCE, '--env-file', str(COMPOSE.parent / '.env'), '-f', str(COMPOSE)]
    with (ROOT / 'cycle.lock').open('a') as lock:
        # Emergency stop does not wait for a stuck cycle's lock.
        if not args.stop_only:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (ROOT / 'cycle.private.log').open('a') as log:
            if args.stop_only:
                stop_stack(log)
                return
            receipt = {'resource': RESOURCE, 'started_at': time.time(), 'qa_passed': False, 'stopped': False, 'rollback_rehearsed': False, 'contract_qa_passed': False}
            try:
                stop_stack(log)
                baseline_routes = None
                if args.candidate:
                    command(compose + ['up', '-d', '--force-recreate', '--wait', '--wait-timeout', '120', 'postgres', 'redis'], log, 180)
                    baseline_routes = api_routes(compose, ROOT / 'baseline-routes.private.log')
                if candidate != original:
                    private_replace(COMPOSE, candidate)
                    COMPOSE.chmod(0o600)
                command(compose + ['up', '-d', '--force-recreate', '--wait', '--wait-timeout', '120', 'postgres', 'redis'], log, 180)
                command(['python3', str(ROOT / 'migrate.py')], log, 1200)
                command(compose + ['up', '-d', '--force-recreate', '--wait', '--wait-timeout', '300'], log, 360)
                # Require a stability window rather than one healthy sample.
                for _ in range(3):
                    for name in yaml.safe_load(COMPOSE.read_text())['services']:
                        details = json.loads(subprocess.check_output(['docker', 'inspect', name + '-' + RESOURCE]))[0]
                        expected_image = yaml.safe_load(COMPOSE.read_text())['services'][name]['image']
                        if details['Config']['Image'] != expected_image:
                            raise RuntimeError('Staging image mismatch: ' + name)
                        if not details['State']['Running'] or details['State'].get('Health', {}).get('Status') != 'healthy':
                            raise RuntimeError('Staging health failed: ' + name)
                    time.sleep(5)
                if args.candidate:
                    command(['python3', str(ROOT / 'run-runtime-probe.py')], log, 90)
                    new_routes = api_routes(compose, ROOT / 'candidate-routes.private.log')
                    removed = sorted(baseline_routes - new_routes)
                    (ROOT / 'route-contract-result.json').write_text(json.dumps({'removed': removed, 'baseline_count': len(baseline_routes), 'candidate_count': len(new_routes)}))
                    if removed:
                        raise RuntimeError('Candidate removes CRM API routes: ' + str(len(removed)))
                    receipt['contract_qa_passed'] = True
                    stop_stack(log)
                    if COMPOSE.read_text() != candidate:
                        raise RuntimeError('Concurrent staging configuration change')
                    private_replace(COMPOSE, original)
                    command(compose + ['up', '-d', '--wait', '--wait-timeout', '300'], log, 360)
                    for _ in range(3):
                        for name, service in yaml.safe_load(original)['services'].items():
                            details = json.loads(subprocess.check_output(['docker', 'inspect', name + '-' + RESOURCE]))[0]
                            if details['Config']['Image'] != service['image'] or not details['State']['Running'] or details['State'].get('Health', {}).get('Status') != 'healthy':
                                raise RuntimeError('Previous staging version not healthy: ' + name)
                        time.sleep(5)
                    receipt['rollback_rehearsed'] = True
                receipt['qa_passed'] = True
            finally:
                try:
                    stop_stack(log)
                    receipt['stopped'] = True
                finally:
                    if candidate != original and COMPOSE.read_text() == candidate:
                        private_replace(COMPOSE, original)
                    receipt['finished_at'] = time.time()
                    (ROOT / 'cycle-result.json').write_text(json.dumps(receipt, indent=2))
                    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    main()
