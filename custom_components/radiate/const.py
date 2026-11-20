"""Constants for the Radiate integration."""

DOMAIN = "radiate"
CONF_URL = "url"
CONF_TOKEN = "token"
DEFAULT_URL = "http://localhost:8099"
SCAN_INTERVAL_S = 30
CONF_PEOPLE = "people"  # options: Radiate person id to person entity id
# Presence is reported again this often, so the server can tell a quiet Home
# Assistant from a person who is still out (its presence_stale_after_min).
PRESENCE_HEARTBEAT_MIN = 15
