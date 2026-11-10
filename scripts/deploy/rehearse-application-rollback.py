import importlib.util,json,subprocess,sys
from pathlib import Path
root=Path('/data/evocrm-staging');sys.path.insert(0,str(root/'adapter'))
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
adapter=load('adapter',root/'adapter/coolify-service.py')
bootstrap=load('bootstrap',root/'bootstrap-coolify.py')
staging=load('staging',root/'staging-cycle.py')
token=subprocess.check_output(['docker','exec','coolify','cat','/tmp/evocrm-staging-token.private'],text=True).strip()
client=adapter.Coolify(bootstrap.API.removesuffix('/api/v1'),token,enabled=True,resource=adapter.STAGING_RESOURCE,application_only=True)
manifest=json.load((root/'candidate-local-images.json').open());raw=client.current()
release=adapter.plan(raw,manifest['images'],resource=adapter.STAGING_RESOURCE)
state=root/'application-rollback-rehearsal';state.mkdir(mode=0o700,exist_ok=True)
health=adapter.DockerHealth(timeout=360,stable_rounds=3,interval=5,resource=adapter.STAGING_RESOURCE)
compose=['docker','compose','--project-name',staging.RESOURCE,'--env-file',str(staging.COMPOSE.parent/'.env'),'-f',str(staging.COMPOSE)]
def database_state():
 return {n:subprocess.check_output(['docker','inspect','--format','{{.Id}} {{.State.StartedAt}}',n+'-'+staging.RESOURCE],text=True).strip() for n in ('postgres','redis')}
receipt={'resource':staging.RESOURCE,'application_only':True,'forced_failure_triggered':False,'rollback_verified':False,'datastores_preserved':False,'stopped':False}
with (root/'application-rollback.private.log').open('w') as log:
 try:
  staging.command(compose+['up','-d','--wait','--wait-timeout','300'],log,360)
  baseline=database_state()
  def force_failure():
   if database_state()!=baseline:raise RuntimeError('Datastore restarted during application deploy')
   receipt['forced_failure_triggered']=True
   raise RuntimeError('Intentional staging smoke failure after candidate was healthy')
  try:
   adapter.promote(client,release,health,force_failure,state)
   raise RuntimeError('Forced failure did not abort deployment')
  except adapter.DeploymentError as error:
   if 'previous application images restored and verified' not in str(error):raise
   receipt['rollback_verified']=True
  receipt['datastores_preserved']=database_state()==baseline
 finally:
  try:
   staging.stop_stack(log)
   receipt['stopped']=True
  finally:
   (root/'coolify-application-rollback-result.json').write_text(json.dumps(receipt,indent=2))
   print(json.dumps(receipt),flush=True)
if not all(receipt[k] for k in ('forced_failure_triggered','rollback_verified','datastores_preserved','stopped')):raise SystemExit(1)
