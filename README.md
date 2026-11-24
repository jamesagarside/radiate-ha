# Radiate for Home Assistant

This integration brings [Radiate](https://github.com/jamesagarside/radiate) into Home Assistant. Radiate balances radiators and runs an on/off boiler across a whole house. The integration adds a climate entity for each room, plus sensors, switches and services, all backed by the Radiate server.

The integration is a thin client of the server's API and contains no control logic. Heating carries on if Home Assistant stops.

> **Status:** pre-alpha, like Radiate itself. It's tested with the Home Assistant test harness against a simulated house.

## Before you start

You need:

- Home Assistant 2025.2 or later, with [HACS](https://hacs.xyz/).
- A running Radiate server, either the Radiate App in Home Assistant or a standalone server. See [deployment](https://github.com/jamesagarside/radiate/blob/main/docs/deployment.md) in the Radiate repository.

HACS doesn't install the Radiate server. It only installs this integration.

## Install

1. In HACS, open the top-right menu, select **Custom repositories**, add `https://github.com/jamesagarside/radiate-ha` with the type **Integration**, then download **Radiate**.
2. Restart Home Assistant.
3. Add the integration:
   - With the Radiate App: accept the discovered **Radiate** under **Settings** > **Devices & services**.
   - With a standalone server: go to **Settings** > **Devices & services** > **Add integration** > **Radiate**, and enter the server URL, for example `http://192.0.2.20:8099`, plus the token if you set one.

To update, update Radiate in HACS and restart Home Assistant.

## Entities

The integration polls the server every 30 seconds. If an older server doesn't report a value, the integration leaves that entity out.

For each room Radiate controls:

- A climate entity. Setting its target temperature (5 to 28 °C in 0.5 °C steps) creates a setpoint override that ends at the room's next scheduled change and survives a server restart. Its attributes show the opening limit, learning state, latest reason, and the override's setpoint (`override_setpoint`), how it ends (`override_until`) and minutes left (`override_expires_in_min`).
- Sensors: temperature, opening limit, heating gain, loss rate, arrival lag, model confidence and learning state.
- A Stuck valve binary sensor (problem class). It turns on when the room stays cold through burns that warm other rooms, or warms while its valve should be shut. Either way, the valve needs checking.

For each room with an open fire or stove:

- A Fire lit switch. Turn it on when you light the fire, so Radiate closes the room's radiator, leaves the room out of boiler demand and pauses its learning. The server forgets it when it restarts.
- A Fire detected binary sensor, on while Radiate treats the fire as lit, either because of the switch or because the room is warming faster than the radiator explains.

Rooms Radiate can't control, such as a bypass radiator, get a temperature sensor only.

For the house:

- Heating mode (`select.radiate_heating_mode`): **Auto**, **Frost** or **Off**. Choosing an option sets the mode, as `radiate.set_mode` does.
- Hot-water store (`binary_sensor.radiate_hot_water_store`): on while the store relay is on, in a store window or during a boost. The relay enables the store; the boiler's own thermostat decides when it heats.
- Hot-water boost (`binary_sensor.radiate_hot_water_boost`): on while a boost from `radiate.boost_store` runs.
- A Demand mode select (`select.radiate_demand_mode`, unique ID `<house id>_house_demand_mode`) with the options **Eco** and **Comfort**. Eco, the default, runs fewer and longer burns: a room on its own can wait until other rooms need heat too, so they share a burn. Comfort fires the boiler as soon as any room is noticeably cold. The change applies from the server's next tick and survives a restart. Choosing the mode set in the server's configuration file (shown in the `default_mode` attribute) makes the server follow that file again.
- Pooled demand (`sensor.radiate_pooled_demand`, unique ID `<house id>_house_pooled_demand`), a diagnostic sensor in minutes: how long the calling rooms need the radiators at full output between them.
- Boiler state, boiler firing, starts in the last hour, predicted burn and outdoor temperature.
- Short-cycle extra off time, in minutes. Radiate adds this to the minimum off time for 24 hours after it sees short-cycling. Attributes give the hours left and the effective minimum off.
- Burner hours today and starts today, plus oil used today (litres) and heat delivered today (kWh) when the server has a nozzle rating. They reset at local midnight. Until a burner-firing signal exists they count relay time, so litres and kWh are an upper bound.
- Balance score for yesterday, 0 to 100. It's higher when rooms reached their setpoints closer together.
- Alerts: the number of current alerts, with each one's code, message and room in the `alerts` attribute.

For each person in the server's household (the `household` section of the house file, or the household set up in Radiate's web UI):

- An away binary sensor, for example `binary_sensor.radiate_early_riser_away`. It's on while Radiate counts the person as away. Its attributes give the `person` entity linked to them (`person_entity`), the reason (`away_until` or `presence`), when they're due back (`away_until`), the presence Radiate last had (`presence`, `presence_since`) whether it has gone stale (`presence_stale`), and why Radiate counts a not home as home, if it does (`presence_why`).

### Presence

To let Home Assistant presence drive away, link each Radiate person to a `person` entity. You can do it in two places:

- In Radiate's web UI: **Home Assistant person** on the People step of the household setup. The integration tells Radiate which `person` entities Home Assistant has when it starts and every 15 minutes, so the setup can list them.
- In Home Assistant: go to **Settings** > **Devices & services** > **Radiate** > **Configure**.

A link in the integration's options takes priority. Leave a person empty there to use the link from Radiate's setup. The integration checks Radiate's people every 15 minutes and reloads when they or their links change.

The integration reports each linked person's state to the server when it changes, and again every 15 minutes so the server knows Home Assistant is still reporting. `home` counts as home and any other state, such as `not_home` or a zone name, counts as not home. `unknown` and `unavailable` aren't reported, so they never make anyone away. The server decides when not home counts as away, after its presence delay. Each report also says when the person's device trackers last reported, what kind they are (GPS, router or Bluetooth) and the phone's battery, where Home Assistant knows. A phone with a flat battery keeps its person at not home, so the server uses this to count a not home whose trackers have gone quiet as home, and to wait longer before a router or Bluetooth tracker counts as away. Servers that don't know these fields ignore them. If you remove a person's link, the integration tells the server to forget that person's presence.

## Services

- `radiate.boost_store`: `minutes`, 0 to 180, default 60.
- `radiate.set_mode`: `auto`, `frost` or `off`.
- `radiate.set_override`: target one or more Radiate climate entities with a `temperature`. By default the override ends at the room's next scheduled change. Set `duration_min` (1 to 10080) to hold it for that long, or `until: cleared` to hold it until you clear it.
- `radiate.clear_override`: returns the targeted rooms to their schedules.
- `radiate.set_away`: `person` (a Radiate person ID, or their linked `person` entity) and `until` (a date and time). The person counts as away until then, and Radiate warms their rooms in time for their return.
- `radiate.clear_away`: `person`. Counts them as home again.

## Development

The tests use `pytest-homeassistant-custom-component`, which pins its own Home Assistant version:

```sh
uv venv --python 3.13
uv pip install -r requirements_test.txt
.venv/bin/pytest
.venv/bin/ruff check custom_components tests
.venv/bin/ruff format --check custom_components tests
```

CI also runs hassfest and HACS validation.

The API contract lives in the Radiate repository: the routes in `radiate.server.app` and section 8.1 of its spec. All server calls go through `RadiateClient` in `api.py`. If a feature needs logic, it belongs in the Radiate server, exposed through the API.

The test fixtures in `tests/fixtures` are real API responses. When the server's API changes, regenerate them from a Radiate checkout and copy them to both repositories:

```sh
python scripts/ha_fixtures.py /path/to/radiate-ha/tests/fixtures
```

Radiate's own tests check that the server still returns every field these fixtures use.

## Licence

[Apache License 2.0](LICENSE). The Radiate server and engine are under the Elastic License 2.0 in their own repository.
