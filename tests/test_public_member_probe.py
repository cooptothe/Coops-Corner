import json
import unittest
from pipelines.public_member_probe import journey,ORIGIN,ME,LOGIN,LOGOUT,READS

class Response:
    def __init__(self,status,payload):self.status_code=status;self.payload=payload;self.headers={'Cache-Control':'no-store','Set-Cookie':'corner_session=synthetic; Path=/; Secure; HttpOnly; SameSite=Strict'}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_content(self,size):yield json.dumps(self.payload).encode()
class Session:
    def __init__(self,role='member',broken=None):self.logged=False;self.calls=[];self.role=role;self.broken=broken;self.closed=False
    def request(self,method,url,**kwargs):
        self.calls.append((method,url,kwargs));path=url.removeprefix(ORIGIN)
        assert kwargs['verify'] is True and kwargs['allow_redirects'] is False
        assert url.startswith(ORIGIN+'/')
        if path==LOGIN:self.logged=True;return Response(200,{'user':{'id':'private-id','role':self.role,'cohort':'beta'}})
        if path==LOGOUT:self.logged=False;return Response(200,{'ok':True})
        if not self.logged:return Response(401,{'error':'Sign in'})
        if path==self.broken:return Response(500,{'secret':'must not escape'})
        if path==ME:return Response(200,{'user':{'id':'private-id','role':self.role}})
        if path.endswith('/billing/status'):return Response(200,{'payments_enabled':False})
        return Response(200,{'meta':{'snapshot_id':'test'},'items':[]})
    def close(self):self.closed=True
class PublicMemberProbe(unittest.TestCase):
    def test_fixed_read_allowlist_and_redacted_report(self):
        session=Session();report=journey('private-name','private-password',transport=session)
        self.assertEqual(report['result'],'passed');self.assertTrue(report['probe_session_logged_out']);self.assertTrue(session.closed)
        text=json.dumps(report)
        for secret in ('private-name','private-password','private-id'):self.assertNotIn(secret,text)
        self.assertTrue(all(method=='GET' or url in (ORIGIN+LOGIN,ORIGIN+LOGOUT) for method,url,_ in session.calls))
    def test_operator_is_incomplete_and_logs_out(self):
        report=journey('owner','secret',transport=Session(role='admin'))
        self.assertEqual(report['result'],'incomplete');self.assertTrue(report['probe_session_logged_out'])
    def test_failed_read_cannot_pass_and_logs_out(self):
        report=journey('member','secret',transport=Session(broken=READS[-1]))
        self.assertEqual(report['result'],'failed');self.assertTrue(report['probe_session_logged_out'])
        self.assertNotIn('must not escape',json.dumps(report))
    def test_insecure_cookie_cannot_pass(self):
        class Insecure(Session):
            def request(self,method,url,**kwargs):
                response=super().request(method,url,**kwargs)
                if url==ORIGIN+LOGIN:response.headers['Set-Cookie']='corner_session=synthetic; HttpOnly; SameSite=Strict'
                return response
        report=journey('member','secret',transport=Insecure())
        self.assertEqual(report['result'],'failed');self.assertTrue(report['probe_session_logged_out'])
    def test_unexpected_live_checkout_cannot_pass(self):
        class Enabled(Session):
            def request(self,method,url,**kwargs):
                response=super().request(method,url,**kwargs)
                if url.endswith('/billing/status'):response.payload={'payments_enabled':True}
                return response
        report=journey('member','secret',transport=Enabled())
        self.assertEqual(report['result'],'failed');self.assertTrue(report['probe_session_logged_out'])
if __name__=='__main__':unittest.main()
