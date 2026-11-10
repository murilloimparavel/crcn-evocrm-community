import importlib.util,json,os,re,subprocess,sys,time
from pathlib import Path
os.umask(0o077)
root=Path('/data/evocrm-deploy-executor');folder=Path('/var/backups/evocrm-validation')
sha=sys.argv[1]
if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('Full source SHA required')
started=time.time()
env=os.environ.copy();env.update(BACKUP_DIR=str(folder),RESTORE_POSTGRES_IMAGE='pgvector/pgvector@sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b')
with (root/'backup.private.log').open('a') as log:
 subprocess.run(['bash','/data/evocrm-deploy-preparation/backup-restore.sh'],env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1200)
 archives=[p for p in folder.glob('*.dump') if p.stat().st_mtime>=started]
 if len(archives)!=1:raise RuntimeError('Expected one fresh restored archive')
 spec=importlib.util.spec_from_file_location('roundtrip','/data/evocrm-backups/minio-roundtrip.py')
 backup=importlib.util.module_from_spec(spec);spec.loader.exec_module(backup)
 receipt=backup.roundtrip(archives[0],'production')
 receipt.update(release_sha=sha,database_restore_verified=True,offsite_verified=False,backup_policy='same-vps-temporary-user-approved')
 (root/'backup-receipt.private.json').write_text(json.dumps(receipt,indent=2))
 print(json.dumps({'backup_verified':True,'roundtrip_verified':True,'same_vps':True,'offsite_verified':False}),flush=True)
