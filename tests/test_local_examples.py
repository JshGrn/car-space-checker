"""Opt-in regression check against the user's ignored local reference photographs."""
import json
import os
from pathlib import Path
import unittest
from car_space_checker.service import Service

@unittest.skipUnless(os.getenv('RUN_LOCAL_EXAMPLES')=='1','Private local examples are opt-in.')
class LocalExampleTests(unittest.TestCase):
    def test_empty_and_parked_reference_images(self):
        service=Service()
        for name,config,clear in [('floodlight-day','day-example',True),('parked-day','parked-day',False),('parked-night','parked-night',False),('parked-right','parked-right',False)]:
            with self.subTest(example=name):
                result=service.preview(Path('data/'+name+'.jpg').read_bytes(),json.loads(Path('data/'+config+'.json').read_text()))
                self.assertEqual(result['assessment']=='clear',clear)
                self.assertEqual(service.status()['state'],'unknown')
