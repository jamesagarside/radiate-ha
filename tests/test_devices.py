"""The house device and the room devices linked to it."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.radiate.const import DOMAIN

from .conftest import setup_integration


async def test_rooms_hang_off_the_house_device(hass: HomeAssistant, radiate_api, house):
    entry = await setup_integration(hass, house)
    registry = dr.async_get(hass)
    house_device = registry.async_get_device_by_identifier((DOMAIN, house["id"]), entry.entry_id)
    room = registry.async_get_device_by_identifier(
        (DOMAIN, f"{house['id']}_bedroom_1"), entry.entry_id
    )
    assert house_device is not None and room is not None
    assert room.via_device_id == house_device.id
