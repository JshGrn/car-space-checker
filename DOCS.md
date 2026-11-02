# Install on Home Assistant OS

This is an experimental add-on (called an app in newer Home Assistant versions), not a HACS integration. Version 0.2.0 connects configured Ring recordings to local image processing. Enable capture in add-on Configuration and calibrate the parking zone before publishing availability.

## Install

1. Start the official Mosquitto broker add-on and configure the MQTT integration in Home Assistant.
2. Open **Settings → Add-ons → Add-on store → ⋮ → Repositories** (newer versions: **Settings → Apps → Install app**).
3. Add `https://github.com/JshGrn/car-space-checker`.
4. Find **Car Space Checker** and select **Install**. The image builds on your HAOS machine. Supported architectures: amd64 and aarch64; 32-bit machines are not supported.
5. Start it. First startup downloads the checksum-verified YOLOX-S model; allow time for the download.
6. Select **Open Web UI**. Upload a floodlight photo and mark the zone, reference car length, charging rear range and preferred position. Leave live publishing disabled until the capture connection and calibration have been validated.
7. Under the MQTT integration, find the **Car Space Checker** device and its **Parking space available** sensor. It stays unavailable until fresh live observations arrive. The actual entity ID can differ if the name already exists.

[Add repository](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FJshGrn%2Fcar-space-checker)

## Ring prerequisite

Add **Ring** through **Settings → Devices & services → Add integration**. Enter Ring credentials and verification code in Home Assistant only. Open the Floodlight device, show disabled entities, and enable **Last recording** camera and timestamp sensor if offered. Retain the motion event entity. Enter these entity IDs in the add-on Configuration tab; never use the Doorbell image as a substitute.

A subscription is required for recordings. Camera snapshots may be cached. The adapter must derive frame age from recording metadata rather than assume the download time is the capture time. See [Ring documentation](https://www.home-assistant.io/integrations/ring/).

## Connect recordings

In add-on **Configuration**, set `recording_camera` to the Floodlight Last recording camera, `recording_timestamp` to its timestamp sensor, and `motion_event` to its motion event. Turn on `ring_enabled`, save and restart the add-on. All three entities must belong to the same Ring device. No Ring password or HA token is entered here.

Open Web UI and check the capture message. The adapter skips the existing recording on startup and waits for a new recording whose ID and timestamp have both changed and settled. Trigger new motion after startup, then allow Ring to finish uploading it. **Load latest recording frame** displays the last received frame for calibration; its capture time is shown alongside the status. An old displayed preview does not imply a currently free space.

The adapter samples three frames spanning ten seconds near the end of a 12–180 second recording. Live observations must still be younger than 120 seconds when processed. If Ring is too slow, the sensor remains unknown/unavailable. A new motion event invalidates previous availability while waiting for the next recording. Download failures or missing metadata discard confirmation and establish a new baseline on reconnection.

After validating the marks with a parked-car reference, save the setup with **Enable live observations** checked. New recordings then update the MQTT sensor. Notifications remain a separate Home Assistant automation; see `examples/home-assistant.yaml`.

The URL and timestamp come from separate HA entities. Advancing and settling both values guards common update races, but this is a correlation rather than a direct Ring history ID/timestamp lookup. Validate timing on the target installation before relying on it. Source files are downloaded into temporary storage and removed after analysis; only the latest preview frame remains in process memory.

## Settings, storage and access

- `instance_id` defaults to `parking_poc`; keep it stable to preserve the MQTT device identity. Use a different ID if running another checker against the same broker.
- MQTT credentials come from Supervisor's MQTT service. They are not entered into the repository or printed to logs.
- The setup UI is served through authenticated Home Assistant ingress only; the add-on opens no host port. Direct container requests are rejected unless they originate from Supervisor.
- Calibration lives in `/data/data/zone.json`, the model in `/data/models/`, and the generated ingestion token in `/data/ingestion-token`. Supervisor preserves `/data` across normal updates and includes it in add-on backups.
- Existing laptop calibration and private examples are not bundled. Recreate marks in the add-on UI for now. Public users' example gallery entries require local private examples and otherwise show unavailable.
- An upload previews the image but does not publish live availability. Any car counts as occupied; there is no vehicle identity recognition.
- The add-on requests `homeassistant_api` access for entity metadata and refresh requests. Supervisor grants administrator-level API scope; this adapter uses only its three configured entities and never sends the Supervisor token to Ring storage.

## Updates

Changes are published on `main`. Each installable release increments `version` in `config.json` and updates `CHANGELOG.md`. In the add-on store choose **Check for updates**, then update Car Space Checker. Supervisor rebuilds the container from the new source. A Git push with no version bump is not an installable update. Back up the add-on before updating; do not uninstall it to update.

## Troubleshooting

If the add-on reports MQTT service unavailable, confirm the official Mosquitto add-on is running and registered with Supervisor. This package currently requires the Supervisor-advertised MQTT service.

If startup fails during model download, check internet access to GitHub and available storage, then restart. If installation fails, send the relevant build error without credentials. The amd64/aarch64 images can build locally; end-to-end HAOS installation still needs validation on the target machine.

If the UI opens but the sensor is unavailable, check the capture status, saved calibration, live checkbox and footage age. Never treat unavailable or unknown as a free space.
