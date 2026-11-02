import tempfile
import unittest
from pathlib import Path
from car_space_checker.ring import RecordingGate, CaptureError, validate_video_url, extract_samples


def snapshot(recording_id='10', started_at=1000, device='floodlight'):
    from datetime import datetime, timezone
    return {'device_ids':[device]*3,'ring':True,'camera_state':'idle',
            'recording_id':recording_id,'started_at':datetime.fromtimestamp(started_at,timezone.utc).isoformat(),
            'video_url':'https://recordings.s3.amazonaws.com/test.mp4?secret=not-real','motion_at':'unknown'}


class RecordingGateTests(unittest.TestCase):
    def test_startup_does_not_assign_a_timestamp_to_existing_recording(self):
        gate=RecordingGate()
        self.assertIsNone(gate.consider(snapshot(),1010))
        self.assertIsNone(gate.consider(snapshot(),1015))

    def test_new_timestamp_with_old_camera_id_cannot_refresh_old_video(self):
        gate=RecordingGate();gate.consider(snapshot(),1010)
        self.assertIsNone(gate.consider(snapshot(started_at=1020),1030))
        self.assertIsNone(gate.consider(snapshot(started_at=1020),1035))
        self.assertIsNone(gate.consider(snapshot('11',1020),1040))
        recording=gate.consider(snapshot('11',1020),1045)
        self.assertEqual(recording.recording_id,'11')
        self.assertEqual(recording.started_at,1020)

    def test_new_camera_with_old_timestamp_waits_for_both(self):
        gate=RecordingGate();gate.consider(snapshot(),1010)
        self.assertIsNone(gate.consider(snapshot('11'),1020))
        self.assertIsNone(gate.consider(snapshot('11'),1025))
        self.assertIsNone(gate.consider(snapshot('11',1020),1030))
        self.assertIsNotNone(gate.consider(snapshot('11',1020),1035))

    def test_processed_recording_cannot_be_replayed_even_if_url_rotates(self):
        gate=RecordingGate();gate.consider(snapshot(),1010)
        gate.consider(snapshot('11',1020),1030)
        recording=gate.consider(snapshot('11',1020),1035)
        gate.complete(recording)
        newer_url=snapshot('11',1020);newer_url['video_url']+='&renewed=yes'
        self.assertIsNone(gate.consider(newer_url,1040))

    def test_different_devices_unknown_timestamps_and_non_ring_are_rejected(self):
        samples=[]
        bad=snapshot();bad['device_ids'][0]='doorbell';samples.append(bad)
        bad=snapshot();bad['started_at']='unknown';samples.append(bad)
        bad=snapshot();bad['ring']=False;samples.append(bad)
        bad=snapshot();bad['device_ids']=[None]*3;samples.append(bad)
        bad=snapshot();bad['started_at']='1970-01-01T00:16:40';samples.append(bad)
        for item in samples:
            with self.subTest(item=item), self.assertRaises(CaptureError):
                RecordingGate().consider(item,1010)

    def test_future_timestamp_rejected_and_backwards_timestamp_not_accepted(self):
        with self.assertRaises(CaptureError):
            RecordingGate().consider(snapshot(started_at=1200),1010)
        gate=RecordingGate();gate.consider(snapshot(),1010)
        self.assertIsNone(gate.consider(snapshot('11',990),1020))
        self.assertIsNone(gate.consider(snapshot('11',990),1025))


