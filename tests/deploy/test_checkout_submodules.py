import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    'checkout_submodules', ROOT / '.github/scripts/checkout-submodules.py')
checkout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checkout)


class ReleaseModuleHeads(unittest.TestCase):
    def test_main_head_gate_is_opt_in(self):
        self.assertFalse(checkout.require_release_module_mains({}))
        self.assertFalse(checkout.require_release_module_mains({'REQUIRE_RELEASE_MODULE_MAINS': 'false'}))
        self.assertTrue(checkout.require_release_module_mains({'REQUIRE_RELEASE_MODULE_MAINS': 'true'}))

    def run_check(self, pinned_sha, checked_out_sha=None):
        release_sha = 'a' * 40
        module_main = 'b' * 40

        def check_output(args, text, env):
            if args == ['git', 'rev-parse', 'HEAD']:
                return release_sha + '\n'
            if args[1] == 'ls-remote':
                return module_main + '\trefs/heads/main\n'
            if args[1] == 'rev-parse' and args[2] == f'{release_sha}:{args[2].split(":", 1)[1]}':
                return pinned_sha + '\n'
            if args[1] == '-C':
                return (checked_out_sha or pinned_sha) + '\n'
            raise AssertionError(args)

        return checkout.release_module_errors({}, check_output)

    def test_accepts_gitlinks_at_each_module_main(self):
        self.assertEqual(self.run_check('b' * 40), [])

    def test_rejects_stale_gitlinks_even_when_checkout_matches(self):
        errors = self.run_check('c' * 40)
        self.assertEqual(len(errors), len(checkout.RELEASE_MODULES))
        self.assertTrue(all('differs from module main' in error for error in errors))

    def test_rejects_checkout_that_does_not_match_gitlink(self):
        errors = self.run_check('b' * 40, checked_out_sha='c' * 40)
        self.assertEqual(len(errors), len(checkout.RELEASE_MODULES))
        self.assertTrue(all('differs from release gitlink' in error for error in errors))


if __name__ == '__main__':
    unittest.main()
