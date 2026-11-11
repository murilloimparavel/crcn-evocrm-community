#!/usr/bin/python3
"""Root-owned entry point reached through a forced SSH command."""
import json
import os
from pathlib import Path
import sys

ROOT = Path('/data/evocrm-deploy-executor')
if os.geteuid() != 0:
    raise SystemExit(1)
if sys.argv[1:] == ['access-check']:
    config = json.loads((ROOT / 'config.json').read_text())
    print(json.dumps({'access': 'restricted-executor', 'enabled': config.get('enabled') is True,
                      'baseline_approved': config.get('baseline_approved') is True}))
elif sys.argv[1:] == ['rehearse']:
    os.execv('/usr/bin/python3', ['python3', str(ROOT / 'bin/release-executor.py'), '--rehearse'])
elif len(sys.argv) == 1:
    os.execv('/usr/bin/python3', ['python3', str(ROOT / 'bin/release-executor.py')])
else:
    raise SystemExit('Unsupported executor operation')
