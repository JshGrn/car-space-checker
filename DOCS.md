# Install on Home Assistant OS

This is an experimental add-on (called an app in newer Home Assistant versions), not a HACS integration. Version 0.1.0 provides calibration and MQTT discovery. **Automatic Ring recording capture is not connected yet**, so installing alone does not produce live parking availability or notifications.

## Install

1. Start the official Mosquitto broker add-on and configure the MQTT integration in Home Assistant.
2. Open **Settings → Add-ons → Add-on store → ⋮ → Repositories** (newer versions: **Settings → Apps → Install app**).
3. Add `https://github.com/JshGrn/car-space-checker`.
4. Find **Car Space Checker** and select **Install**. The image builds on your HAOS machine. Supported architectures: amd64 and aarch64; 32-bit machines are not supported.
5. Start it. First startup downloads the checksum-verified YOLOX-S model; allow time for the download.
6. Select **Open Web UI**. Upload a floodlight photo and mark the zone, reference car length, charging rear range and preferred position. Leave live publishing disabled until the capture adapter is connected and validated.
7. Under the MQTT integration, find the **Car Space Checker** device and its **Parking space available** sensor. It stays unavailable until fresh live observations arrive. The actual entity ID can differ if the name already exists.

[Add repository](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FJshGrn%2Fcar-space-checker)

## Ring prerequisite

Add **Ring** through **Settings → Devices & services → Add integration**. Enter Ring credentials and verification code in Home Assistant only. Open the Floodlight device, show disabled entities, and enable **Last recording** camera and timestamp sensor if offered. Retain the motion event entity. Record these entity IDs for the capture adapter; never use the Doorbell image as a substitute.

A subscription is required for recordings. Camera snapshots may be cached. The adapter must derive frame age from recording metadata rather than assume the download time is the capture time. See [Ring documentation](https://www.home-assistant.io/integrations/ring/).

## Settings, storage and access

- `instance_id` defaults to `parking_poc`; keep it stable to preserve the MQTT device identity. Use a different ID if running another checker against the same broker.
- MQTT credentials come from Supervisor's MQTT service. They are not entered into the repository or printed to logs.
- The setup UI is served through authenticated Home Assistant ingress only; the add-on opens no host port. Direct container requests are rejected unless they originate from Supervisor.
- Calibration lives in `/data/data/zone.json`, the model in `/data/models/`, and the generated ingestion token in `/data/ingestion-token`. Supervisor preserves `/data` across normal updates and includes it in add-on backups.
- Existing laptop calibration and private examples are not bundled. Recreate marks in the add-on UI for now. Public users' example gallery entries require local private examples and otherwise show unavailable.
- An upload previews the image but does not publish live availability. Any car counts as occupied; there is no vehicle identity recognition.
- This release does not request access to HA Core. The future recording adapter will add only the access it needs.

## Updates

Changes are published on `main`. Each installable release increments `version` in `config.json` and updates `CHANGELOG.md`. In the add-on store choose **Check for updates**, then update Car Space Checker. Supervisor rebuilds the container from the new source. A Git push with no version bump is not an installable update. Back up the add-on before updating; do not uninstall it to update.

## Troubleshooting

If the add-on reports MQTT service unavailable, confirm the official Mosquitto add-on is running and registered with Supervisor. This package currently requires the Supervisor-advertised MQTT service.

If startup fails during model download, check internet access to GitHub and available storage, then restart. If installation fails, send the relevant build error without credentials. The amd64/aarch64 images can build locally; end-to-end HAOS installation still needs validation on the target machine.

If the UI opens but the sensor is unavailable, that is expected before live footage is connected. Never treat unavailable or unknown as a free space.
