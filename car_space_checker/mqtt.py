"""Home Assistant MQTT discovery with expiry tied to the observation age."""
import json
import os
import re
import paho.mqtt.client as mqtt

def messages_for(instance, state, now, max_age):
    prefix = f'car_space_checker/{instance}'
    capture = state.get('observed_at')
    remaining = int(max_age - max(0, now-capture)) if capture is not None else 0
    if remaining <= 0 or state['state'] == 'unavailable':
        return [(f'{prefix}/availability','offline',True)]
    payload = {**state, 'expires_at': capture + max_age}
    config = discovery_config(instance, remaining)
    return [(f'homeassistant/binary_sensor/{instance}/space_available/config',json.dumps(config),True),
            (f'{prefix}/state',json.dumps(payload,allow_nan=False),False),
            (f'{prefix}/availability','online',True)]

def discovery_config(instance, expiry=120):
    prefix = f'car_space_checker/{instance}'
    return {
        'name':'Parking space available','unique_id':f'{instance}_space_available',
        'default_entity_id':'binary_sensor.parking_space_available',
        'state_topic':f'{prefix}/state','availability_topic':f'{prefix}/availability',
        'value_template':"{{ {'available': 'ON', 'occupied': 'OFF'}.get(value_json.state, 'None') if as_timestamp(now()) < value_json.expires_at else 'None' }}",
        'json_attributes_topic':f'{prefix}/state','expire_after':expiry,
        'icon':'mdi:car-parking',
        'device':{'identifiers':[instance],'name':'Car Space Checker','manufacturer':'Local PoC'}
    }

class Publisher:
    def __init__(self, host=None, port=None, instance=None):
        self.instance = instance or os.getenv('CHECKER_ID','parking_poc')
        if not re.fullmatch(r'[a-z0-9_]{1,64}',self.instance):
            raise ValueError('CHECKER_ID must use lowercase letters, numbers and underscores.')
        self.connected = False
        self.prefix = f'car_space_checker/{self.instance}'
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=self.instance)
        self.client.will_set(f'{self.prefix}/availability','offline',qos=1,retain=True)
        if os.getenv('MQTT_USERNAME'):
            self.client.username_pw_set(os.environ['MQTT_USERNAME'],os.getenv('MQTT_PASSWORD'))
        if os.getenv('MQTT_TLS','false').lower() == 'true':
            self.client.tls_set()
        self.client.on_connect = self._connected
        self.client.on_disconnect = self._disconnected
        self.client.reconnect_delay_set(1,30)
        self.client.connect_async(host or os.environ['MQTT_HOST'],port or int(os.getenv('MQTT_PORT','1883')),keepalive=30)
        self.client.loop_start()

    def _connected(self, client, userdata, flags, reason_code, properties):
        self.connected = not reason_code.is_failure
        if self.connected:
            # Reconnection never resurrects a previously observed clear space.
            client.publish(f'{self.prefix}/availability','offline',qos=1,retain=True)
            client.publish(f'{self.prefix}/state',b'',qos=1,retain=True)
            client.publish(f'homeassistant/binary_sensor/{self.instance}/space_available/config',
                           json.dumps(discovery_config(self.instance)),qos=1,retain=True)

    def _disconnected(self, client, userdata, flags, reason_code, properties):
        self.connected = False

    def publish(self, state, now, max_age):
        if self.connected:
            for topic,payload,retain in messages_for(self.instance,state,now,max_age):
                # QoS 0 evidence is never replayed by Paho after reconnect.
                self.client.publish(topic,payload,qos=0,retain=retain)

    def close(self):
        if self.connected:
            self.client.publish(f'{self.prefix}/availability','offline',qos=1,retain=True).wait_for_publish(timeout=2)
        self.client.disconnect()
        self.client.loop_stop()
