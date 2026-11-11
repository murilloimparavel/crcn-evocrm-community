import importlib.util
from pathlib import Path
import tempfile
import unittest
import yaml

spec = importlib.util.spec_from_file_location('runtime', Path(__file__).with_name('runtime-only-promote.py'))
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)

class Adapter:
    REQUIRED = {'evocrm_bot_runtime', 'other'}
    @staticmethod
    def approved_image(image, resource): return image in ('sha256:old', 'sha256:new')

class Client:
    enabled=True
    resource='staging'
    def __init__(self, raw): self.raw=raw; self.starts=[]; self.fail_start=False
    def current(self): return self.raw
    def set_compose(self, raw): self.raw=raw
    def discover_applications(self): pass
    def start_application(self, name):
        self.starts.append(name)
        if self.fail_start: raise RuntimeError('uncertain')

class Health:
    def __init__(self): self.images=[]
    def wait(self, images): self.images.append(images)

class Tests(unittest.TestCase):
    def setUp(self):
        self.raw=yaml.safe_dump({'services':{'evocrm_bot_runtime':{'image':'sha256:old','healthcheck':{'test':['true']}},'other':{'image':'unrelated:mutable'}}})
        self.client=Client(self.raw); self.health=Health();self.release=runtime.plan(Adapter,self.raw,'sha256:new','staging')
    def test_only_runtime_changes(self):
        before=yaml.safe_load(self.raw);after=yaml.safe_load(self.release['candidate'])
        self.assertEqual(before['services']['other'],after['services']['other'])
    def test_success_and_forced_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(RuntimeError,'previous runtime configuration restored'):
                runtime.promote(self.client,self.release,self.health,lambda:None,d,lambda: (_ for _ in ()).throw(RuntimeError('fail')))
        self.assertEqual(self.client.raw,self.raw)
        self.assertEqual(self.client.starts,['evocrm_bot_runtime','evocrm_bot_runtime'])
    def test_drift_and_guard_fail_before_write(self):
        self.client.raw+='\n'
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(RuntimeError,'drifted'):runtime.promote(self.client,self.release,self.health,lambda:None,d,lambda:None)
        self.assertEqual(self.client.starts,[])
    def test_uncertain_start_never_restarts_old(self):
        self.client.fail_start=True
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(RuntimeError,'outcome uncertain'):runtime.promote(self.client,self.release,self.health,lambda:None,d,lambda:None)
        self.assertEqual(self.client.raw,self.raw)
        self.assertEqual(len(self.client.starts),1)
    def test_guard_rejects_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(RuntimeError,'not held'):runtime.promote(self.client,self.release,self.health,lambda: (_ for _ in ()).throw(RuntimeError('not held')),d,lambda:None)
        self.assertEqual(self.client.raw,self.raw)
        self.assertEqual(self.client.starts,[])
if __name__ == '__main__': unittest.main()
