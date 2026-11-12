#!/usr/bin/env python3
"""Stage-only Coolify config change/rollback; run with staged adapter on VPS."""
import fcntl
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import urllib.parse
import yaml

ROOT = Path('/data/evocrm-staging')
RESOURCE = 'w3ic7aoj22xbx6ljsb7evu6f'
ADAPTER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ADAPTER.parent))
spec = importlib.util.spec_from_file_location('queueqa_adapter', ADAPTER)
adapter = importlib.util.module_from_spec(spec); spec.loader.exec_module(adapter)
spec = importlib.util.spec_from_file_location('queueqa_stage', ROOT / 'staging-cycle.py')
stage = importlib.util.module_from_spec(spec); spec.loader.exec_module(stage)


def main():
    assert stage.RESOURCE == RESOURCE and adapter.STAGING_RESOURCE == RESOURCE
    config = json.loads(Path('/data/evocrm-deploy-executor/config.json').read_text())
    token = (ROOT / 'coolify-token.private').read_text().strip()
    client = adapter.Coolify(config['coolify_url'], token, enabled=True, resource=RESOURCE, application_only=True)
    health = adapter.DockerHealth(timeout=360, stable_rounds=2, interval=5, resource=RESOURCE)
    state = ROOT / 'queue-config-rollback-rehearsal'; state.mkdir(mode=0o700, exist_ok=True)
    compose = ['docker', 'compose', '--project-name', RESOURCE, '--env-file', str(stage.COMPOSE.parent / '.env'), '-f', str(stage.COMPOSE)]
    def db_state():
        return {n: subprocess.check_output(['docker','inspect','--format','{{.Id}} {{.State.StartedAt}}',n+'-'+RESOURCE],text=True).strip() for n in ('postgres','redis')}
    def path(name):
        values = json.loads(subprocess.check_output(['docker','inspect',name+'-'+RESOURCE], text=True))[0]['Config']['Env']
        value = next(x.split('=',1)[1] for x in values if x.startswith('REDIS_URL='))
        return urllib.parse.urlsplit(value).path
    with (ROOT/'cycle.lock').open('a') as lock, (ROOT/'network.lock').open('a') as network_lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(network_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        active = subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+RESOURCE],text=True).strip()
        if active: raise RuntimeError('staging already active; refusing to interfere')
        network = json.loads(subprocess.check_output(['docker','network','inspect',RESOURCE]))[0]
        stage.validate(yaml.safe_load(stage.COMPOSE.read_text()),network)
        raw = client.current(); doc = yaml.safe_load(raw)
        images = {n: doc['services'][n]['image'] for n in adapter.REQUIRED}
        release = adapter.plan(raw, images, resource=RESOURCE)
        candidate = yaml.safe_load(release['candidate_compose'])
        names = ('evocrm_auth','evocrm_auth_sidekiq')
        for n in names:
            env = dict(candidate['services'][n]['environment'])
            candidate['services'][n]['environment'] = env
            old = env['REDIS_URL']
            u = urllib.parse.urlsplit(old)
            if u.path != '/1': raise RuntimeError('unexpected staging Redis baseline')
            env['REDIS_URL'] = urllib.parse.urlunsplit((u.scheme,u.netloc,'/3',u.query,u.fragment))
        release['candidate_compose'] = yaml.safe_dump(candidate,sort_keys=False)
        receipt = {'stage_only': True,'candidate_verified': False,'rollback_verified': False,'datastores_preserved': False}
        with (state/'run.private.log').open('w') as log:
            try:
                stage.command(compose+['up','-d','--wait','--wait-timeout','300'],log,360)
                baseline = db_state()
                def force_failure():
                    if any(path(n) != '/3' for n in names): raise RuntimeError('candidate Redis config not applied')
                    if db_state() != baseline: raise RuntimeError('datastore changed')
                    receipt['candidate_verified'] = True
                    raise RuntimeError('intentional rollback rehearsal')
                try:
                    adapter.promote(client,release,health,force_failure,state)
                    raise RuntimeError('expected forced rollback')
                except adapter.DeploymentError as error:
                    if 'previous application images restored and verified' not in str(error): raise
                if any(path(n) != '/1' for n in names): raise RuntimeError('rollback Redis config not applied')
                receipt['rollback_verified'] = True
                receipt['datastores_preserved'] = db_state() == baseline
            finally:
                stage.stop_stack(log)
        print(json.dumps(receipt),flush=True)
        if not all(receipt.values()): raise RuntimeError('rehearsal incomplete')


if __name__ == '__main__': main()
