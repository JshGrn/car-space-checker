"""Ring recordings through HAOS; download time is never capture time."""
from dataclasses import dataclass
from datetime import datetime
import json
import logging
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener, urlopen

MAX_VIDEO_BYTES = 100_000_000
MAX_DURATION = 180
MAX_AGE = 120


class CaptureError(ValueError):
    """A safe user-facing error without credentials or signed media URLs."""


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError
        result = parsed.timestamp()
        if not math.isfinite(result):
            raise ValueError
        return result
    except (ValueError, TypeError, OverflowError):
        raise CaptureError('Waiting for a valid recording timestamp from Home Assistant.') from None


def validate_video_url(url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        allowed = any(host == domain or host.endswith('.' + domain)
                      for domain in ('ring.com', 'amazonaws.com', 'cloudfront.net'))
        if (parsed.scheme != 'https' or not allowed or parsed.username or parsed.password
                or parsed.port not in (None, 443)):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise CaptureError('Recording URL is not a supported HTTPS Ring storage address.') from None


@dataclass(frozen=True)
class Recording:
    recording_id: str
    started_at: float
    url: str

    @property
    def key(self):
        return self.recording_id, self.started_at


def parse_recording(data, now):
    devices = data.get('device_ids', [])
    if len(devices) != 3 or not all(devices) or len(set(devices)) != 1 or data.get('ring') is not True:
        raise CaptureError('Camera, timestamp and motion must belong to the same Ring device. Check the entity settings.')
    if data.get('camera_state') in ('unknown', 'unavailable', None):
        raise CaptureError('The recording camera is unavailable in Home Assistant.')
    recording_id = str(data.get('recording_id') or '')
    if not re.fullmatch(r'[0-9]{1,40}', recording_id):
        raise CaptureError('Waiting for the Ring camera recording ID.')
    started_at = timestamp(data.get('started_at'))
    if started_at > now + 5:
        raise CaptureError('Recording timestamp is in the future. Check device clocks.')
    url = data.get('video_url')
    validate_video_url(url)
    return Recording(recording_id, started_at, url)


class RecordingGate:
    """Require both independently updated HA values to advance and settle."""
    def __init__(self):
        self.baseline = None
        self.candidate = None
        self.candidate_since = None

    def consider(self, data, now):
        recording = parse_recording(data, now)
        if self.baseline is None:
            self.complete(recording)
            return None
        if recording.recording_id == self.baseline.recording_id or recording.started_at <= self.baseline.started_at:
            self.candidate = None
            return None
        if self.candidate != recording.key:
            self.candidate = recording.key
            self.candidate_since = now
            return None
        return recording if now - self.candidate_since >= 3 else None

    def complete(self, recording):
        self.baseline = recording
        self.candidate = None


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_video_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_video(url, target):
    validate_video_url(url)
    deadline = time.monotonic() + 60
    try:
        # This separate opener never receives the Supervisor Authorization header.
        with build_opener(SafeRedirect()).open(Request(url), timeout=15) as response, target.open('wb') as output:
            size = 0
            while chunk := response.read1(1024 * 1024):
                size += len(chunk)
                if size > MAX_VIDEO_BYTES or time.monotonic() > deadline:
                    raise CaptureError('Recording download exceeded the size or time limit.')
                output.write(chunk)
    except CaptureError:
        raise
    except Exception:
        raise CaptureError('Recording download failed. Waiting for a new recording.') from None


def extract_samples(video, started_at, now):
    from .__main__ import extract_frame
    try:
        result = subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file,pipe',
                                 '-show_entries','format=duration,start_time','-of','json',str(video)],
                                check=True,capture_output=True,timeout=15)
        metadata = json.loads(result.stdout)['format']
        duration = float(metadata['duration'])
        start = float(metadata.get('start_time', 0))
        if not math.isfinite(duration) or not 12 <= duration <= MAX_DURATION or not math.isfinite(start) or abs(start) > .1:
            raise CaptureError('Recording timing is unsupported (requires a 12–180 second clip starting at zero).')
        offsets = [round(duration - delta, 3) for delta in (12, 7, 2)]
        if started_at + duration > now + 5:
            raise CaptureError('Recording end time is in the future. Check device clocks.')
        if now - (started_at + offsets[-1]) >= MAX_AGE:
            raise CaptureError('Latest recording is too old for live parking detection.')
        samples = []
        with tempfile.TemporaryDirectory() as directory:
            for index, offset in enumerate(offsets):
                frame = Path(directory) / f'{index}.jpg'
                extract_frame(video,offset,frame)
                samples.append((started_at + offset, frame.read_bytes()))
        return samples
    except CaptureError:
        raise
    except Exception:
        raise CaptureError('Could not extract usable frames from the recording.') from None


