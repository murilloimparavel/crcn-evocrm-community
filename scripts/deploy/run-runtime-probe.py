import json,os,subprocess
from pathlib import Path
root=Path('/data/evocrm-staging')
metadata=json.load((root/'metadata.json').open())
if metadata['service_uuid']!='w3ic7aoj22xbx6ljsb7evu6f':raise RuntimeError('Not staging')
secret=json.load((root/'synthetic-secrets.private.json').open())['bot']
env=os.environ.copy();env['QA_BOT_SECRET']=secret
result=subprocess.run(['docker','exec','-i','-e','QA_BOT_SECRET','evocrm_processor-'+metadata['service_uuid'],'python','-'],input=(root/'runtime-staging-probe.py').read_text(),env=env,capture_output=True,text=True,timeout=80)
with (root/'runtime-probe.private.log').open('w') as f:f.write(result.stdout+result.stderr)
if result.returncode:raise RuntimeError('Synthetic runtime probe failed; private log retained')
receipt=json.loads(result.stdout.strip())
(root/'runtime-probe-result.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt))
