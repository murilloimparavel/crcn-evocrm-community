import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts/deploy' / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

request = module('release_request', 'release-request.py')
executor = module('release_executor', 'release-executor.py')

class Requests(unittest.TestCase):
    def test_aggregates_exact_scanned_components(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for name in request.MAP:
                (folder / (name + '.json')).write_text(json.dumps({name: 'ghcr.io/murilloimparavel/crcn-release-' + name + '@sha256:' + 'b' * 64}))
            result = request.build(folder, 'a' * 40)
            executor.validate_request(result)
            self.assertEqual(len(result['images']), 9)
            self.assertEqual(result['images']['evocrm_crm'], result['images']['evocrm_crm_sidekiq'])
            (folder / 'extra.json').write_text('{}')
            with self.assertRaises(ValueError): request.build(folder, 'a' * 40)

    def test_rejects_other_component_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for name in request.MAP:
                (folder / (name + '.json')).write_text(json.dumps({name: 'ghcr.io/murilloimparavel/crcn-release-wrong@sha256:' + 'b' * 64}))
            with self.assertRaises(ValueError): request.build(folder, 'a' * 40)

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
