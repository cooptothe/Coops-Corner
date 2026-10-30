import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from corner.credit_governor import Refused
from pipelines.collection_live import failure_detail

class SafeDiagnostics(unittest.TestCase):
    def test_exception_credentials_never_enter_diagnostics(self):
        try:raise RuntimeError('https://provider/?apiKey=PRIVATE_PASSWORD')
        except RuntimeError as error:result=failure_detail(error)
        self.assertEqual(result['error_type'],'RuntimeError')
        self.assertNotIn('PRIVATE_PASSWORD',json.dumps(result))
        self.assertTrue(result['location'])
        self.assertEqual(failure_detail(Refused('Worker lease lost'))['failure_code'],'lease_lost')

class Watchdog(unittest.TestCase):
    def test_failed_service_recovers_but_manual_stop_and_healthy_worker_do_not(self):
        bash='C:/Program Files/Git/bin/bash.exe' if os.name=='nt' else shutil.which('bash')
        if not bash or not Path(bash).exists():self.skipTest('bash unavailable')
        source=(Path(__file__).resolve().parents[1]/'deploy/collection-watchdog.sh').read_text(encoding='utf-8').split('# Refuse unattended recovery')[0]
        for active,failed,health,expected in [(0,1,0,False),(0,1,10,True),(1,0,0,True),(1,0,10,True),(1,1,0,False),(0,1,1,False)]:
            with self.subTest(active=active,failed=failed,health=health):
                mocks=f"""cd() {{ return 0; }}
systemctl() {{ if [ \"$1\" = is-active ]; then return {active}; else return {failed}; fi; }}
runuser() {{ return {health}; }}
"""
                result=subprocess.run([bash,'-c',mocks+source+'\nprintf RECOVERY_SELECTED'],text=True,capture_output=True)
                self.assertEqual('RECOVERY_SELECTED' in result.stdout,expected,result.stderr)
