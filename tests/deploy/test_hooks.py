import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'production_hooks', Path(__file__).resolve().parents[2] / 'scripts/deploy/production-hooks.py')
hooks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hooks)


class ProductionHooks(unittest.TestCase):
    def test_resume_keeps_active_workers_running(self):
        with patch.object(hooks.subprocess, 'check_output', return_value='false\n'), patch.object(hooks, 'run') as run:
            hooks.resume()
        self.assertTrue(run.call_args_list)
        self.assertTrue(all(call.args[0][:2] == ['docker', 'exec'] for call in run.call_args_list))

    def test_resume_restarts_only_quiet_workers(self):
        with patch.object(hooks.subprocess, 'check_output', side_effect=['true\n', 'false\n']), patch.object(hooks, 'run') as run:
            hooks.resume()
        restarts = [call.args[0] for call in run.call_args_list if call.args[0][:2] == ['docker', 'restart']]
        self.assertEqual(restarts, [['docker', 'restart', 'evocrm_auth_sidekiq-' + hooks.RESOURCE]])

    def test_migration_rejects_paths_outside_the_private_candidate(self):
        with self.assertRaises(ValueError):
            hooks.migrate('/tmp/untrusted-compose.yml')
