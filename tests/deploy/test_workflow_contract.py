"""Keep production deployment behind the reviewed release workflow."""
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


def load_workflow(name):
    path = ROOT / '.github' / 'workflows' / name
    return yaml.safe_load(path.read_text())


class ProductionWorkflowContract(unittest.TestCase):
    def test_only_the_release_workflow_can_promote_production(self):
        self.assertFalse((ROOT / '.github/workflows/deploy-production.yml').exists())
        self.assertTrue((ROOT / '.github/workflows/auto-release.yml').is_file())

    def test_release_starts_only_after_successful_main_ci_push(self):
        workflow = load_workflow('auto-release.yml')
        events = workflow.get('on', workflow.get(True))
        self.assertEqual(events['workflow_run']['workflows'], ['CI'])
        self.assertEqual(events['workflow_run']['types'], ['completed'])
        self.assertEqual(events['workflow_run']['branches'], ['main'])

        gate = workflow['jobs']['runtime-qa']['if']
        for condition in (
            "github.event.workflow_run.conclusion == 'success'",
            "github.event.workflow_run.event == 'push'",
            "github.event.workflow_run.head_branch == 'main'",
            'github.event.workflow_run.head_repository.full_name == github.repository',
        ):
            self.assertIn(condition, gate)

    def test_promotion_requires_build_qa_production_flag_and_environment(self):
        workflow = load_workflow('auto-release.yml')
        jobs = workflow['jobs']
        promote = jobs['promote']
        self.assertEqual(set(promote['needs']), {'images', 'qa-on-vps'})
        self.assertEqual(promote['environment'], 'production')
        self.assertIn("vars.PRODUCTION_DEPLOY_ENABLED == 'true'", promote['if'])
        self.assertIn("needs.images.result == 'success'", promote['if'])
        self.assertIn("needs.qa-on-vps.result == 'success'", promote['if'])
        self.assertEqual(workflow['concurrency']['group'], 'evocrm-main-release')
        self.assertIs(workflow['concurrency']['cancel-in-progress'], False)

    def test_executor_transport_uses_only_fixed_forced_commands(self):
        workflow = load_workflow('auto-release.yml')
        qa_steps = workflow['jobs']['qa-on-vps']['steps']
        qa_transport = next(step for step in qa_steps if step.get('name') == 'Send to restricted host executor')
        self.assertIn('"evocrm-deploy@$DEPLOY_HOST" rehearse < request.json', qa_transport['run'])

        promote_steps = workflow['jobs']['promote']['steps']
        promote_transport = next(step for step in promote_steps if step.get('name') == 'Send to restricted host executor')
        self.assertIn('"evocrm-deploy@$DEPLOY_HOST" < request.json', promote_transport['run'])
        self.assertNotIn('DEPLOY_COMMAND', promote_transport['run'])

    def test_release_images_are_immutable_and_cannot_move_latest(self):
        text = (ROOT / '.github/workflows/auto-release.yml').read_text()
        self.assertIn('provenance: mode=max', text)
        self.assertIn('sbom: true', text)
        self.assertIn('crcn-release-${{ matrix.name }}:sha-${{ github.event.workflow_run.head_sha }}', text)
        self.assertNotIn('crcn-release-${{ matrix.name }}:latest', text)


if __name__ == '__main__':
    unittest.main()
