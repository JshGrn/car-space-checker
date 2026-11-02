"""Small local setup UI and authenticated frame ingestion API."""
import base64
import binascii
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit

STATIC = Path(__file__).parent / 'static'

def capture_time(value):
    try:
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            raise ValueError
        return timestamp.timestamp()
    except (ValueError,TypeError,OverflowError) as exc:
        raise ValueError('X-Observed-At must be the capture time in ISO 8601 format with a timezone.') from exc

def make_handler(service, token, ingress=False):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(20)

        def respond(self,status,payload,content_type='application/json'):
            data = json.dumps(payload,allow_nan=False).encode() if content_type == 'application/json' else payload
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Frame-Options','SAMEORIGIN' if ingress else 'DENY')
            self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self'; frame-ancestors " + ("'self'" if ingress else "'none'"))
            self.end_headers()
            self.wfile.write(data)

        def allowed_host(self):
            if ingress:
                return self.client_address[0] == '172.30.32.2'
            try:
                authority = urlsplit('http://' + self.headers.get('Host', ''))
                return (authority.hostname in {'localhost', '127.0.0.1', '::1', 'checker'}
                        and authority.username is None and authority.password is None
                        and not authority.path and not authority.query and not authority.fragment)
            except ValueError:
                return False

        def allowed_origin(self):
            origin = urlsplit(self.headers.get('Origin', ''))
            host = self.headers.get('Host')
            if ingress and self.allowed_host():
                host = self.headers.get('X-Forwarded-Host', host)
            return (origin.scheme in {'http', 'https'} and origin.netloc == host
                    and not origin.username and not origin.password)

        def do_GET(self):
            if not self.allowed_host():
                return self.respond(403, {'error':'Use the local checker address.'})
            if self.path == '/health':
                return self.respond(200,{'ok':True})
            if self.path == '/api/status':
                return self.respond(200,service.status())
            if self.path == '/api/source/frame':
                content = service.capture.latest_frame() if service.capture else None
                if content:
                    return self.respond(200, content, 'image/jpeg')
                return self.respond(404, {'error':'No recording frame has arrived yet.'})
            examples = {
                'empty-day': ('floodlight-day.jpg','day-example.json','Daytime: empty parking area'),
                'car-day': ('parked-day.jpg','parked-day.json','Daytime: valid parked charging reference'),
                'car-night': ('parked-night.jpg','parked-night.json','Night: valid parked charging reference'),
                'car-right': ('parked-right.jpg','parked-right.json','Night: valid right-hand charging reference'),
            }
            if self.path.startswith('/api/example/'):
                key = self.path.removeprefix('/api/example/')
                if key in examples:
                    image_name, config_name, label = examples[key]
                    config = service.directory / config_name
                    if config.exists():
                        return self.respond(200,{'settings':json.loads(config.read_text()),'image':'api/example-image/'+key,'label':label})
                return self.respond(404,{'error':'Example unavailable.'})
            if self.path.startswith('/api/example-image/'):
                key = self.path.removeprefix('/api/example-image/')
                if key in examples:
                    image_path = service.directory / examples[key][0]
                    if image_path.exists():
                        return self.respond(200,image_path.read_bytes(),'image/jpeg')
                return self.respond(404,{'error':'Example image unavailable.'})
            assets={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
            if self.path in assets:
                name,mime=assets[self.path]
                return self.respond(200,(STATIC/name).read_bytes(),mime)
            self.respond(404,{'error':'Not found.'})

        def do_POST(self):
            if not self.allowed_host():
                return self.respond(403, {'error':'Use the local checker address.'})
            try:
                if self.path == '/api/observe':
                    if not token or not secrets.compare_digest(self.headers.get('Authorization',''),f'Bearer {token}'):
                        return self.respond(401,{'error':'A valid ingestion token is required.'})
                elif self.path in {'/api/preview','/api/settings'}:
                    if not self.allowed_origin():
                        return self.respond(403,{'error':'Open the local setup page to make this change.'})
                else:
                    return self.respond(404,{'error':'Not found.'})
                length=int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 14_000_000:
                    return self.respond(413,{'error':'Request must be between 1 byte and 14 MB.'})
                content=self.rfile.read(length)
                if len(content) != length:
                    raise ValueError('Incomplete request.')
                if self.path == '/api/observe':
                    result=service.ingest(content,self.headers.get('X-Camera-Id'),self.headers.get('X-Observation-Id'),capture_time(self.headers.get('X-Observed-At')))
                else:
                    if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                        raise ValueError('Use application/json for setup requests.')
                    payload=json.loads(content)
                    if not isinstance(payload,dict):
                        raise ValueError('Request must be a JSON object.')
                    if self.path == '/api/settings':
                        result=service.configure(payload)
                    else:
                        encoded=payload.get('image')
                        if not isinstance(encoded,str):
                            raise ValueError('A base64 image is required.')
                        result=service.preview(base64.b64decode(encoded,validate=True),payload.get('settings'))
                self.respond(200,result)
            except (ValueError,TypeError,binascii.Error) as exc:
                self.respond(400,{'error':str(exc)})
            except Exception:
                logging.exception('Image request failed')
                self.respond(500,{'error':'Processing failed. Check container logs; live state has not been confirmed.'})

        def log_message(self,format,*args):
            logging.info('%s %s',self.command,self.path)
    return Handler

def serve(service,token,port=8080,ingress=False):
    server=ThreadingHTTPServer(('0.0.0.0',port),make_handler(service,token,ingress=ingress))
    stop=threading.Event()
    def expire():
        while not stop.wait(1): service.tick()
    thread=threading.Thread(target=expire,daemon=True); thread.start()
    try:
        print(f'Car Space Checker listening on port {port}',flush=True)
        server.serve_forever()
    finally:
        stop.set(); server.server_close()
        if service.publisher: service.publisher.close()
