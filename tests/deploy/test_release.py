import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts/deploy' / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

request = module('release_request', 'release-request.py')
executor = module('release_executor', 'release-executor.py')

class Requests(unittest.TestCase):
    def write_artifacts(self, folder, sha, wrong_repository=None):
        for name in request.MAP:
            image_name = wrong_repository if wrong_repository and name == 'auth' else name
            value = {
                'component': name,
                'image': 'ghcr.io/murilloimparavel/crcn-release-' + image_name + '@sha256:' + 'b' * 64,
                'release_sha': sha,
                'source_sha': request.pinned_source_sha(name, sha),
                'source_repository': request.SOURCE_REPOSITORIES[name],
            }
            (folder / (name + '.json')).write_text(json.dumps(value))

    def test_aggregates_exact_scanned_components(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            sha = request.subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=request.ROOT,
                                         text=True, capture_output=True, check=True).stdout.strip()
            self.write_artifacts(folder, sha)
            result = request.build(folder, sha)
            executor.validate_request(result)
            self.assertEqual(len(result['images']), 9)
            self.assertEqual(result['images']['evocrm_crm'], result['images']['evocrm_crm_sidekiq'])
            (folder / 'extra.json').write_text('{}')
            with self.assertRaises(ValueError): request.build(folder, sha)

    def test_rejects_other_component_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            sha = request.subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=request.ROOT,
                                         text=True, capture_output=True, check=True).stdout.strip()
            self.write_artifacts(folder, sha, wrong_repository='wrong')
            with self.assertRaises(ValueError): request.build(folder, sha)

    def test_rejects_artifact_from_other_source_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            sha = request.subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=request.ROOT,
                                         text=True, capture_output=True, check=True).stdout.strip()
            self.write_artifacts(folder, sha)
            artifact = json.loads((folder / 'frontend.json').read_text())
            artifact['source_sha'] = 'c' * 40
            (folder / 'frontend.json').write_text(json.dumps(artifact))
            with self.assertRaisesRegex(ValueError, 'source differs'):
                request.build(folder, sha)

    def test_rejects_command_injection_fields(self):
        data = {'schema_version': 1, 'release_sha': 'a' * 40, 'images': {}, 'command': ['sh']}
        with self.assertRaises(ValueError): executor.validate_request(data)

    def test_activation_is_disabled_before_network_or_commands(self):
        images = {n: 'ghcr.io/murilloimparavel/crcn-release-' + executor.COMPONENTS[n] + '@sha256:' + 'b' * 64 for n in executor.REQUIRED}
        data = {'schema_version': 1, 'release_sha': 'a' * 40, 'images': images}
        with self.assertRaisesRegex(ValueError, 'not approved'):
            executor.execute(data, {'enabled': False}, Path('/tmp/not-created'))

    def test_rejects_mutable_tags(self):
        images = {n: 'ghcr.io/murilloimparavel/test:latest' for n in executor.REQUIRED}
        with self.assertRaises(ValueError):
            executor.validate_request({'schema_version': 1, 'release_sha': 'a' * 40, 'images': images})

    def test_production_rejects_staging_local_image_ids(self):
        images = {n: 'sha256:' + 'b' * 64 for n in executor.REQUIRED}
        with self.assertRaises(ValueError):
            executor.validate_request({'schema_version': 1, 'release_sha': 'a' * 40, 'images': images})

    def test_rejects_correct_digest_from_unrelated_owner_package(self):
        images = {n: 'ghcr.io/murilloimparavel/unrelated@sha256:' + 'b' * 64 for n in executor.REQUIRED}
        with self.assertRaises(ValueError):
            executor.validate_request({'schema_version': 1, 'release_sha': 'a' * 40, 'images': images})


class CandidateRehearsal(unittest.TestCase):
    def test_successful_qa_cannot_hide_unverified_application_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'cycle-result.json').write_text(json.dumps({
                'qa_passed': True, 'rollback_rehearsed': True, 'stopped': True}))
            (folder / 'coolify-application-rollback-result.json').write_text(json.dumps({
                'forced_failure_triggered': True, 'rollback_verified': False,
                'datastores_preserved': True, 'stopped': True}))
            data = {'release_sha': 'a' * 40, 'images': {'test': 'image'}}
            with patch.object(executor, 'STAGING', folder), patch.object(executor.subprocess, 'run'), patch.object(
                    executor.subprocess, 'check_output', return_value='a' * 40):
                with self.assertRaisesRegex(ValueError, 'Selective application rollback'):
                    executor.verify_candidate(data, folder, None)
