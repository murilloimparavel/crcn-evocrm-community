#!/usr/bin/env python3
"""Root-owned hooks for the fixed production stack."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
import yaml

ROOT = Path('/data/evocrm-deploy-executor')
RESOURCE = 'tzbydmxtjuilf4xq2gow9gcs'
DIRECTORY = Path('/data/coolify/services') / RESOURCE
WORKERS = ('evocrm_auth_sidekiq', 'evocrm_crm_sidekiq')
LOOKUP = "p=Sidekiq::ProcessSet.new.find{|x|x['hostname']==Socket.gethostname}; abort 'worker missing' unless p; "


def run(arguments, timeout=180):
    subprocess.run(arguments, check=True, timeout=timeout)


def worker_command(name, ruby):
    return ['docker', 'exec', name + '-' + RESOURCE, 'bundle', 'exec', 'ruby',
            '-rsidekiq/api', '-rsocket', '-e', LOOKUP + ruby]


def stores():
    return {name: subprocess.check_output(['docker', 'inspect', '--format',
            '{{.Id}} {{.State.StartedAt}}', name + '-' + RESOURCE], text=True).strip()
            for name in ('postgres', 'redis')}


def drain():
    (ROOT / 'datastores-before.private.json').write_text(json.dumps(stores()))
    for name in WORKERS:
        run(worker_command(name, """p.quiet!; deadline=Time.now+120; loop do
          current=Sidekiq::ProcessSet.new.find{|x|x['hostname']==Socket.gethostname}
          break if current && current['quiet'].to_s=='true' && current['busy'].to_i==0
          abort 'worker drain timeout' if Time.now>deadline
          sleep 2
        end"""), 150)


def resume():
    for name in WORKERS:
        status = subprocess.check_output(worker_command(name, "puts(p['quiet'].to_s)"), text=True).strip()
        if status == 'true':
            run(['docker', 'restart', name + '-' + RESOURCE], 120)
        run(worker_command(name, "abort 'worker still quiet' if p['quiet'].to_s=='true'"), 45)


def migrate(candidate):
    path = Path(candidate)
    if path != ROOT / 'candidate-compose.private.yml' or path.is_symlink():
        raise ValueError('Unexpected candidate file')
    proposed = yaml.safe_load(path.read_text())['services']
    # The Coolify rendered file carries the actual network, mounts and env.
    # Substitute only the already-validated candidate image references.
    effective = yaml.safe_load((DIRECTORY / 'docker-compose.yml').read_text())
    for name in ('evocrm_auth', 'evocrm_crm', 'evocrm_core', 'evocrm_processor'):
        image = proposed[name]['image']
        if not re.fullmatch(r'ghcr\.io/murilloimparavel/crcn-release-[a-z]+@sha256:[a-f0-9]{64}', image):
            raise ValueError('Unexpected candidate image')
        effective['services'][name]['image'] = image
    temporary = ROOT / 'migration-compose.private.yml'
    temporary.write_text(yaml.safe_dump(effective, sort_keys=False))
    compose = ['docker', 'compose', '--project-directory', str(DIRECTORY), '--project-name',
               RESOURCE, '--env-file', str(DIRECTORY / '.env'), '-f', str(temporary)]
    run(compose + ['config', '--quiet'])
    commands = [
        ('evocrm_auth', 'bundle', ['exec', 'rails', 'db:migrate']),
        ('evocrm_crm', 'bundle', ['exec', 'rails', 'db:migrate']),
        ('evocrm_core', 'sh', ['-ec', 'exec ./migrate -database "postgres://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}?sslmode=disable&x-migrations-table=evo_core_community_schema_migrations" -path ./migrations up']),
        ('evocrm_processor', 'alembic', ['upgrade', 'head']),
    ]
    for name, entrypoint, arguments in commands:
        run(compose + ['run', '-T', '--rm', '--no-deps', '--entrypoint', entrypoint,
                       name, *arguments], 480)


def smoke():
    before = json.loads((ROOT / 'datastores-before.private.json').read_text())
    if stores() != before:
        raise RuntimeError('Datastore container restarted during deployment')
    run(['docker', 'exec', 'evocrm_gateway-' + RESOURCE, 'wget', '-q', '-O',
         '/dev/null', 'http://127.0.0.1:3030/ready'], 30)
    for url in ('https://crm.caldasindica.com',):
        with urllib.request.urlopen(url, timeout=20) as response:
            if response.status != 200:
                raise RuntimeError('Public smoke check failed')


def main():
    os.umask(0o077)
    if os.geteuid() != 0:
        raise ValueError('Use the installed executor')
    operation, *arguments = sys.argv[1:]
    if operation == 'drain' and not arguments:
        drain()
    elif operation == 'resume' and not arguments:
        resume()
    elif operation == 'migrate' and len(arguments) == 1:
        migrate(arguments[0])
    elif operation == 'smoke' and len(arguments) == 1 and re.fullmatch('[a-f0-9]{40}', arguments[0]):
        smoke()
    else:
        raise ValueError('Unsupported hook operation')


if __name__ == '__main__':
    main()
