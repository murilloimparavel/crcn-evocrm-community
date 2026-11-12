#!/usr/bin/env python3
"""Disposable, internal-only Rails/Sidekiq rehearsal using production images.

Must run on vps-caldas. It creates a fresh compose project and fresh volumes;
it never connects to or mounts the production or shared staging databases.
"""
import copy
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid
import yaml

SOURCE = Path('/data/coolify/services/w3ic7aoj22xbx6ljsb7evu6f')
KEEP = {'postgres', 'redis', 'evocrm_auth', 'evocrm_auth_sidekiq', 'evocrm_crm', 'evocrm_crm_sidekiq'}
CRM = 'ghcr.io/murilloimparavel/crcn-knowledge-crm@sha256:681278e27da672ab0dace7237c7ab7ebc79e156f77830b1fb77bd068128b4166'
AUTH = 'ghcr.io/murilloimparavel/evo-auth-knowledge-release:sha-398bdeba32ed621cb31504fd4feaba6bd0ec7acf'


def main():
    project = 'queueqa' + uuid.uuid4().hex[:12]
    envfile = SOURCE / '.env'
    source = yaml.safe_load((SOURCE / 'docker-compose.yml').read_text())
    if not KEEP.issubset(source['services']):
        raise RuntimeError('Missing staging services')
    services = {name: copy.deepcopy(source['services'][name]) for name in KEEP}
    volumes = {}
    for name, service in services.items():
        for key in ('container_name', 'ports', 'labels', 'network_mode', 'privileged', 'devices', 'cap_add'):
            service.pop(key, None)
        service['networks'] = {'isolated': {'aliases': [name]}}
        if service.get('env_file'):
            service['env_file'] = [str(envfile)]
        service['depends_on'] = {k: v for k, v in (service.get('depends_on') or {}).items() if k in KEEP}
        mounts = []
        for mount in service.get('volumes', []):
            if isinstance(mount, str):
                parts = mount.split(':')
                if len(parts) < 2 or '/' in parts[0]:
                    raise RuntimeError('Unexpected mount')
                local = 'vol' + str(len(volumes))
                if parts[0] not in volumes:
                    volumes[parts[0]] = local
                parts[0] = volumes[parts[0]]
                mounts.append(':'.join(parts))
            else:
                path = Path(mount.get('source', '')).resolve()
                if name != 'redis' or not path.is_relative_to(Path('/data/evocrm-staging')) or not mount.get('read_only'):
                    raise RuntimeError('Unsafe bind mount')
                mounts.append(mount)
        service['volumes'] = mounts
        if name.startswith('evocrm_auth'):
            service['image'] = AUTH
        if name.startswith('evocrm_crm'):
            service['image'] = CRM
        if name.startswith('evocrm_'):
            e = service['environment']
            if not isinstance(e, dict) or not re.search(r'/\d+$', e.get('REDIS_URL', '')):
                raise RuntimeError('Unexpected Redis configuration')
            e['REDIS_URL'] = re.sub(r'/\d+$', '/3' if name.startswith('evocrm_auth') else '/1', e['REDIS_URL'])
    document = {'services': services, 'volumes': {v: {} for v in volumes.values()},
                'networks': {'isolated': {'internal': True}}}
    with tempfile.TemporaryDirectory(prefix=project + '-') as temp:
        path = Path(temp) / 'compose.yml'
        path.write_text(yaml.safe_dump(document, sort_keys=False)); path.chmod(0o600)
        compose = ['docker', 'compose', '-p', project, '--env-file', str(envfile), '-f', str(path)]
        def run(*args, timeout=300):
            result = subprocess.run([*compose, *args], timeout=timeout,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            if result.returncode:
                if args[:2] == ('config', '--quiet'):
                    message = re.sub(r'(?i)(password|secret|token|redis_url)\S*', '[redacted]', result.stderr)
                    print('Compose configuration error:', message[-1000:], flush=True)
                raise RuntimeError('Failed isolated step: ' + ' '.join(args[:4]))
        try:
            run('config', '--quiet')
            run('up', '-d', '--wait', '--wait-timeout', '120', 'postgres', 'redis')
            print('Disposable PostgreSQL and Redis healthy', flush=True)
            for svc in ('evocrm_auth', 'evocrm_crm'):
                run('run', '-T', '--rm', '--no-deps', '--entrypoint', 'bundle', svc,
                    'exec', 'rails', 'db:prepare', timeout=600)
                print(svc + ' Rails database prepared', flush=True)
            gate = project + '_' + volumes[next(k for k in volumes if 'release-state' in k)]
            subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--user', '0:0',
                            '--entrypoint', 'sh', '--mount', 'type=volume,src='+gate+',dst=/release',
                            AUTH, '-ec', 'touch /release/migrations-ready; chmod 644 /release/migrations-ready'],
                           check=True, timeout=60, stdout=subprocess.DEVNULL)
            fixture_dir = Path(__file__).resolve().parent
            result = subprocess.check_output([*compose, 'run', '-T', '--rm', '--no-deps',
                '-v', str(fixture_dir) + ':/fixtures:ro', '--entrypoint', 'bundle', 'evocrm_auth',
                'exec', 'rails', 'runner', '/fixtures/rails-reconcile.rb'], text=True, timeout=180)
            if 'PASS real ActiveJob payloads:' not in result:
                raise RuntimeError('Rails reconciliation rehearsal did not complete')
            print('Real pending, scheduled and retry jobs reconciled in isolated Redis', flush=True)
            run('up', '-d', '--no-deps', 'evocrm_auth_sidekiq', 'evocrm_crm_sidekiq')
            for svc, expression in (
                ('evocrm_auth', 'j=Licensing::HeartbeatJob.perform_later(nil); puts "QA_JOB=#{j.provider_job_id} #{j.job_id}"'),
                ('evocrm_crm', 'j=Webhooks::EvolutionHubEventsJob.perform_later("{}", nil); puts "QA_JOB=#{j.provider_job_id} #{j.job_id}"'),
            ):
                result = subprocess.check_output([*compose, 'run', '-T', '--rm', '--no-deps', '--entrypoint',
                    'bundle', svc, 'exec', 'rails', 'runner', expression], text=True, timeout=180)
                match = re.search(r'QA_JOB=([0-9a-f]{24}) ([0-9a-f-]{36})', result)
                if not match:
                    raise RuntimeError('Rails producer did not enqueue ' + svc)
                worker = svc + '_sidekiq'
                for _ in range(60):
                    logs = subprocess.check_output([*compose, 'logs', '--no-color', worker], text=True)
                    if (re.search(r'jid=' + match.group(1) + r'\b[^\n]*\bdone\b', logs) or
                        re.search(r'Performed .*Job \(Job ID: ' + match.group(2) + r'\)', logs)):
                        break
                    time.sleep(1)
                else:
                    for line in logs.splitlines():
                        if match.group(1) in line or match.group(2) in line:
                            print('Worker log:', line[:400], flush=True)
                    print('Worker state:', subprocess.check_output(
                        [*compose, 'ps', '--format', '{{.Name}} {{.State}} {{.Health}}', worker],
                        text=True).strip(), flush=True)
                    raise RuntimeError('Worker did not confirm job ' + svc)
                print(svc + ' real Rails producer and real job processed', flush=True)
            print('PASS isolated Rails producer/worker smoke', flush=True)
        finally:
            subprocess.run([*compose, 'down', '--volumes', '--remove-orphans'], timeout=180,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


if __name__ == '__main__':
    main()
