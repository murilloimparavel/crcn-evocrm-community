import importlib.util
from pathlib import Path
import unittest

import yaml

path = Path(__file__).resolve().parents[2] / 'scripts/deploy/crm-repull-plan.py'
spec = importlib.util.spec_from_file_location('crm_repull_plan', path)
repull = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repull)


class RepullPlan(unittest.TestCase):
    def setUp(self):
        self.digest = 'sha256:' + 'a' * 64
        self.raw = yaml.safe_dump({'services': {name: {'image': repull.IMAGE, 'healthcheck': {'test': ['CMD', 'true']}} for name in repull.SERVICES}})
        self.running = {name: {'healthy': True, 'image_id': 'sha256:' + 'b' * 64} for name in repull.SERVICES}

    def test_validates_target_and_records_previous_image(self):
        result = repull.plan(self.raw, self.digest, self.digest, self.running)
        self.assertEqual(result['previous_image_id'], 'sha256:' + 'b' * 64)
        self.assertEqual(result['services'], list(repull.SERVICES))

    def test_rejects_latest_moved_after_approval(self):
        with self.assertRaisesRegex(ValueError, 'no longer matches'):
            repull.plan(self.raw, self.digest, 'sha256:' + 'c' * 64, self.running)

    def test_rejects_divergent_running_images(self):
        self.running['evocrm_crm_sidekiq']['image_id'] = 'sha256:' + 'c' * 64
        with self.assertRaisesRegex(ValueError, 'different images'):
            repull.plan(self.raw, self.digest, self.digest, self.running)

    def test_rejects_missing_healthcheck(self):
        doc = yaml.safe_load(self.raw)
        del doc['services']['evocrm_crm']['healthcheck']
        with self.assertRaisesRegex(ValueError, 'healthcheck'):
            repull.plan(yaml.safe_dump(doc), self.digest, self.digest, self.running)
