"""Readiness probe boundaries: no auth secrets, redirect following or paid endpoints."""
import json
import unittest
from pipelines.release_probe import base_url,probe,NoRedirects,CHECKS

class ReleaseProbe(unittest.TestCase):
    def test_only_https_corner_or_loopback_and_no_embedded_credentials(self):
        for url in ('http://coopscorner.tech','https://example.invalid','https://user:secret@coopscorner.tech','https://coopscorner.tech?token=secret','https://coopscorner.tech/api','https://coopscorner.tech/#secret'):
            with self.assertRaises(ValueError):base_url(url)
        self.assertEqual(base_url('http://127.0.0.1:3000/'),'http://127.0.0.1:3000')
    def reader(self,origin,path):
        expected=dict(CHECKS)[path]
        body=b'html'
        if path.endswith('.png'):body=b'\x89PNG\r\n\x1a\n'
        if path.endswith('webmanifest'):body=json.dumps(dict(display='standalone',start_url='/',icons=[{'src':'/assets/corner-icon-192.png'},{'src':'/assets/corner-icon-512.png'}])).encode()
        return dict(status=expected,ms=5,cache_control='no-store',nosniff=True,body=body)
    def test_happy_path_is_bounded_and_explicitly_anonymous(self):
        result=probe('https://coopscorner.tech',samples=3,concurrency=2,reader=self.reader)
        self.assertEqual(result['result'],'passed');self.assertEqual(result['state_mutations'],0)
        self.assertIn('not authenticated',result['scope'])
    def test_exposed_personal_api_cannot_report_pass(self):
        def exposed(origin,path):
            item=self.reader(origin,path)
            if path=='/api/refresh/v1/tracker/state':item['status']=200
            return item
        self.assertEqual(probe('https://coopscorner.tech',samples=1,reader=exposed)['result'],'failed')
    def test_cacheable_private_denial_and_missing_manifest_fail(self):
        def broken(origin,path):
            item=self.reader(origin,path)
            if path.startswith('/api/'):item['cache_control']='public, max-age=3600'
            if path.endswith('webmanifest'):item['body']=b'{}'
            return item
        self.assertEqual(probe('https://coopscorner.tech',samples=1,reader=broken)['result'],'failed')
    def test_excessive_http_latency_cannot_report_pass(self):
        def slow(origin,path):
            item=self.reader(origin,path);item['ms']=2000;return item
        result=probe('https://coopscorner.tech',samples=3,reader=slow)
        self.assertEqual(result['result'],'failed')
        self.assertEqual(result['performance_review'],'review_latency')
    def test_redirects_are_not_followed(self):
        self.assertIsNone(NoRedirects().redirect_request(None,None,302,'',{},'https://example.invalid'))
    def test_unbounded_samples_rejected(self):
        with self.assertRaises(ValueError):probe('https://coopscorner.tech',samples=100,reader=self.reader)
        with self.assertRaises(ValueError):probe('https://coopscorner.tech',concurrency=11,reader=self.reader)

if __name__=='__main__':unittest.main()
