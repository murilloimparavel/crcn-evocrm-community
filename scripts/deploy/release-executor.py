#!/usr/bin/env python3
"""Restricted, host-installed release executor; never execute from an uploaded ref.

Only a digest manifest arrives from CI. Root-owned host configuration supplies
reviewed backup/drain/migration commands, credentials and the approved baseline.
"""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import yaml
from readiness import IMAGE, REQUIRED

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('coolify_service', HERE / 'coolify-service.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
ROOT = Path('/data/evocrm-deploy-executor')
STAGING = Path('/data/evocrm-staging')
COMPONENTS = {'evocrm_auth': 'auth', 'evocrm_auth_sidekiq': 'auth',
    'evocrm_crm': 'crm', 'evocrm_crm_sidekiq': 'crm', 'evocrm_core': 'core',
    'evocrm_processor': 'processor', 'evocrm_bot_runtime': 'runtime',
    'evocrm_frontend': 'frontend', 'evocrm_gateway': 'gateway'}


def read_private(path):
    details = path.stat()
    if details.st_uid != 0 or stat.S_IMODE(details.st_mode) & 0o077 or path.is_symlink():
        raise ValueError('Host deployment configuration must be private and root-owned')
    return json.loads(path.read_text())


def validate_request(data):
    if not isinstance(data, dict) or set(data) != {'schema_version', 'release_sha', 'images'}:
        raise ValueError('Unexpected release request fields')
    if data['schema_version'] != 1 or not isinstance(data['release_sha'], str) or not re.fullmatch('[0-9a-f]{40}', data['release_sha']):
        raise ValueError('Full release SHA required')
    images = data['images']
    if not isinstance(images, dict) or set(images) != REQUIRED:
        raise ValueError('Exact application service set required')
    for service, image in images.items():
        if not isinstance(image, str) or not IMAGE.fullmatch(image):
            raise ValueError('Immutable personal registry digests required')
        if not image.startswith('ghcr.io/murilloimparavel/crcn-release-' + COMPONENTS[service] + '@'):
            raise ValueError('Unexpected component image repository')
    for web, worker in [('evocrm_auth', 'evocrm_auth_sidekiq'), ('evocrm_crm', 'evocrm_crm_sidekiq')]:
        if images[web] != images[worker]:
            raise ValueError('Web/worker version mismatch')


def run_hook(config, name, log, *arguments):
    command = config.get(name)
    if not isinstance(command, list) or not command or not all(isinstance(v, str) for v in command):
        raise ValueError('Missing reviewed host hook: ' + name)
    executable = Path(command[0])
    details = executable.stat()
    if not executable.is_absolute() or details.st_uid != 0 or details.st_mode & 0o022:
        raise ValueError('Hook executable must be absolute, root-owned and not writable by others')
    subprocess.run(command + list(arguments), check=True, stdout=log, stderr=subprocess.STDOUT, timeout=1200)


def require_current_main(config, request):
    # The host verifies main independently; CI cannot choose another Git remote.
    repository = Path(config['source_repository'])
    origin = subprocess.check_output(['git', '-C', str(repository), 'remote', 'get-url', 'origin'], text=True).strip()
    if origin != 'git@github.com:murilloimparavel/crcn-evocrm-community.git':
        raise ValueError('Unexpected source repository')
    subprocess.run(['git', '-C', str(repository), 'fetch', '--quiet', 'origin', 'main'], check=True, timeout=90)
    main = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'origin/main'], text=True).strip()
    if main != request['release_sha']:
        raise ValueError('Obsolete or non-main release')


def verify_candidate(request, folder, log):
    for image in sorted(set(request['images'].values())):
        subprocess.run(['docker', 'pull', image], check=True, stdout=log, stderr=subprocess.STDOUT, timeout=600)
        revision = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{index .Config.Labels "org.opencontainers.image.revision"}}', image], text=True).strip()
        if revision != request['release_sha']:
            raise ValueError('Image revision does not match the approved main commit')
    subprocess.run(['python3', str(STAGING / 'staging-cycle.py'), '--candidate', str(folder / 'candidate-request.json')],
                   check=True, stdout=log, stderr=subprocess.STDOUT, timeout=1500)
    qa = json.loads((STAGING / 'cycle-result.json').read_text())
    if not all(qa.get(k) is True for k in ('qa_passed', 'rollback_rehearsed', 'stopped')):
        raise ValueError('Candidate migration/rollback QA did not pass')


