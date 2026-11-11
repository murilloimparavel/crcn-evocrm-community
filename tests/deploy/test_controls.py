import copy
import datetime as dt
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/deploy'))
import readiness
import healthchecks
spec = importlib.util.spec_from_file_location('render_images', ROOT / 'scripts/deploy/render-images.py')
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)

class Controls(unittest.TestCase):
    def setUp(self):
        self.sha = 'a' * 40
        image = 'ghcr.io/murilloimparavel/test@sha256:' + 'b' * 64
        self.now = dt.datetime.now(dt.timezone.utc)
        self.data = dict(schema_version=1, release_sha=self.sha,
            coolify_service_uuid='tzbydmxtjuilf4xq2gow9gcs',
            migration_strategy='expand-contract', activation_approved=True,
            backup_verified_at=self.now.isoformat(), backup_offsite_verified=True,
            images={s: image for s in readiness.REQUIRED},
            previous_images={s: image for s in readiness.REQUIRED},
            evidence={c: dict(passed=True, release_sha=self.sha, url='https://example.test/evidence') for c in readiness.CONTROLS})
    def errors(self):
        return readiness.validate(self.data, self.sha, self.now)
    def test_example_is_blocked_without_crashing(self):
        import json
        example = json.loads((ROOT / "deploy/production-readiness.example.json").read_text())
        self.assertTrue(readiness.validate(example))
    def test_complete_evidence(self):
        self.assertEqual(self.errors(), [])
    def test_vendor_rollback_uses_exact_origin_digest_for_its_service(self):
        self.data['previous_images']['evocrm_core'] = (
            'evoapicloud/evo-ai-core-service-community@sha256:' + 'c' * 64)
        self.assertEqual(self.errors(), [])
        self.data['previous_images']['evocrm_gateway'] = self.data['previous_images']['evocrm_core']
        self.assertTrue(self.errors())

    def test_vendor_rollback_policy_cannot_replace_candidate_provenance(self):
        self.data['images']['evocrm_core'] = (
            'evoapicloud/evo-ai-core-service-community@sha256:' + 'c' * 64)
        self.assertTrue(self.errors())

    def test_not_approved(self):
        self.data['activation_approved'] = False
        self.assertIn('production activation has not been approved', self.errors())
    def test_every_control_is_required(self):
        for control in readiness.CONTROLS:
            with self.subTest(control=control):
                d = copy.deepcopy(self.data); d['evidence'][control]['passed'] = False
                self.assertTrue(readiness.validate(d))
    def test_unrelated_commit(self):
        self.data['evidence']['ci']['release_sha'] = 'c' * 40
        self.assertTrue(self.errors())
    def test_stale_backup(self):
        self.data['backup_verified_at'] = (self.now - dt.timedelta(days=2)).isoformat()
        self.assertTrue(self.errors())
    def test_future_backup(self):
        self.data['backup_verified_at'] = (self.now + dt.timedelta(hours=1)).isoformat()
        self.assertTrue(self.errors())
    def test_naive_timestamp(self):
        self.data['backup_verified_at'] = '2026-11-03T10:00:00'
        self.assertTrue(self.errors())
    def test_mutable_image(self):
        self.data['images']['evocrm_core'] = 'evoapicloud/core:latest'
        self.assertTrue(self.errors())
    def test_rollback_required(self):
        self.data['previous_images'] = {}
        self.assertTrue(self.errors())
    def test_wrong_resource(self):
        self.data['coolify_service_uuid'] = 'other'
        self.assertTrue(self.errors())
    def test_no_offsite(self):
        self.data['backup_offsite_verified'] = False
        self.assertTrue(self.errors())
    def test_renderer_preserves_state(self):
        source = {'services': {s: {'image':'old', 'environment':{'SECRET':'private'}, 'volumes':['data:/data']} for s in readiness.REQUIRED}, 'volumes':{'data':{}}}
        result = renderer.render(copy.deepcopy(source), self.data['previous_images'])
        for s in readiness.REQUIRED:
            self.assertEqual(result['services'][s]['environment'], source['services'][s]['environment'])
            self.assertEqual(result['services'][s]['volumes'], source['services'][s]['volumes'])
        self.assertEqual(source['volumes'], result['volumes'])
    def test_renderer_rejects_partial_update(self):
        with self.assertRaises(ValueError): renderer.render({'services':{}}, {})
    def test_smoke_rejects_credentials_and_http(self):
        for url in ['http://example.test', 'https://user:password@example.test']:
            with self.assertRaises(ValueError): healthchecks.check(url)

if __name__ == '__main__': unittest.main()

class LocalBackupException(unittest.TestCase):
    setUp = Controls.setUp
    errors = Controls.errors
    def test_explicit_local_exception_preserves_truth_about_offsite(self):
        self.data['backup_offsite_verified'] = False
        self.data['backup_policy'] = {'mode': 'same-vps-temporary',
            'same_failure_domain_acknowledged': True,
            'approval_reference': 'User instruction 2026-11-10: MinIO VPS temporarily'}
        self.assertEqual(self.errors(), [])
        self.assertFalse(self.data['backup_offsite_verified'])

    def test_unacknowledged_local_exception_is_rejected(self):
        self.data['backup_offsite_verified'] = False
        self.data['backup_policy'] = {'mode': 'same-vps-temporary'}
        self.assertIn('offsite backup verification required', self.errors())
