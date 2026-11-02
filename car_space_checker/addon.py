"""HAOS startup; credentials are obtained internally and never logged."""
import json
import logging
import os
from pathlib import Path
import secrets
import time
from urllib.request import Request, urlopen


def supervisor_get(path):
    token = os.environ.get('SUPERVISOR_TOKEN')
    if not token:
        raise ValueError('Supervisor token is missing.')
    request = Request('http://supervisor/' + path, headers={'Authorization': 'Bearer ' + token})
    with urlopen(request, timeout=15) as response:
        result = json.load(response)
    if result.get('result') != 'ok' or not isinstance(result.get('data'), dict):
        raise ValueError('Supervisor service request failed.')
    return result['data']


def configure_mqtt():
    service = supervisor_get('services/mqtt')
    if not isinstance(service.get('host'), str) or not service['host']:
        raise ValueError('MQTT service is unavailable. Start the Mosquitto add-on first.')
    port = int(service.get('port', 1883))
    if not 1 <= port <= 65535:
        raise ValueError('MQTT service has an invalid port.')
    os.environ.update({
        'MQTT_HOST': service['host'], 'MQTT_PORT': str(port),
        'MQTT_USERNAME': service.get('username', ''),
        'MQTT_PASSWORD': service.get('password', ''),
        'MQTT_TLS': 'true' if service.get('ssl', False) else 'false',
    })


def configure_storage(root):
    root.mkdir(parents=True, exist_ok=True)
    token_path = root / 'ingestion-token'
    if not token_path.exists():
        with open(token_path, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as handle:
            handle.write(secrets.token_urlsafe(32))
    token_path.chmod(0o600)
    os.environ['CHECKER_TOKEN'] = token_path.read_text().strip()
    os.environ['CHECKER_INGRESS'] = 'true'


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    root = Path('/data')
    configure_storage(root)
    # Existing relative paths now live under Supervisor's persistent volume.
    os.chdir(root)
    options_path = root / 'options.json'
    options = json.loads(options_path.read_text()) if options_path.exists() else {}
    os.environ['CHECKER_ID'] = options.get('instance_id', 'parking_poc')
    for attempt in range(12):
        try:
            configure_mqtt()
            break
        except Exception:
            logging.warning('MQTT service not ready; waiting for Mosquitto (%s/12).', attempt + 1)
            if attempt == 11:
                raise SystemExit('Cannot discover MQTT. Check the Mosquitto and Supervisor logs.') from None
            time.sleep(5)
    from .vision import MODEL_PATH, fetch_model
    if not MODEL_PATH.exists():
        logging.info('Downloading the verified YOLOX model on first start.')
        fetch_model()
    from .http import serve
    from .service import Service
    from .mqtt import Publisher
    serve(Service(publisher=Publisher()), os.environ['CHECKER_TOKEN'], ingress=True)


if __name__ == '__main__':
    main()
