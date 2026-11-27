import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/deploy'))
spec = importlib.util.spec_from_file_location('crm_repull_executor', ROOT / 'scripts/deploy/crm-repull-executor.py')
executor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor)


class Executor(unittest.TestCase):
    def setUp(self):
        self.digest = 'sha256:' + 'a' * 64
        self.old = 'sha256:' + 'b' * 64
        self.new = 'sha256:' + 'c' * 64
        self.request = {'schema_version': 1, 'source_sha': 'd' * 40, 'expected_digest': self.digest}
        self.config = {'crm_repull_enabled': True, 'crm_repull_rehearsed': True}
        self.raw = 'services:\n  evocrm_crm:\n    image: ghcr.io/murilloimparavel/evo-ai-crm-community:latest\n    healthcheck: {test: [CMD, true]}\n  evocrm_crm_sidekiq:\n    image: ghcr.io/murilloimparavel/evo-ai-crm-community:latest\n    healthcheck: {test: [CMD, true]}\n'
        self.client = Mock()
        self.client.current.return_value = self.raw
        self.states = {n: {'healthy': True, 'running': True, 'image_id': self.old, 'container_id': n, 'ref': executor.IMAGE} for n in executor.SERVICES}
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_rejects_extra_request_fields(self):
        with self.assertRaises(ValueError):
            executor.validate_request({**self.request, 'command': 'anything'})

    def test_disabled_stops_before_any_operation(self):
        with patch.object(executor, 'inspect') as inspect, self.assertRaises(ValueError):
            executor.execute(self.request, {}, self.client, self.folder)
        inspect.assert_not_called()

    def invoke(self, smoke_failure=False, compose_failure=False, drain_failure=False, rollback_resume_failure=False):
        def run(args, timeout=120, output=False):
            if args[:3] == ['docker', 'image', 'inspect']:
                return self.new + '\n'
            return None
        def hook(config, name, log, *args):
            if drain_failure and name == 'crm_repull_drain_command':
                raise subprocess.CalledProcessError(1, 'drain')
            if rollback_resume_failure and name == 'crm_repull_resume_command':
                raise subprocess.CalledProcessError(1, 'resume')
            if smoke_failure and name == 'crm_repull_smoke_command':
                raise subprocess.CalledProcessError(1, 'smoke')
        with patch.object(executor, 'inspect', side_effect=lambda n: self.states[n]), \
             patch.object(executor, 'run', side_effect=run), \
             patch.object(executor, 'digest_for', return_value=self.digest), \
             patch.object(executor.release, 'run_hook', side_effect=hook), \
             patch.object(executor, 'wait_healthy') as health, \
             patch.object(executor, 'compose', side_effect=subprocess.TimeoutExpired('compose', 1) if compose_failure else None) as compose:
            result = executor.execute(self.request, self.config, self.client, self.folder)
            return result, health, compose

    def test_success_keeps_latest_and_recreates_only_selected_services(self):
        _, health, compose = self.invoke()
        self.assertEqual(compose.call_args.args[0][-2:], list(executor.SERVICES))
        self.assertEqual(health.call_args.args[0], self.new)
        self.assertEqual(json.loads((self.folder / 'crm-repull-state.json').read_text())['phase'], 'healthy')
        self.client.set_compose.assert_not_called()

    def test_failed_smoke_restores_previous_image(self):
        with self.assertRaisesRegex(RuntimeError, 'restored and verified'):
            self.invoke(smoke_failure=True)
        self.assertEqual(json.loads((self.folder / 'crm-repull-state.json').read_text())['phase'], 'rolled-back')

    def test_partial_drain_requires_reconciliation(self):
        with self.assertRaises(executor.ReconciliationRequired):
            self.invoke(drain_failure=True)
        self.assertEqual(json.loads((self.folder / 'crm-repull-state.json').read_text())['phase'], 'reconciliation-required')

    def test_failed_resume_after_rollback_requires_reconciliation(self):
        with self.assertRaises(executor.ReconciliationRequired):
            self.invoke(smoke_failure=True, rollback_resume_failure=True)
        self.assertEqual(json.loads((self.folder / 'crm-repull-state.json').read_text())['phase'], 'reconciliation-required')

    def test_timed_out_start_requires_reconciliation(self):
        with self.assertRaises(executor.ReconciliationRequired):
            self.invoke(compose_failure=True)
        self.assertEqual(json.loads((self.folder / 'crm-repull-state.json').read_text())['phase'], 'reconciliation-required')


if __name__ == '__main__':
    unittest.main()
