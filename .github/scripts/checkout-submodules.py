#!/usr/bin/env python3
"""Checkout approved first-level modules using independent read-only deploy keys."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.request

MODULES = (
    'evo-auth-service-community', 'evo-ai-crm-community', 'sofia-central-frontend',
    'evo-ai-processor-community', 'evo-ai-core-service-community', 'evo-bot-runtime',
    'evo-flow-community', 'evolution-api', 'evolution-go', 'crcn-search-api',
)
RELEASE_MODULES = (
    'evo-auth-service-community', 'evo-ai-crm-community', 'evo-ai-core-service-community',
    'evo-ai-processor-community', 'evo-bot-runtime', 'sofia-central-frontend',
)


def release_module_errors(environment, check_output=subprocess.check_output):
    """Reject a release whose production image inputs are not the modules' current main heads."""
    errors = []
    release_sha = check_output(['git', 'rev-parse', 'HEAD'], text=True, env=environment).strip()
    for module in RELEASE_MODULES:
        remote = f'git@github-ci-{module}:murilloimparavel/{module}.git'
        refs = check_output(['git', 'ls-remote', remote, 'refs/heads/main'],
                            text=True, env=environment).splitlines()
        remote_sha = refs[0].split()[0] if len(refs) == 1 and refs[0].split() else ''
        if len(remote_sha) != 40 or any(char not in '0123456789abcdef' for char in remote_sha):
            errors.append(f'{module}: could not resolve refs/heads/main')
            continue
        pinned_sha = check_output(['git', 'rev-parse', f'{release_sha}:{module}'],
                                  text=True, env=environment).strip()
        checked_out_sha = check_output(['git', '-C', module, 'rev-parse', 'HEAD'],
                                       text=True, env=environment).strip()
        if checked_out_sha != pinned_sha:
            errors.append(f'{module}: checkout {checked_out_sha} differs from release gitlink {pinned_sha}')
        if pinned_sha != remote_sha:
            errors.append(f'{module}: release gitlink {pinned_sha} differs from module main {remote_sha}')
    return errors


def require_release_module_mains(environment):
    return environment.get('REQUIRE_RELEASE_MODULE_MAINS') == 'true'


def main():
    subprocess.run(['bash', '.github/scripts/validate-submodules.sh'], check=True)
    raw = os.environ.pop('SUBMODULES_SSH_KEYS', '')
    if not raw:
        raise SystemExit('SUBMODULES_SSH_KEYS is missing; read-only module keys are required')
    keys = json.loads(raw)
    if set(keys) != set(MODULES):
        raise SystemExit('Deploy key bundle must contain exactly the approved module set')
    headers = {'Accept': 'application/vnd.github+json'}
    token = os.environ.get('GH_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request('https://api.github.com/meta', headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        host_keys = json.load(response)['ssh_keys']
    with tempfile.TemporaryDirectory(prefix='crcn-module-keys-') as temporary:
        folder = Path(temporary)
        known_hosts = folder / 'known_hosts'
        known_hosts.write_text(''.join('github.com ' + key + '\n' for key in host_keys))
        config = []
        for module in MODULES:
            key = folder / module
            key.write_text(keys[module])
            key.chmod(0o600)
            config.append(f'Host github-ci-{module}\n  HostName github.com\n  User git\n'
                          f'  IdentityFile {key}\n  IdentitiesOnly yes\n  HostKeyAlias github.com\n'
                          f'  UserKnownHostsFile {known_hosts}\n  StrictHostKeyChecking yes\n')
        ssh_config = folder / 'config'
        ssh_config.write_text('\n'.join(config))
        subprocess.run(['git', 'submodule', 'init'], check=True)
        for module in MODULES:
            subprocess.run(['git', 'config', f'submodule.{module}.url',
                            f'git@github-ci-{module}:murilloimparavel/{module}.git'], check=True)
        environment = os.environ.copy()
        # Git invokes GIT_SSH_COMMAND through a shell; shlex.quote handles paths.
        import shlex
        environment['GIT_SSH_COMMAND'] = 'ssh -F ' + shlex.quote(str(ssh_config))
        subprocess.run(['git', '-c', 'protocol.file.allow=never', 'submodule', 'update',
                        '--init', '--depth', '1', '--', *MODULES], env=environment, check=True)
        if require_release_module_mains(os.environ):
            errors = release_module_errors(environment)
            if errors:
                raise SystemExit('Release image inputs must match each module main:\n- ' + '\n- '.join(errors))
    print('Approved modules checked out; temporary private keys removed')


if __name__ == '__main__':
    main()
