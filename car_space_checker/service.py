"""Application boundary: previews are isolated from live observations."""
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time
from .geometry import Calibration, assess_gap, charging_bounds
from .parking import Zone, classify, Tracker
from .vision import Detector, read_image, quality_ok, annotated_image, MODEL_PATH

def validate_settings(settings):
    if not isinstance(settings, dict):
        raise ValueError('Settings must be an object.')
    camera = settings.get('camera_id', '')
    if camera != 'floodlight':
        raise ValueError('This PoC accepts images from the floodlight camera only.')
    zone = Zone(settings.get('zone'))
    ratio = settings.get('aspect_ratio')
    if not isinstance(ratio,(int,float)) or not math.isfinite(ratio) or not .2 <= ratio <= 5:
        raise ValueError('Load a camera image to establish its aspect ratio.')
    mode = settings.get('mode', 'whole_zone')
    if mode not in {'whole_zone','gap'}:
        raise ValueError('Unknown assessment mode.')
    enabled = settings.get('live_enabled',False)
    if not isinstance(enabled,bool):
        raise ValueError('Live enabled must be true or false.')
    result = {'camera_id':camera,'zone':zone.points,'aspect_ratio':ratio,'mode':mode,'live_enabled':enabled}
    kind = settings.get('reference_kind','known_fit')
    if kind not in {'known_fit','parked_car'}:
        raise ValueError('Unknown reference type.')
    result['reference_kind'] = kind
    if mode == 'gap':
        for key in ['reference','clearance']:
            result[key] = settings.get(key)
        calibration = Calibration(zone.points,result['reference'],result['clearance'])
        charging = settings.get('charging')
        if charging is not None:
            charging_bounds(calibration, charging)
            result['charging'] = {'rear_range':charging['rear_range'], 'preferred':charging.get('preferred')}
    if enabled and (mode != 'gap' or kind != 'parked_car' or not result.get('charging')):
        raise ValueError('Live charging checks need a parked-car length reference and marked rear charging limits.')
    return result

class Service:
    def __init__(self, data_dir='data', detector=None, publisher=None, clock=time.time):
        self.directory = Path(data_dir)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.config_path = self.directory / 'zone.json'
        self.settings = validate_settings(json.loads(self.config_path.read_text())) if self.config_path.exists() else None
        self.detector = detector or Detector()
        self.publisher = publisher
        self.clock = clock
        self.tracker = Tracker()
        self.lock = threading.RLock()
        self.last_published_state = None
        self.capture = None

    def configure(self, settings):
        settings = validate_settings(settings)
        with self.lock:
            temporary = self.config_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(settings,indent=2,allow_nan=False)+'\n')
            temporary.replace(self.config_path)
            self.settings = settings
            self.tracker = Tracker()
            self._publish(self.tracker.snapshot(self.clock()))
        return settings

    def _assess(self, image, settings):
        if abs((image.width/image.height)/settings['aspect_ratio']-1) > .02:
            raise ValueError('Image proportions differ from the calibrated camera. Use the original camera view.')
        zone = Zone(settings['zone'])
        if not quality_ok(image,zone):
            return {'assessment':'uncertain','reason':'The zone is too dark, washed out or featureless to assess.','detections':[]},zone,[]
        detections = self.detector.detect(image)
        if settings['mode'] == 'gap':
            calibration = Calibration(zone.points,settings['reference'],settings['clearance'])
            result = assess_gap(zone,calibration,detections,settings.get('charging'))
            result['reason'] = ('Experimental ground-plane estimate; validate against parked-car examples. ' + ('Cable limits checked; rear location is approximate.' if settings.get('charging') else 'Cable reach has not been checked.'))
        else:
            result = {'assessment':classify(zone,detections),'method':'whole_zone','reason':'Checks the full marked footprint; does not measure smaller gaps.'}
        result['detections'] = [asdict(item) for item in detections]
        return result,zone,detections

    def preview(self, content, settings):
        settings = validate_settings(settings)
        image = read_image(content)
        with self.lock:
            result,zone,detections = self._assess(image,settings)
        return {**result,'preview_only':True,'image':annotated_image(image,zone,detections)}

    def ingest(self, content, camera_id, observation_id, observed_at, publish=True):
        with self.lock:
            if not self.settings or not self.settings['live_enabled']:
                raise ValueError('Save a zone and enable live observations before submitting footage.')
            if camera_id != self.settings['camera_id']:
                raise ValueError('This observation belongs to a different camera.')
            if not isinstance(observation_id,str) or not 1 <= len(observation_id) <= 200:
                raise ValueError('A bounded source observation ID is required.')
            if not isinstance(observed_at,(int,float)) or not math.isfinite(observed_at):
                raise ValueError('A finite capture timestamp is required.')
            try:
                image = read_image(content)
                result,_,_ = self._assess(image,self.settings)
                digest = hashlib.sha256(image.tobytes()).hexdigest()
                state = self.tracker.observe(result['assessment'],observation_id,digest,observed_at,self.clock())
            except Exception:
                self.tracker.invalidate('Image processing failed; waiting for fresh evidence.')
                self._publish(self.tracker.snapshot(self.clock()))
                raise
            if state['accepted'] and publish:
                self._publish(state)
            return {**state,'assessment':result['assessment'],'gap_car_lengths':result.get('gap_car_lengths')}

    def invalidate(self, reason):
        with self.lock:
            self.tracker.invalidate(reason)
            self._publish(self.tracker.snapshot(self.clock()))

    def ingest_recording(self, samples, recording_id):
        # Intermediate clear frames must not notify before the final frame is checked.
        with self.lock:
            last = None
            for observed_at, content in samples:
                last = self.ingest(content, 'floodlight', f'{recording_id}:{observed_at:.3f}', observed_at, publish=False)
            if last is None or not last['accepted']:
                self.tracker.invalidate('Final recording frame was rejected; waiting for fresh evidence.')
            state = self.tracker.snapshot(self.clock())
            self._publish(state)
            return state

    def _publish(self, state):
        if self.publisher:
            self.publisher.publish(state,self.clock(),self.tracker.max_age)
        self.last_published_state = state['state']

    def tick(self):
        with self.lock:
            state = self.tracker.snapshot(self.clock())
            if state['state'] != self.last_published_state:
                self._publish(state)

    def status(self):
        with self.lock:
            return {**self.tracker.snapshot(self.clock()),'settings':self.settings,
                    'mqtt_connected':bool(self.publisher and self.publisher.connected),
                    'model_ready':MODEL_PATH.exists(),
                    'capture':self.capture.status() if self.capture else None}
