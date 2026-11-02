# Parking PoC scope and progress

## Agreed design

Python in Docker Compose alongside Home Assistant. Floodlight-only images and motion initially. Reference images establish car length; no car model, registration or identity recognition. Other presence/Bluetooth sensors can later suppress notifications independently.

Search one marked near-side kerb zone for a contiguous empty gap, including manoeuvring clearance. Both facing directions are allowed, but the hypothetical car's rear must lie within marked cable reach. Prefer a centre in front of the right-hand wall. All supplied black-car images describe valid charging placements; existing cars still obstruct those placements. Use fixed landmarks for limits, not the movable bin itself. The incorrect doorbell view is excluded.

## Completed local increment

- [x] Docker Compose environment and Python CPU inference with pinned official YOLOX-S model.
- [x] Local calibration UI, separate private camera examples, image-based scale, charging limits, orientation and preferred placement.
- [x] Preview/live isolation, timestamp freshness, duplicate rejection, confirmation and expiry.
- [x] Authenticated image ingestion and local recording-frame extraction.
- [x] MQTT discovery/publication implementation; HA automation/dashboard examples.
- [x] Regression tests, actual local image inference and browser validation.

## Remaining live integration

- [ ] Validate one consistent raw camera frame/crop and geometry against independent borderline examples.
- [ ] Obtain actual HA entities and reliable recording/capture metadata; implement motion-to-fresh-frame adapter.
- [ ] Test with the user's broker/HA, verify the dashboard sensor and notification delivery, then enable live observations.

The current local PoC does not log into Ring, fetch footage automatically, identify the user's vehicle, or modify the user's Home Assistant instance. Bounding-box footprints and a planar perspective approximation remain experimental for this wide-angle view.
