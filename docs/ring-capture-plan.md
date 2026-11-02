# Ring capture adapter

Goal: connect an HAOS-installed checker to a user-selected Ring Floodlight through add-on Configuration. Keep README bare and release notes brief.

Design: an internal Supervisor-authenticated HA client reads one coherent template snapshot for the configured camera, recording timestamp and motion event, including device registry IDs. Reject mismatched/non-Ring devices. Poll local HA state every five seconds; fresh motion requests a bounded HA entity refresh every 30 seconds while awaiting the recording. No separate Ring login.

The camera URL and timestamp update independently. Establish a baseline after startup, require both recording ID and capture timestamp to advance, then require the pair to remain stable for a second poll. Skip existing recordings at startup. Reject recordings whose newest sampled frame is expired; never timestamp a cached image as now. Download signed HTTPS footage with no HA credentials, bounded size/time and allowed CDN redirects. Extract three frames spanning ten seconds near the recording end; submit as a batch and publish only its final assessment. Recheck source metadata after download.

Add-on options: ring_enabled, recording_camera, recording_timestamp, motion_event; defaults disabled/blank. Expose capture progress and latest processed frame through ingress for calibration. Saved zone/live enabling remain separate from capture configuration.

Tasks:
1. Tests for timestamp/ID race, mismatched devices, duplicate/stale recordings, bounded downloads, batch publishing and extraction timestamps.
2. Adapter, Supervisor permissions/options and UI status/latest frame. No deployment credentials in Git.
3. Full container tests, isolated HA/MQTT fixture smoke test, review, version 0.2.0, concise changelog, push and verify CI.

Limits: calibration-set accuracy only; manual camera geometry still required; Ring cloud latency can exceed the 120-second evidence window. A stable metadata pair is a conservative correlation from HA entities, not a direct Ring recording-history ID/timestamp lookup. Actual HAOS source connection and day/night accuracy require target-device verification.