class DownloadAndExtractionTests(unittest.TestCase):
    def test_phoenix_recording_host_is_supported(self):
        validate_video_url('https://download-eu-south-2.prod.phoenix.devices.amazon.dev/v1/download/example.mp4?signature=fixture')

    def test_phoenix_lookalikes_and_unsafe_urls_are_rejected(self):
        host='download-eu-south-2.prod.phoenix.devices.amazon.dev'
        for url in [f'http://{host}/a', f'https://{host}.evil.test/a',
                    f'https://evil.{host}/a', 'https://unrelated.amazon.dev/a',
                    f'https://user:pass@{host}/a', f'https://{host}:8443/a']:
            with self.subTest(url=url), self.assertRaises(CaptureError):
                validate_video_url(url)

    def test_private_http_and_lookalike_hosts_rejected(self):
        for url in ['http://ring.com/a','https://127.0.0.1/a','https://ring.com.evil.test/a',
                    'https://evilring.com/a','https://user:pass@ring.com/a','file:///etc/passwd',
                    'https://ring.com:8443/a']:
            with self.subTest(url=url), self.assertRaises(CaptureError): validate_video_url(url)
        validate_video_url('https://recordings.s3.amazonaws.com/a?signature=abc')

    def test_real_video_samples_span_ten_seconds_and_use_capture_time(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            video=Path(directory)/'video.mp4'
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',
                            'testsrc2=size=128x72:rate=2:duration=20','-c:v','libx264','-y',str(video)],check=True)
            samples=extract_samples(video,1000,1025)
            self.assertEqual([item[0] for item in samples],[1008,1013,1018])
            self.assertTrue(all(content.startswith(b'\xff\xd8') for _,content in samples))
            with self.assertRaises(CaptureError): extract_samples(video,1000,1200)

class CaptureFlowTests(unittest.TestCase):
    def capture(self, live=False):
        from car_space_checker.ring import RingCapture
        from unittest.mock import Mock
        service=Mock();service.status.return_value={'settings':{'live_enabled':live}}
        client=Mock();client.snapshot.return_value=snapshot()
        capture=RingCapture(service,{'ring_enabled':True},client=client,clock=lambda:1045)
        capture.gate.consider(snapshot(),1010)
        capture.gate.consider(snapshot('11',1020),1030)
        client.snapshot.return_value=snapshot('11',1020)
        return capture,service,client

    def test_config_disabled_never_starts_capture(self):
        from car_space_checker.ring import RingCapture
        from unittest.mock import Mock
        capture=RingCapture(Mock(),{'ring_enabled':False})
        capture.start()
        self.assertIsNone(capture.thread)
        self.assertFalse(capture.status()['enabled'])

    def test_new_recording_is_preview_only_until_live_enabled(self):
        from unittest.mock import patch
        capture,service,client=self.capture()
        with patch('car_space_checker.ring.download_video'), patch('car_space_checker.ring.extract_samples',return_value=[(1028,b'one'),(1033,b'two'),(1038,b'three')]):
            capture.step()
        service.ingest_recording.assert_not_called()
        self.assertEqual(capture.latest_frame(),b'three')
        self.assertEqual(capture.status()['captured_at'],1038)
        self.assertNotIn('video_url',capture.status())
        self.assertNotIn('secret',str(capture.status()))

    def test_live_recording_submits_original_capture_timestamps(self):
        from unittest.mock import patch
        capture,service,client=self.capture(live=True)
        with patch('car_space_checker.ring.download_video'), patch('car_space_checker.ring.extract_samples',return_value=[(1028,b'one'),(1033,b'two'),(1038,b'three')]):
            capture.step()
        service.ingest_recording.assert_called_once_with([(1028,b'one'),(1033,b'two'),(1038,b'three')],'11')

    def test_new_motion_during_download_prevents_publishing_older_clear_video(self):
        from datetime import datetime,timezone
        from unittest.mock import patch
        capture,service,client=self.capture(live=True)
        after=snapshot('11',1020);after['motion_at']=datetime.fromtimestamp(1040,timezone.utc).isoformat()
        client.snapshot.side_effect=[snapshot('11',1020),after]
        with patch('car_space_checker.ring.download_video'), patch('car_space_checker.ring.extract_samples',return_value=[(1028,b'one'),(1033,b'two'),(1038,b'three')]):
            capture.step()
        service.ingest_recording.assert_not_called()
        service.invalidate.assert_called_once()

    def test_changed_recording_during_download_is_discarded(self):
        from unittest.mock import patch
        capture,service,client=self.capture(live=True)
        client.snapshot.side_effect=[snapshot('11',1020),snapshot('12',1040)]
        with patch('car_space_checker.ring.download_video'), patch('car_space_checker.ring.extract_samples',return_value=[(1028,b'one'),(1033,b'two'),(1038,b'three')]):
            capture.step()
        service.ingest_recording.assert_not_called()
        self.assertIsNone(capture.latest_frame())

    def test_mismatched_device_does_not_refresh_or_download(self):
        from unittest.mock import patch
        capture,service,client=self.capture(live=True)
        bad=snapshot('11',1020);bad['device_ids'][0]='doorbell';client.snapshot.return_value=bad
        with patch('car_space_checker.ring.download_video') as download:
            with self.assertRaises(CaptureError):capture.step()
        client.refresh.assert_not_called();download.assert_not_called()


