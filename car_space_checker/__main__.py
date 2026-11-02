"""Run with python -m car_space_checker inside Docker Compose."""
import argparse
import json
import logging
import math
import tempfile
import os
from pathlib import Path
import secrets
import subprocess
from .vision import fetch_model

def extract_frame(video, seconds, output):
    from .vision import read_image
    video, output = Path(video), Path(output)
    if not math.isfinite(seconds) or seconds < 0 or not video.is_file():
        raise ValueError('Provide a local recording and a finite, non-negative offset.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        frame = Path(directory) / 'frame.jpg'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y',
                        '-protocol_whitelist','file,pipe','-ss',str(seconds),'-i',str(video),
                        '-frames:v','1',str(frame)],check=True,timeout=60)
        if not frame.is_file():
            raise ValueError('The offset did not produce a frame; previous output left unchanged.')
        read_image(frame.read_bytes())
        frame.replace(output)
    return output


def main():
    parser=argparse.ArgumentParser(description='Local floodlight parking PoC')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('serve')
    sub.add_parser('fetch-model')
    sub.add_parser('init-token')
    analyze=sub.add_parser('analyze'); analyze.add_argument('image'); analyze.add_argument('--config',default='data/zone.json'); analyze.add_argument('--output',default='data/assessment.jpg')
    extract=sub.add_parser('extract'); extract.add_argument('video'); extract.add_argument('--seconds',type=float,required=True); extract.add_argument('--output',default='data/reference.jpg')
    submit=sub.add_parser('submit'); submit.add_argument('image'); submit.add_argument('--observed-at',required=True); submit.add_argument('--id',required=True)
    args=parser.parse_args()
    if args.command == 'fetch-model':
        print(fetch_model())
    elif args.command == 'init-token':
        target=Path('.env')
        content=target.read_text() if target.exists() else Path('.env.example').read_text()
        lines=content.splitlines()
        if any(line.startswith('CHECKER_TOKEN=') and line.partition('=')[2].strip() for line in lines):
            print('An ingestion token already exists; left unchanged.'); return
        lines=[line for line in lines if not line.startswith('CHECKER_TOKEN=')]
        lines.append('CHECKER_TOKEN='+secrets.token_urlsafe(32))
        target.write_text('\n'.join(lines)+'\n'); target.chmod(0o600)
        print('Generated an ingestion token in ignored .env. The token is not printed.')
    elif args.command == 'extract':
        extract_frame(args.video,args.seconds,args.output)
        print(args.output)
    elif args.command == 'submit':
        import urllib.request
        from .http import capture_time
        capture_time(args.observed_at)
        token=os.getenv('CHECKER_TOKEN')
        if not token: parser.error('Generate CHECKER_TOKEN before submitting a live observation.')
        request=urllib.request.Request('http://checker:8080/api/observe',data=Path(args.image).read_bytes(),headers={
            'Authorization':'Bearer '+token,'Content-Type':'image/jpeg','X-Camera-Id':'floodlight',
            'X-Observed-At':args.observed_at,'X-Observation-Id':args.id},method='POST')
        with urllib.request.urlopen(request,timeout=30) as response: print(response.read().decode())
    elif args.command == 'analyze':
        import base64
        from .service import Service
        result=Service().preview(Path(args.image).read_bytes(),json.loads(Path(args.config).read_text()))
        Path(args.output).parent.mkdir(parents=True,exist_ok=True)
        Path(args.output).write_bytes(base64.b64decode(result.pop('image').partition(',')[2]))
        print(json.dumps(result,indent=2)); print('Annotated preview:',args.output)
    else:
        from .http import serve
        from .service import Service
        from .mqtt import Publisher
        logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
        publisher=Publisher() if os.getenv('MQTT_HOST') else None
        serve(Service(publisher=publisher),os.getenv('CHECKER_TOKEN',''))

if __name__ == '__main__': main()