def execute(request, config, folder):
    validate_request(request)
    if config.get('enabled') is not True or config.get('baseline_approved') is not True:
        raise ValueError('Production activation/baseline not approved')
    require_current_main(config, request)
    state = folder / 'deployment-state.json'
    if state.exists() and json.loads(state.read_text()).get('phase') not in ('healthy', 'idle'):
        raise ValueError('Previous failed/interrupted deployment requires reconciliation')
    token_path = Path(config['coolify_token_file'])
    details = token_path.stat()
    if details.st_uid != 0 or details.st_mode & 0o077:
        raise ValueError('Coolify credentials must remain private on the host')
    client = adapter.Coolify(config['coolify_url'], token_path.read_text().strip(), enabled=True, application_only=True)
    raw = client.current()
    previous = yaml.safe_load(raw)
    # Current rollback target must itself have verifiable probes and immutable
    # images. Do not replace custom production images with an unapproved baseline.
    for service in REQUIRED:
        old = previous['services'][service]
        if not IMAGE.fullmatch(old.get('image', '')) or not old.get('healthcheck'):
            raise ValueError('Production baseline requires digest/probe reconciliation: ' + service)
    release = adapter.plan(raw, request['images'])
    request_path = folder / 'candidate-request.json'
    candidate_path = folder / 'candidate-compose.private.yml'
    request_path.write_text(json.dumps(request))
    candidate_path.write_text(release['candidate_compose'])
    with (folder / 'executor.private.log').open('a') as log:
        def phase(name):
            data = {'release_sha': request['release_sha'], 'phase': name, 'at': time.time()}
            temporary = folder / 'state.partial'
            with temporary.open('w') as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, state)
        drain_attempted = False
        try:
            phase('candidate-qa')
            verify_candidate(request, folder, log)
            # A separate verifier must confirm a restorable/offsite backup. Merely
            # starting a backup upload is not evidence of completion.
            require_current_main(config, request)
            phase('backup')
            run_hook(config, 'backup_command', log, request['release_sha'])
            run_hook(config, 'backup_verification_command', log, request['release_sha'])
            phase('drain')
            drain_attempted = True
            run_hook(config, 'drain_command', log)
            phase('migrating')
            run_hook(config, 'migration_command', log, str(candidate_path))
            require_current_main(config, request)
            phase('promoting')
            health = adapter.DockerHealth()
            def smoke():
                run_hook(config, 'smoke_command', log, request['release_sha'])
            # The caller holds the adapter's deployment.lock across ALL stages.
            adapter._promote(client, release, health, smoke, folder)
            phase('healthy')
        except adapter.ReconciliationRequired:
            drain_attempted = False
            phase('reconciliation-required')
            raise
        finally:
            try:
                if drain_attempted:
                    # Resume the selected Compose, never restore the database.
                    run_hook(config, 'resume_command', log)
            finally:
                subprocess.run(['python3', str(STAGING / 'staging-cycle.py'), '--stop-only'],
                               stdout=log, stderr=subprocess.STDOUT, timeout=150, check=True)


def main():
    os.umask(0o077)
    if os.geteuid() != 0:
        raise ValueError('Use the installed restricted host executor')
    config = read_private(ROOT / 'config.json')
    data = sys.stdin.read(65537)
    if len(data) > 65536:
        raise ValueError('Release request too large')
    request = json.loads(data)
    validate_request(request)
    with (ROOT / 'deployment.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if sys.argv[1:] == ['--rehearse']:
            require_current_main(config, request)
            (ROOT / 'candidate-request.json').write_text(json.dumps(request))
            with (ROOT / 'rehearsal.private.log').open('a') as log:
                verify_candidate(request, ROOT, log)
            print(json.dumps({'release_sha': request['release_sha'], 'result': 'qa-passed-staging-stopped'}))
            return
        if len(sys.argv) != 1:
            raise ValueError('Unsupported executor operation')
        execute(request, config, ROOT)
    print(json.dumps({'release_sha': request['release_sha'], 'result': 'healthy'}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Values of configs, subprocess responses and request bodies stay private.
        print(json.dumps({'result': 'failed', 'error_class': type(error).__name__}), file=sys.stderr)
        raise SystemExit(1)
