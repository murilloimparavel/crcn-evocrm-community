import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import fcntl
import os
import unittest
from unittest.mock import Mock
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/deploy'))
spec = importlib.util.spec_from_file_location('coolify_service', ROOT/'scripts/deploy/coolify-service.py')
a = importlib.util.module_from_spec(spec);spec.loader.exec_module(a)


class Adapter(unittest.TestCase):
    def setUp(self):
        self.old = {s: 'ghcr.io/murilloimparavel/previous@sha256:'+'1'*64 for s in a.REQUIRED}
        self.images = {s: 'ghcr.io/murilloimparavel/next@sha256:'+'2'*64 for s in a.REQUIRED}
        self.current = yaml.safe_dump({'services':{s:{'image':i, 'environment':{'PRIVATE':'unchanged'},
            'volumes':['data:/data']} for s,i in self.old.items()},'volumes':{'data':{}}})
        self.release = a.plan(self.current,self.images)
        self.client=Mock(enabled=True, resource=a.RESOURCE)
        self.client.current.return_value=self.current
        self.health=Mock();self.smoke=Mock()
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.private_dir=Path(temporary.name)
    def test_plan_preserves_environment_and_volumes(self):
        candidate=yaml.safe_load(self.release['candidate_compose'])
        for service in a.REQUIRED:
            self.assertEqual(candidate['services'][service]['environment'],{'PRIVATE':'unchanged'})
            self.assertEqual(candidate['services'][service]['volumes'],['data:/data'])
    def test_rejects_partial_manifest(self):
        with self.assertRaises(a.DeploymentError):a.plan(self.current,{})
    def test_rejects_mutable_images(self):
        self.images['evocrm_core']='evoapicloud/core:latest'
        with self.assertRaises(a.DeploymentError):a.plan(self.current,self.images)
    def test_mutation_disabled_before_network(self):
        opener=Mock();client=a.Coolify('https://coolify.example','private',opener=opener)
        with self.assertRaises(a.DeploymentError):client.deploy()
        opener.open.assert_not_called()
    def test_legacy_get_deploy_cannot_bypass_mutation_gate(self):
        opener=Mock();client=a.Coolify('https://coolify.example','private',opener=opener)
        with self.assertRaises(a.DeploymentError):client.request('GET','/deploy')
        opener.open.assert_not_called()
    def test_restricts_resource(self):
        client=a.Coolify('https://coolify.example','private',enabled=True)
        with self.assertRaises(a.DeploymentError):client.request('POST','/deploy',{'uuid':'other'})
    def test_restricts_origin(self):
        for url in ['http://coolify.example','https://u:p@coolify.example','https://coolify.example/path']:
            with self.assertRaises(a.DeploymentError):a.Coolify(url,'private')
    def test_drift_stops_before_write(self):
        self.client.current.return_value=self.current+'\n'
        with self.assertRaises(a.DeploymentError):a.promote(self.client,self.release,self.health,self.smoke,self.private_dir)
        self.client.set_compose.assert_not_called()
    def test_success_checks_runtime_and_smoke(self):
        a.promote(self.client,self.release,self.health,self.smoke,self.private_dir)
        self.client.set_compose.assert_called_once_with(self.release['candidate_compose'])
        self.health.wait.assert_called_once_with(self.images);self.smoke.assert_called_once()
    def test_health_failure_restores_application(self):
        self.health.wait.side_effect=[a.DeploymentError('unhealthy'),None]
        with self.assertRaisesRegex(a.DeploymentError,'restored and verified'):
            a.promote(self.client,self.release,self.health,self.smoke,self.private_dir)
        self.assertEqual(self.client.set_compose.call_args_list[-1].args[0],self.current)
        self.health.wait.assert_called_with(self.old)
    def test_ambiguous_patch_failure_attempts_recovery(self):
        self.client.set_compose.side_effect=[TimeoutError(),None]
        with self.assertRaisesRegex(a.DeploymentError,'restored and verified'):
            a.promote(self.client,self.release,self.health,self.smoke,self.private_dir)
        self.assertEqual(self.client.deploy.call_count,1)
    def test_unconfirmed_start_restores_configuration_without_racing_coolify(self):
        self.client.application_only = True
        self.client.start_application.side_effect = TimeoutError()
        with self.assertRaises(a.ReconciliationRequired):
            a.promote(self.client, self.release, self.health, self.smoke, self.private_dir)
        self.client.start_application.assert_called_once()
        self.assertEqual(self.client.set_compose.call_args.args[0], self.current)
        self.health.wait.assert_not_called()
        self.smoke.assert_not_called()

    def test_smoke_failure_restores_application(self):
        self.smoke.side_effect=RuntimeError('smoke failed')
        with self.assertRaisesRegex(a.DeploymentError,'restored and verified'):
            a.promote(self.client,self.release,self.health,self.smoke,self.private_dir)
    def test_concurrent_edit_blocks_rollback_overwrite(self):
        self.client.current.side_effect=[self.current,self.current+'\n# concurrent edit\n']
        self.client.deploy.side_effect=TimeoutError()
        with self.assertRaisesRegex(a.DeploymentError,'operator attention'):
            a.promote(self.client,self.release,self.health,self.smoke,self.private_dir)
        self.assertEqual(self.client.set_compose.call_count,1)
    def test_private_recovery_exists_before_mutation(self):
        def validate_snapshot(raw):
            snapshot=next(self.private_dir.glob('recovery-*.json'))
            self.assertEqual(snapshot.stat().st_mode & 0o777,0o600)
            self.assertEqual(json.loads(snapshot.read_text())['previous_compose'],self.current)
        self.client.set_compose.side_effect=validate_snapshot
        a.promote(self.client,self.release,self.health,self.smoke,self.private_dir)
    def test_lock_conflict_stops_before_network(self):
        with open(self.private_dir/'deployment.lock','a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(a.DeploymentError,'resource lock'):
                a.promote(self.client,self.release,self.health,self.smoke,self.private_dir)
        self.client.current.assert_not_called()
    def test_public_recovery_directory_rejected(self):
        self.private_dir.chmod(0o755)
        with self.assertRaisesRegex(a.DeploymentError,'private permissions'):
            a.promote(self.client,self.release,self.health,self.smoke,self.private_dir)
        self.client.current.assert_not_called()
    def test_production_disabled_stops_before_snapshot(self):
        self.client.enabled=False
        with self.assertRaises(a.DeploymentError):a.promote(self.client,self.release,self.health,self.smoke,self.private_dir)
        self.client.current.assert_not_called()

if __name__=='__main__':unittest.main()

class StagingAdapter(unittest.TestCase):
    def test_stage_allows_local_immutable_image_ids(self):
        images={n: 'sha256:'+'b'*64 for n in a.REQUIRED}
        raw=yaml.safe_dump({'services':{n:{'image':'old'} for n in a.REQUIRED}})
        self.assertEqual(a.plan(raw,images,resource=a.STAGING_RESOURCE)['resource'], a.STAGING_RESOURCE)
        with self.assertRaises(a.DeploymentError):a.plan(raw,images)

    def test_stage_client_cannot_deploy_production(self):
        client=a.Coolify('https://coolify.example','private',enabled=True,resource=a.STAGING_RESOURCE)
        with self.assertRaises(a.DeploymentError):client.request('POST','/deploy',{'uuid':a.RESOURCE})

    def test_rejects_unknown_resource(self):
        with self.assertRaises(a.DeploymentError):a.Coolify('https://coolify.example','private',resource='other')

    def test_release_cannot_cross_resource_boundary(self):
        client=Mock(enabled=True,resource=a.RESOURCE)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(a.DeploymentError):
                a.promote(client,{'resource':a.STAGING_RESOURCE},Mock(),Mock(),Path(temporary))
        client.current.assert_not_called()

class ApplicationOnly(unittest.TestCase):
    def test_cannot_deploy_whole_stack(self):
        opener=Mock()
        client=a.Coolify('https://coolify.example','private',enabled=True,opener=opener,application_only=True)
        with self.assertRaises(a.DeploymentError):client.deploy()
        opener.open.assert_not_called()

    def test_never_starts_datastore_application(self):
        client=a.Coolify('https://coolify.example','private',enabled=True,application_only=True)
        client.request=Mock(return_value=[{'name':n,'uuid':'abcdef1234567890'} for n in a.REQUIRED|{'postgres','redis'}])
        client.discover_applications()
        self.assertEqual(set(client._app_paths), a.REQUIRED)
        with self.assertRaises(a.DeploymentError):client.start_application('postgres')

    def test_waits_for_each_changed_app_then_full_health(self):
        client=Mock(application_only=True);health=Mock()
        images={n:'image-for-'+n for n in a.REQUIRED}
        a.apply_images(client,images,{'evocrm_crm','evocrm_bot_runtime'},health)
        self.assertEqual([x.args[0] for x in client.start_application.call_args_list],['evocrm_crm','evocrm_bot_runtime'])
        self.assertEqual([x.args[0] for x in health.wait.call_args_list],[{'evocrm_crm':images['evocrm_crm']},{'evocrm_bot_runtime':images['evocrm_bot_runtime']},images])
        client.deploy.assert_not_called()
