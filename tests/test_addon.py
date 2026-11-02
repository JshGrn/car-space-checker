import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from car_space_checker import addon

class AddonTests(unittest.TestCase):
    def test_supervisor_service_credentials_stay_in_environment(self):
        details={'host':'core-mosquitto','port':1883,'username':'addons','password':'private','ssl':False}
        with patch.dict(os.environ,{'SUPERVISOR_TOKEN':'test'},clear=True):
            with patch.object(addon,'supervisor_get',return_value=details):
                addon.configure_mqtt()
            self.assertEqual(os.environ['MQTT_HOST'],'core-mosquitto')
            self.assertEqual(os.environ['MQTT_PASSWORD'],'private')
            self.assertEqual(os.environ['MQTT_TLS'],'false')

    def test_missing_service_fails_without_guessing_credentials(self):
        with patch.object(addon,'supervisor_get',return_value={}):
            with self.assertRaisesRegex(ValueError,'MQTT service'):
                addon.configure_mqtt()

    def test_startup_reuses_private_token_and_persistent_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.dict(os.environ,{},clear=True):
                addon.configure_storage(root)
                first=os.environ['CHECKER_TOKEN']
                addon.configure_storage(root)
                self.assertEqual(first,os.environ['CHECKER_TOKEN'])
                self.assertGreater(len(first),32)
                self.assertEqual((root/'ingestion-token').stat().st_mode & 0o777,0o600)
                self.assertEqual(os.environ['CHECKER_INGRESS'],'true')