class HAClient:
    def __init__(self, camera, sensor, motion):
        for entity, domain in [(camera,'camera'),(sensor,'sensor'),(motion,'event')]:
            if not re.fullmatch(domain + r'\.[a-z0-9_]+', entity or ''):
                raise CaptureError('Set the recording camera, timestamp sensor and motion event in add-on Configuration.')
        self.entities = (camera, sensor, motion)
        # Entity IDs are restricted above, so they cannot inject template expressions.
        self.template = ("{{ {'device_ids': [device_id('" + camera + "'), device_id('" + sensor
            + "'), device_id('" + motion + "')], 'ring': "
            + ' and '.join("'" + item + "' in integration_entities('ring')" for item in self.entities)
            + ", 'camera_state': states('" + camera + "'), 'recording_id': state_attr('" + camera
            + "', 'last_video_id'), 'video_url': state_attr('" + camera + "', 'video_url'), 'started_at': states('"
            + sensor + "'), 'motion_at': states('" + motion + "')} | tojson }}")

    def request(self, path, payload):
        token = os.environ.get('SUPERVISOR_TOKEN', '')
        if not token:
            raise CaptureError('Home Assistant access is only configured inside the HAOS add-on.')
        request = Request('http://supervisor/core/api/' + path, data=json.dumps(payload).encode(),
                          headers={'Authorization':'Bearer ' + token, 'Content-Type':'application/json'})
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read(1_000_000))
        except Exception:
            raise CaptureError('Cannot read Home Assistant. Check entity IDs and restart the updated add-on.') from None

    def snapshot(self):
        return self.request('template', {'template':self.template})

    def refresh(self):
        self.request('services/homeassistant/update_entity', {'entity_id':list(self.entities[:2])})


class RingCapture:
    def __init__(self, service, options, client=None, clock=time.time):
        self.service = service
        self.enabled = options.get('ring_enabled', False)
        self.client = client
        self.clock = clock
        self.gate = RecordingGate()
        self.last_motion = None
        self.last_refresh = 0
        self.stop = threading.Event()
        self.thread = None
        self.lock = threading.Lock()
        self.frame = None
        self.state = {'enabled':self.enabled,'message':'Ring capture is disabled in add-on Configuration.','frame_available':False}
        if self.enabled and client is None:
            try:
                self.client = HAClient(options.get('recording_camera'), options.get('recording_timestamp'), options.get('motion_event'))
                self.update('Connecting to the configured Ring entities.')
            except CaptureError as error:
                self.update(str(error))

    def update(self, message, **details):
        with self.lock:
            self.state = {**self.state,'message':message,**details}

    def status(self):
        with self.lock:
            return dict(self.state)

    def latest_frame(self):
        with self.lock:
            return self.frame

    def step(self):
        data = self.client.snapshot()
        now = self.clock()
        # Validate device ownership before requesting any entity refresh.
        recording = self.gate.consider(data, now)
        motion = data.get('motion_at')
        try:
            motion_at = timestamp(motion)
        except CaptureError:
            motion_at = None
        if motion_at is not None and -5 <= now - motion_at <= 180:
            if motion != self.last_motion:
                self.last_motion = motion
                self.service.invalidate('New floodlight motion; waiting for a fresh recording.')
            if now - self.last_refresh >= 30:
                self.client.refresh()
                self.last_refresh = now
        if recording is None:
            self.update('Connected to Ring entities. Waiting for a new, settled recording.')
            return
        if now - recording.started_at >= MAX_DURATION + MAX_AGE:
            self.gate.complete(recording)
            self.update('Latest recording is too old for live detection. Waiting for new motion.')
            return
        self.update('Downloading and checking a new recording.')
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / 'recording.mp4'
            download_video(recording.url, video)
            samples = extract_samples(video, recording.started_at, self.clock())
            after_data = self.client.snapshot()
            after = parse_recording(after_data, self.clock())
            if after.key != recording.key:
                self.update('Recording changed during download; waiting for settled metadata.')
                return
            with self.lock:
                self.frame = samples[-1][1]
                self.state = {**self.state,'frame_available':True,'captured_at':samples[-1][0]}
            try:
                latest_motion = timestamp(after_data.get('motion_at'))
            except CaptureError:
                latest_motion = None
            if latest_motion is not None and latest_motion > samples[-1][0]:
                self.service.invalidate('Newer motion exists; waiting for its recording.')
                self.update('Newer motion exists; waiting for its recording.')
            else:
                settings = self.service.status()['settings']
                if settings and settings['live_enabled']:
                    self.service.ingest_recording(samples, recording.recording_id)
                    self.update('Recording processed. Live state uses the frame capture time.', processed_at=self.clock())
                else:
                    self.update('Fresh recording received. Calibrate the zone and enable live observations to publish.', processed_at=self.clock())
            self.gate.complete(recording)

    def run(self):
        previous_error = None
        while not self.stop.is_set():
            try:
                self.step()
                previous_error = None
            except Exception as error:
                # Raw HTTP/subprocess errors may contain signed URLs: never log them.
                message = str(error) if isinstance(error, CaptureError) else 'Ring capture failed; waiting for a new recording.'
                self.update(message)
                self.service.invalidate(message)
                self.gate = RecordingGate()
                if message != previous_error:
                    logging.warning('Ring capture: %s', message)
                previous_error = message
            self.stop.wait(5)

    def start(self):
        if self.enabled and self.client:
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)
