"""Constants for the Radiate integration."""

DOMAIN = "radiate"
CONF_URL = "url"
CONF_TOKEN = "token"
DEFAULT_URL = "http://localhost:8099"
SCAN_INTERVAL_S = 30
# A failed fetch is tried once more after this long before the entities go unavailable,
# so a single lost DNS reply or dropped connection doesn't flap them.
FETCH_RETRY_DELAY_S = 2
CONF_PEOPLE = "people"  # options: Radiate person id to person entity id
CONF_OUTDOOR = "outdoor_entity"  # options: weather or temperature sensor entity, or absent
# Presence and the outdoor temperature are reported again this often, so the server
# can tell a quiet Home Assistant from a person who is still out (its
# presence_stale_after_min) and keep an outdoor reading that hasn't changed fresh.
PRESENCE_HEARTBEAT_MIN = 15
