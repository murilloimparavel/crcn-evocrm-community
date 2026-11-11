import datetime,json,re,sys
from pathlib import Path
root=Path('/data/evocrm-deploy-executor')
sha=sys.argv[1]
if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('Full source SHA required')
r=json.load((root/'backup-receipt.private.json').open())
if r.get('release_sha')!=sha:raise RuntimeError('Backup belongs to a different release')
if not all(r.get(k) is True for k in ['roundtrip_verified','database_restore_verified','same_vps']):raise RuntimeError('Backup verification incomplete')
if r.get('offsite_verified') is not False or r.get('backup_policy')!='same-vps-temporary-user-approved':raise RuntimeError('Backup policy mismatch')
age=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(r['verified_at'])).total_seconds()
if age<0 or age>86400:raise RuntimeError('Backup is not fresh')
if not Path(r['recovered_path']).is_file():raise RuntimeError('Recovered backup missing')
print(json.dumps({'backup_verified':True,'same_vps_exception':True,'offsite_verified':False}))
