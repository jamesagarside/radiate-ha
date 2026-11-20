# Radiate for Home Assistant: notes for Claude

The Home Assistant integration for [Radiate](https://github.com/jamesagarside/radiate). It's a thin client of the Radiate server's API, installed through HACS.

- No control logic here. If a feature needs logic, it goes in the Radiate server or core and is exposed through the API; this repo only calls it.
- All server calls go through `RadiateClient` in `custom_components/radiate/api.py`. Keep it in step with the routes in `radiate.server.app` and spec section 8.1 in the radiate repo.
- Follow Home Assistant conventions: config flow, `DataUpdateCoordinator`, `entry.runtime_data`, entity descriptions with translation keys, services in `services.yaml` and `strings.json`. CI runs hassfest and HACS validation.
- Fixtures in `tests/fixtures` come from `scripts/ha_fixtures.py` in the radiate repo. Regenerate them there, never edit them by hand, and copy them to `tests/server/fixtures/ha` in the radiate repo too.
- Use the terms in the radiate repo's `docs/GLOSSARY.md`.
- Licence is Apache-2.0. Never copy code from the radiate repo's server or engine (ELv2) or from Better Thermostat (AGPL) into this repo.
- UK English, metric units, no em dashes. Commits go on a feature branch, with no `Co-Authored-By` or other attribution lines.
