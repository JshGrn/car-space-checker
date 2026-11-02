import io
import tempfile
import unittest
from PIL import Image
import numpy as np
from car_space_checker.service import Service, validate_settings
from car_space_checker.parking import Detection

CONFIG = {'camera_id':'floodlight', 'zone':[[.1,.1],[.9,.1],[.9,.9],[.1,.9]], 'aspect_ratio':1, 'mode':'gap', 'live_enabled':True, 'reference':[[.1,.5],[.4,.5]], 'clearance':.2, 'reference_kind':'parked_car', 'charging':{'rear_range':[[.5,.5],[.9,.5]],'preferred':[.7,.5]}}

def photo(seed=0):
    image = Image.fromarray(np.random.default_rng(seed).integers(30,200,(100,100,3),dtype=np.uint8))
    stream=io.BytesIO(); image.save(stream,format='PNG'); return stream.getvalue()

class FixedDetector:
    def detect(self, image):
        return []

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = Service(self.temp.name, detector=FixedDetector(), clock=lambda:1010)
        self.service.configure(CONFIG)

    def test_preview_does_not_publish_or_change_live_state(self):
        result=self.service.preview(photo(), CONFIG)
        self.assertEqual(result['assessment'], 'clear')
        self.assertEqual(self.service.status()['state'], 'unknown')
        self.assertTrue(result['preview_only'])

    def test_image_ingestion_confirms_distinct_frames(self):
        for i, timestamp in enumerate([1000,1005,1010]):
            result=self.service.ingest(photo(i),'floodlight',str(i),timestamp)
        self.assertEqual(result['state'],'available')

    def test_same_pixels_with_different_ids_cannot_confirm(self):
        for i, timestamp in enumerate([1000,1005,1010]):
            result=self.service.ingest(photo(),'floodlight',str(i),timestamp)
        self.assertEqual(result['state'],'unknown')
        self.assertEqual(result['clear_count'],1)

    def test_wrong_camera_or_aspect_ratio_rejected(self):
        with self.assertRaises(ValueError): self.service.ingest(photo(),'other_camera','one',1000)
        with self.assertRaises(ValueError): self.service.preview(photo(), {**CONFIG,'aspect_ratio':1.7})

    def test_configuration_change_clears_live_confirmation(self):
        for i, timestamp in enumerate([1000,1005,1010]): self.service.ingest(photo(i),'floodlight',str(i),timestamp)
        self.service.configure(CONFIG)
        self.assertEqual(self.service.status()['state'],'unknown')

    def test_live_ingestion_requires_explicit_enable_and_saved_zone(self):
        self.service.configure({**CONFIG,'live_enabled':False})
        with self.assertRaises(ValueError): self.service.ingest(photo(),'floodlight','one',1000)

    def test_invalid_config_and_nan_values_rejected(self):
        for change in [{'aspect_ratio':float('nan')},{'camera_id':'../x'},{'mode':'arbitrary'},{'live_enabled':'false'}]:
            with self.subTest(change=change), self.assertRaises(ValueError): validate_settings({**CONFIG,**change})

    def test_failed_analysis_removes_previously_available_state(self):
        for i, timestamp in enumerate([1000,1005,1010]): self.service.ingest(photo(i),'floodlight',str(i),timestamp)
        with self.assertRaises(ValueError): self.service.ingest(b'broken','floodlight','bad',1011)
        self.assertEqual(self.service.status()['state'],'unknown')

class RecordingBatchTests(unittest.TestCase):
    def test_only_final_recording_state_is_published(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            publisher=Mock()
            service=Service(directory,detector=FixedDetector(),publisher=publisher,clock=lambda:1020)
            service.configure(CONFIG)
            publisher.reset_mock()
            frames=[(1000,photo()),(1005,photo()),(1010,photo()),(1015,photo())]
            # Isolate temporal batching from the vision model; test the production tracker/publisher.
            assessments=iter(['clear','clear','clear','occupied'])
            service._assess=lambda image,settings: ({'assessment':next(assessments)},None,[])
            # Give each frame distinct pixels, as real compressed video frames normally have.
            from PIL import Image
            import io
            frames=[]
            for i in range(4):
                data=io.BytesIO();Image.new('RGB',(100,100),(80+i,80,80)).save(data,format='PNG')
                frames.append((1000+5*i,data.getvalue()))
            service.ingest_recording(frames,'recording-1')
            self.assertEqual(publisher.publish.call_count,1)
            self.assertEqual(publisher.publish.call_args.args[0]['state'],'occupied')

    def test_rejected_final_frame_cannot_publish_intermediate_availability(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            publisher=Mock();service=Service(directory,detector=FixedDetector(),publisher=publisher,clock=lambda:1020)
            service.configure(CONFIG)
            assessments=iter(['occupied','clear','clear','clear','occupied'])
            service._assess=lambda image,settings: ({'assessment':next(assessments)},None,[])
            service.ingest(photo(9),'floodlight','old-occupied',990)
            service.ingest(photo(1),'floodlight','old-clear',1000)
            publisher.reset_mock()
            service.ingest_recording([(1005,photo(2)),(1010,photo(3)),(1015,photo(9))],'recording-1')
            self.assertEqual(publisher.publish.call_count,1)
            self.assertNotEqual(publisher.publish.call_args.args[0]['state'],'available')
