import json
import unittest
from car_space_checker.mqtt import messages_for

class MqttTests(unittest.TestCase):
    def test_capture_age_reduces_expiry_and_state_is_never_retained(self):
        messages=messages_for('parking_poc', {'state':'available','observed_at':1000,'reason':'clear','clear_count':3}, now=1100, max_age=120)
        config=json.loads(next(payload for topic,payload,retain in messages if topic.startswith('homeassistant/')))
        self.assertEqual(config['expire_after'],20)
        state=next((payload,retain) for topic,payload,retain in messages if topic.endswith('/state'))
        self.assertFalse(state[1])
        self.assertEqual(json.loads(state[0])['state'],'available')
        self.assertEqual(json.loads(state[0])['expires_at'],1120)
        self.assertIn('as_timestamp(now()) < value_json.expires_at',config['value_template'])

    def test_expired_evidence_is_only_offline_never_republished_available(self):
        messages=messages_for('parking_poc', {'state':'available','observed_at':1000}, now=1121,max_age=120)
        self.assertEqual(messages,[('car_space_checker/parking_poc/availability','offline',True)])

    def test_disconnect_race_does_not_queue_evidence_for_replay(self):
        import paho.mqtt.client as mqtt
        from car_space_checker.mqtt import Publisher
        publisher=Publisher.__new__(Publisher)
        publisher.instance='test'; publisher.prefix='car_space_checker/test'
        publisher.connected=True  # Socket can fail before on_disconnect runs.
        publisher.client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        publisher.publish({'state':'available','observed_at':1000},1000,120)
        self.assertEqual(list(publisher.client._out_messages.values()),[])

    def test_connect_announces_entity_while_offline_without_evidence(self):
        from unittest.mock import Mock
        from car_space_checker.mqtt import Publisher
        publisher=Publisher.__new__(Publisher)
        publisher.instance='test'; publisher.prefix='car_space_checker/test'
        client=Mock()
        publisher._connected(client,None,None,Mock(is_failure=False),None)
        calls=client.publish.call_args_list
        config=json.loads(next(c.args[1] for c in calls if c.args[0].startswith('homeassistant/')))
        self.assertEqual(config['default_entity_id'],'binary_sensor.parking_space_available')
        self.assertTrue(any(c.args[1]=='offline' for c in calls))
        self.assertFalse(any(c.args[1]=='online' for c in calls))
