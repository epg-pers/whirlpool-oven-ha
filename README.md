# Whirlpool Oven for Home Assistant

A HACS integration that lets you monitor and control Whirlpool 6th Sense ovens from Home Assistant.

## Why not the existing Whirlpool integration?

The [whirlpool-sixth-sense](https://github.com/abmantis/whirlpool-sixth-sense) HACS integration works well for older ("legacy") Whirlpool appliances that expose a REST API. However, **newer oven models use a completely different communication path** — they are registered as AWS IoT "Thing Shadow" (TS) devices rather than legacy appliances.

For TS appliances, the standard REST endpoint (`/api/v1/appliance/{id}`) returns `401 User not authorized`. All state and commands flow through an AWS IoT MQTT broker instead. This integration implements that alternative path.

**How to know if you need this integration:** open the official 6th Sense app, go to your oven, and check if it shows up. If it does but HA says "not authorized", you have a TS appliance.

## Features

- **Real-time state** — cavity temperature, target temperature, cavity state, door status
- **Favourites** — trigger pre-saved cooking presets directly from HA
- **Cavity light** — switch it on/off
- **Stop cooking** — cancel an active cycle remotely
- **Push updates** — state changes are received via MQTT the moment the oven reports them; no polling lag

## Requirements

- Whirlpool 6th Sense account (EMEA region)
- Oven must have **Remote Start** enabled in the app settings
- Home Assistant 2023.6 or later

## Installation

### Via HACS (recommended)

1. In HACS → Integrations → ⋮ → Custom repositories, add `https://github.com/epg-pers/whirlpool-oven-ha` as an **Integration**.
2. Search for *Whirlpool Oven* and install it.
3. Restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration** and search for *Whirlpool Oven*.

### Manual

Copy the `custom_components/whirlpool_oven` folder into your HA `config/custom_components/` directory and restart.

## Setup

Enter your Whirlpool account email and password. The integration will:

1. Authenticate and discover your appliances automatically via the cloud API.
2. Set up an MQTT connection to the oven.
3. Fetch your saved favourites from the app.

## Entities

| Entity | Type | Description |
|--------|------|-------------|
| Oven Temperature | Sensor | Current cavity temperature (°C) |
| Oven Target Temperature | Sensor | Cooking set-point (°C) |
| Oven Cavity State | Sensor | `idle`, `preheating`, `cooking`, … |
| Oven Door | Sensor | `open` / `close` |
| Oven Recipe State | Sensor | `idle`, `running`, `paused` |
| Oven Cavity Light | Switch | Turn cavity light on/off |
| Oven Favourite | Select | Choose a saved favourite preset |
| Start Favourite | Button | Start the selected favourite |
| Stop Cooking | Button | Cancel the active cooking cycle |

## How it works

See [docs/api-internals.md](docs/api-internals.md) for a detailed description of the cloud API and MQTT protocol.

## Limitations & known issues

- EMEA Whirlpool region only (the `whrcloud.eu` stack). Other regions / brands may work but are untested.
- The Whirlpool API will lock the account after repeated failed login attempts. The integration uses refresh tokens to avoid re-authenticating with a password after the initial setup.
- AWS IoT credentials expire after ~1 hour; the integration reconnects automatically.
- Favourites are read from the server at startup. If you add a new favourite in the app, reload the integration entry to pick it up.

## Disclaimer

This integration uses unofficial APIs that were discovered through analysis of the official app. It is not affiliated with or endorsed by Whirlpool Corporation. Use at your own risk.
