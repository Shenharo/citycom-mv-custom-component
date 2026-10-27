# Release checklist

- Before every release, bump `version` in `custom_components/citycom_mv_water_meter/manifest.json` so it matches the release tag (for example `v0.2.0` -> `0.2.0`).
- If the integration needs a newer `citycom-mv-api`, publish that library to PyPI first, then update the pin in `manifest.json` and `requirements.txt`.
- Tests: `pytest` (needs `pytest-homeassistant-custom-component`). Lint: `ruff check .`.