class HAClientTests(unittest.TestCase):
    def test_invalid_entity_cannot_inject_template(self):
        from car_space_checker.ring import HAClient
        for value in ["camera.bad'); evil('x",'sensor.bad','',None]:
            with self.assertRaises(CaptureError): HAClient(value,'sensor.test','event.test')

    def test_api_error_does_not_expose_token_or_url(self):
        from car_space_checker.ring import HAClient
        from unittest.mock import patch
        import os
        client=HAClient('camera.test','sensor.test','event.test')
        with patch.dict(os.environ,{'SUPERVISOR_TOKEN':'never-expose'}), patch('car_space_checker.ring.urlopen',side_effect=RuntimeError('never-expose signed-url')):
            with self.assertRaises(CaptureError) as error: client.snapshot()
        self.assertNotIn('never-expose',str(error.exception))
        self.assertNotIn('signed-url',str(error.exception))

    def test_download_caps_bytes_and_does_not_forward_supervisor_token(self):
        import io,os
        from unittest.mock import Mock,patch
        from car_space_checker.ring import download_video
        opener=Mock();opener.open.return_value=io.BytesIO(b'video-too-large')
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'SUPERVISOR_TOKEN':'never-send'}), patch('car_space_checker.ring.build_opener',return_value=opener), patch('car_space_checker.ring.MAX_VIDEO_BYTES',4):
            with self.assertRaises(CaptureError): download_video('https://ring.com/test',Path(directory)/'video')
        request=opener.open.call_args.args[0]
        self.assertNotIn('Authorization',request.headers)

    def test_redirect_to_local_host_is_rejected(self):
        from car_space_checker.ring import SafeRedirect
        from urllib.request import Request
        with self.assertRaises(CaptureError):
            SafeRedirect().redirect_request(Request('https://ring.com/video'),None,302,'redirect',{},'http://127.0.0.1/token')

    def test_slow_trickle_cannot_hold_the_worker_past_download_deadline(self):
        import threading,time,urllib.request
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from unittest.mock import Mock,patch
        from types import SimpleNamespace
        from car_space_checker.ring import download_video
        class SlowHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Length','40');self.end_headers()
                try:
                    for _ in range(40):
                        self.wfile.write(b'x');self.wfile.flush();time.sleep(.05)
                except (BrokenPipeError,ConnectionResetError):pass
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),SlowHandler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        response=urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}',timeout=2)
        opener=Mock();opener.open.return_value=response
        # Accelerate only the adapter's clock: 60 seconds becomes 0.6 seconds.
        clock=SimpleNamespace(monotonic=lambda:time.monotonic()*100)
        started=time.monotonic()
        with tempfile.TemporaryDirectory() as directory, patch('car_space_checker.ring.build_opener',return_value=opener), patch('car_space_checker.ring.time',clock):
            with self.assertRaises(CaptureError):download_video('https://ring.com/video',Path(directory)/'clip')
        self.assertLess(time.monotonic()-started,1.5)
