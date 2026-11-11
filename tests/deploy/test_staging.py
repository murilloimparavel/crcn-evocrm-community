import copy
import importlib.util
from pathlib import Path
import unittest

p = Path(__file__).resolve().parents[2] / 'scripts/deploy/staging-cycle.py'
spec = importlib.util.spec_from_file_location('staging_cycle', p)
staging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(staging)


class StagingIsolation(unittest.TestCase):
    def setUp(self):
        self.document = {'services': {'app': {'networks': [staging.RESOURCE],
            'volumes': [staging.RESOURCE + '_data:/data'], 'healthcheck': {'test': ['CMD', 'true']},
            'ports': ['127.0.0.1:18080:80']}}, 'volumes': {}}
        self.network = {'Name': staging.RESOURCE, 'Internal': True}

    def test_accepts_internal_stack(self):
        staging.validate(self.document, self.network)

    def test_rejects_external_network(self):
        self.network['Internal'] = False
        with self.assertRaises(ValueError): staging.validate(self.document, self.network)

    def test_rejects_public_port(self):
        self.document['services']['app']['ports'] = ['18080:80']
        with self.assertRaises(ValueError): staging.validate(self.document, self.network)

    def test_rejects_production_volume(self):
        self.document['services']['app']['volumes'] = ['production_data:/data']
        with self.assertRaises(ValueError): staging.validate(self.document, self.network)

    def test_rejects_docker_socket(self):
        self.document['services']['app']['volumes'] = ['/var/run/docker.sock:/var/run/docker.sock']
        with self.assertRaises(ValueError): staging.validate(self.document, self.network)

    def test_rejects_external_volume_alias(self):
        self.document['volumes'][staging.RESOURCE + '_data'] = {'name': 'production_data', 'external': True}
        with self.assertRaises(ValueError): staging.validate(self.document, self.network)

    def test_rejects_second_network(self):
        self.document['services']['app']['networks'].append('production')
        with self.assertRaises(ValueError): staging.validate(self.document, self.network)

    def test_rejects_privileged(self):
        self.document['services']['app']['privileged'] = True
        with self.assertRaises(ValueError): staging.validate(self.document, self.network)

    def test_requires_healthcheck(self):
        del self.document['services']['app']['healthcheck']
        with self.assertRaises(ValueError): staging.validate(self.document, self.network)

    def test_rejects_host_pid_namespace(self):
        self.document['services']['app']['pid'] = 'host'
        with self.assertRaises(ValueError): staging.validate(self.document, self.network)

    def test_rejects_added_capabilities(self):
        self.document['services']['app']['cap_add'] = ['SYS_ADMIN']
        with self.assertRaises(ValueError): staging.validate(self.document, self.network)

    def test_rejects_production_container_name(self):
        self.document['services']['app']['container_name'] = 'app-production'
        with self.assertRaises(ValueError): staging.validate(self.document, self.network)

    def test_rejects_named_volume_backed_by_host_bind(self):
        self.document['volumes'][staging.RESOURCE + '_data'] = {'driver_opts': {'type': 'none', 'o': 'bind', 'device': '/production'}}
        with self.assertRaises(ValueError): staging.validate(self.document, self.network)


class StagingFailureCleanup(unittest.TestCase):
    def test_migration_failure_stops_stack_and_records_failure(self):
        import json
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compose = root / 'compose.yml'
            (root / 'metadata.json').write_text(json.dumps({'service_uuid': staging.RESOURCE}))
            compose.write_text('services:\n  postgres:\n    networks: [' + staging.RESOURCE + ']\n    healthcheck: {test: [CMD, true]}\n')
            calls = []
            def execute(args, log, timeout=600):
                calls.append(args)
                if args[0] == 'python3':
                    raise RuntimeError('simulated failed migration')
            network = [{'Name': staging.RESOURCE, 'Internal': True}]
            queries = iter([b'abcdef123456\n', b'', b'abcdef123456\n', b''])
            def output(args, **kwargs):
                if args[:3] == ['docker', 'network', 'inspect']:
                    return json.dumps(network).encode()
                return next(queries)
            with patch.object(staging, 'ROOT', root), patch.object(staging, 'COMPOSE', compose), \
                 patch.object(staging, 'command', side_effect=execute), \
                 patch.object(staging.subprocess, 'check_output', side_effect=output), \
                 patch('sys.argv', ['staging-cycle.py']):
                with self.assertRaisesRegex(RuntimeError, 'failed migration'):
                    staging.main()
            receipt = json.loads((root / 'cycle-result.json').read_text())
            self.assertFalse(receipt['qa_passed'])
            self.assertTrue(receipt['stopped'])
            self.assertEqual(sum('stop' in args for args in calls), 2)
            self.assertFalse(any('down' in args or '--volumes' in args for args in calls))

class CleanupOwnership(unittest.TestCase):
    def test_stops_only_project_scoped_container_ids_and_verifies_empty(self):
        from unittest.mock import patch
        with patch.object(staging, 'command') as command, \
             patch.object(staging.subprocess, 'check_output', side_effect=[b'abcdef123456\n', b'']) as output:
            staging.stop_stack(None)
            command.assert_called_once_with(['docker', 'stop', '--time', '30', 'abcdef123456'], None, 120)
            self.assertIn('label=com.docker.compose.project=' + staging.RESOURCE, output.call_args.args[0])

    def test_invalid_container_identifier_cannot_become_a_docker_flag(self):
        from unittest.mock import patch
        with patch.object(staging, 'command') as command, \
             patch.object(staging.subprocess, 'check_output', return_value=b'--all'):
            with self.assertRaises(RuntimeError): staging.stop_stack(None)
            command.assert_not_called()


class NetworkRecovery(unittest.TestCase):
    def test_missing_network_is_recreated_internal(self):
        import json
        import subprocess
        import tempfile
        from unittest.mock import patch
        network = {'Name': staging.RESOURCE, 'Internal': True}
        with tempfile.TemporaryDirectory() as directory, patch.object(staging, 'ROOT', Path(directory)):
            with patch.object(staging.subprocess, 'check_output', side_effect=[
                    subprocess.CalledProcessError(1, ['docker']), json.dumps([network]).encode()]):
                with patch.object(staging.subprocess, 'run') as run:
                    self.assertEqual(staging.staging_network(), network)
                    run.assert_called_once_with(
                        ['docker', 'network', 'create', '--internal', '--attachable', staging.RESOURCE],
                        check=True, capture_output=True, timeout=30)

    def test_existing_external_network_is_rejected(self):
        import json
        import tempfile
        from unittest.mock import patch
        network = {'Name': staging.RESOURCE, 'Internal': False}
        with tempfile.TemporaryDirectory() as directory, patch.object(staging, 'ROOT', Path(directory)):
            with patch.object(staging.subprocess, 'check_output', return_value=json.dumps([network]).encode()):
                with patch.object(staging.subprocess, 'run') as run:
                    with self.assertRaises(ValueError):
                        staging.staging_network()
                    run.assert_not_called()
