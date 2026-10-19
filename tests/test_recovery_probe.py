import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pipelines import recovery_probe as probe

class RecoveryProbe(unittest.TestCase):
    def state(self,boot='before'):
        return dict(boot_id=boot,release_commit='release',private_fingerprints={'config':'hash'},checked_at_utc='now')

    def test_acceptance_requires_changed_boot_same_release_and_private_config(self):
        self.assertTrue(probe.verify(self.state(),self.state('after'))['boot_changed'])
        for after in (self.state(),dict(self.state('after'),release_commit='different'),
                      dict(self.state('after'),private_fingerprints={'config':'changed'})):
            with self.assertRaises(RuntimeError):probe.verify(self.state(),after)

    def test_enabled_collector_refused_even_when_inactive(self):
        for setting in ('enabled','enabled-runtime','linked','alias','indirect'):
            with self.assertRaises(RuntimeError):
                probe.reject_collectors('corner-collection.service '+setting+' disabled')
        with patch.object(probe.subprocess,'run',return_value=SimpleNamespace(returncode=0)):
            with self.assertRaises(RuntimeError):probe.reject_collectors('corner-collection.service disabled disabled')

    def test_disabled_collectors_do_not_start_anything(self):
        with patch.object(probe.subprocess,'run',return_value=SimpleNamespace(returncode=3)) as run:
            self.assertEqual(probe.reject_collectors('corner-collection.service disabled disabled'),['corner-collection.service'])
            self.assertEqual(run.call_args.args[0],['systemctl','is-active','--quiet','corner-collection.service'])

    def test_boot_phase_and_private_evidence_are_repeatable(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'before.json'
            with patch.object(probe,'BEFORE',path),patch.object(probe,'boot_id',return_value='before'):
                self.assertEqual(probe.phase(),'prepare')
                probe.write_private(path,self.state())
                self.assertEqual(probe.phase(),'reboot')
                with patch.object(probe,'boot_id',return_value='after'):
                    self.assertEqual(probe.phase(),'verify')
                self.assertEqual(json.loads(path.read_text())['boot_id'],'before')
                self.assertEqual(list(path.parent.glob('before.json.*')),[])

if __name__=='__main__':unittest.main()
