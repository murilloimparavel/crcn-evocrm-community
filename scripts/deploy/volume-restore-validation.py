#!/usr/bin/env python3
"""Host-only live storage backup/isolated restore validation. Never deploys services.

Archives and logs contain private data and stay on the protected server directory.
This does not establish point-in-time consistency between database and storage.
"""
def main():
    import datetime,json,os,subprocess
    from pathlib import Path
    os.umask(0o077)
    folder=Path('/var/backups/evocrm-validation');folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    image='pgvector/pgvector@sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b'
    resource='tzbydmxtjuilf4xq2gow9gcs'
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    receipts=[]
    for service,destination in [('evocrm_auth','/rails/storage'),('evocrm_crm','/app/storage')]:
     details=json.loads(subprocess.check_output(['docker','inspect',service+'-'+resource],text=True))[0]
     mount=next(m for m in details['Mounts'] if m['Destination']==destination)
     assert mount['Type']=='volume'
     archive=service+'-storage-'+stamp+'.tar';volume='evocrm-restore-storage-'+service+'-'+stamp
     common=['docker','run','--rm','--network','none','--cpus','1','--memory','256m','--pids-limit','128','--entrypoint','sh']
     # No filesystem content, customer filenames or logs are emitted to this caller.
     with open(folder/(archive+'.log'),'w') as log:
      command=common+['--mount',f'type=volume,src={mount["Name"]},dst=/source,readonly','--mount',f'type=bind,src={folder},dst=/backup',image,'-ec',f'tar -C /source -cf /backup/{archive} .']
      backup=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
      if backup.returncode:raise RuntimeError(service+' storage archive failed; private log retained')
      (folder/archive).chmod(0o600)
      subprocess.run(['docker','volume','create',volume],check=True,stdout=subprocess.DEVNULL)
      try:
       command=common+['--mount',f'type=volume,src={volume},dst=/restore','--mount',f'type=bind,src={folder},dst=/backup,readonly',image,'-ec',f'tar -C /restore -xf /backup/{archive}; tar -C /restore -df /backup/{archive}']
       restore=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
       if restore.returncode:raise RuntimeError(service+' storage restoration comparison failed; private log retained')
      finally:subprocess.run(['docker','volume','rm',volume],check=True,stdout=subprocess.DEVNULL)
     digest=subprocess.check_output(['sha256sum',str(folder/archive)],text=True).split()[0]
     (folder/(archive+'.sha256')).write_text(digest+'  '+archive+'\n')
     receipts.append({'service':service,'restored_and_compared':True,'bytes':(folder/archive).stat().st_size,'sha256':digest})
    (folder/('storage-validation-'+stamp+'.json')).write_text(json.dumps({'at':stamp,'receipts':receipts,'live_copy':True,'offsite_verified':False},indent=2))
    print(json.dumps({'storage_restore_validation':receipts,'point_in_time_consistency_verified':False,'offsite_verified':False}))


if __name__ == "__main__":
    main()
