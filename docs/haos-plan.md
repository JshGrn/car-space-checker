# HAOS packaging plan

Goal: install the existing checker as a HAOS add-on and publish its source publicly, as subsequently authorized.

Use the existing Debian/Python container on amd64/aarch64. Add Supervisor-only ingress, persistent /data storage, MQTT service discovery, and sensor discovery before footage is available. Keep Docker Compose for development. No Ring credentials or private photos enter Git.

1. Add regression tests for ingress source enforcement, proxy-origin writes, initial offline MQTT discovery, and Supervisor credentials/errors.
2. Implement add-on startup, relative UI URLs and ingress support, and root config.json. Default Docker command remains local serve; Supervisor's injected token selects add-on startup.
3. Run the full container suite, image build and isolated startup smoke check. Review changes.
4. Commit and push to the authorized public repository. Document add-on repository installation and versioned updates; actual HAOS installation depends on access supplied by the user.

Review focus: forged ingress headers, cross-origin writes, service credentials in logs, stale sensor state after restart, private files accidentally packaged. Live Ring capture remains a separate step requiring the integration and recording entities.
