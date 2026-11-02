import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from car_space_checker.http import make_handler, capture_time
from car_space_checker.service import Service
from test_service import CONFIG, FixedDetector, photo

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.service=Service(self.temp.name,detector=FixedDetector(),clock=lambda:1010)
        self.service.configure(CONFIG)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.service,'test-secret'))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.host='127.0.0.1:'+str(self.server.server_port)

    def request(self,path,body,headers=None):
        conn=http.client.HTTPConnection(self.host)
        try:
            conn.request('POST',path,body,headers or {})
            response=conn.getresponse(); return response.status,json.loads(response.read())
        finally: conn.close()

    def test_live_observations_require_authentication_before_processing(self):
        code,_=self.request('/api/observe',photo())
        self.assertEqual(code,401)
        self.assertEqual(self.service.status()['state'],'unknown')

    def test_capture_time_is_required_and_must_include_timezone(self):
        headers={'Authorization':'Bearer test-secret','X-Camera-Id':'floodlight','X-Observation-Id':'one'}
        code,_=self.request('/api/observe',photo(),headers); self.assertEqual(code,400)
        headers['X-Observed-At']='2026-11-02T20:00:00'
        code,_=self.request('/api/observe',photo(),headers); self.assertEqual(code,400)

    def test_cross_origin_settings_write_is_rejected(self):
        code,_=self.request('/api/settings',json.dumps(CONFIG),{'Origin':'https://untrusted.example','Content-Type':'application/json'})
        self.assertEqual(code,403)

    def test_same_origin_preview_is_isolated(self):
        import base64
        body=json.dumps({'settings':CONFIG,'image':base64.b64encode(photo()).decode()})
        code,result=self.request('/api/preview',body,{'Origin':'http://'+self.host,'Content-Type':'application/json'})
        self.assertEqual(code,200); self.assertTrue(result['preview_only'])
        self.assertEqual(self.service.status()['state'],'unknown')

    def test_timestamp_with_offset_is_converted_to_utc(self):
        self.assertEqual(capture_time('1970-01-01T01:16:40+01:00'),1000)

    def test_rebinding_host_is_rejected_even_with_matching_origin(self):
        code,_=self.request('/api/settings',json.dumps(CONFIG),{'Host':'attacker.example','Origin':'http://attacker.example','Content-Type':'application/json'})
        self.assertEqual(code,403)

    def test_rebinding_host_cannot_read_local_images_or_settings(self):
        for path in ['/api/status','/api/example-image']:
            conn=http.client.HTTPConnection(self.host)
            try:
                conn.request('GET',path,headers={'Host':'attacker.example'})
                response=conn.getresponse(); response.read()
                self.assertEqual(response.status,403)
            finally: conn.close()

class IngressTests(unittest.TestCase):
    def handler(self,address):
        from unittest.mock import Mock
        handler=make_handler(Mock(),'token',ingress=True).__new__(make_handler(Mock(),'token',ingress=True))
        handler.client_address=(address,12345)
        handler.headers={'Host':'home.example','Origin':'https://home.example','X-Ingress-Path':'/api/hassio_ingress/test'}
        return handler

    def test_ingress_only_accepts_supervisor_even_with_forged_headers(self):
        self.assertTrue(self.handler('172.30.32.2').allowed_host())
        self.assertFalse(self.handler('127.0.0.1').allowed_host())
        self.assertFalse(self.handler('172.30.33.9').allowed_host())

    def test_ingress_origin_must_match_forwarded_host(self):
        handler=self.handler('172.30.32.2')
        handler.headers['Host']='internal:8080'
        handler.headers['X-Forwarded-Host']='home.example'
        self.assertTrue(handler.allowed_origin())
        handler.headers['Origin']='https://attacker.example'
        self.assertFalse(handler.allowed_origin())
