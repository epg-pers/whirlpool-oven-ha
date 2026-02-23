# Whirlpool 6th Sense — API Internals

This document describes how the Whirlpool cloud API works, so the integration can be maintained without needing to re-discover everything from scratch.

---

## Overview

Whirlpool appliances fall into two categories:

| Type | REST API? | MQTT / IoT? |
|------|-----------|-------------|
| Legacy | Yes — `/api/v1/appliance/{SAID}` | No |
| TS (Thing Shadow) | No — returns 401 | Yes — AWS IoT |

Modern ovens (including oven model type 859991682450) are **TS appliances**. The REST appliance endpoint returns 401 for these. All real-time state and commands go through AWS IoT MQTT.

---

## Authentication

### Step 1 — OAuth2 token

**POST** `https://prod-api.whrcloud.eu/oauth/token`

Content-Type: `application/x-www-form-urlencoded`

Required headers on every request:
```
User-Agent: okhttp/3.12.0
wp-client-brand: WHIRLPOOL
wp-client-region: EMEA
wp-client-country: GB
wp-client-language: en
wp-client-version: 7.0.5
wp-client-appName: com.adbglobal.whirlpool
wp-client-platform: ANDROID
```

Body (initial login):
```
grant_type=password
username=<email>
password=<password>
client_id=whirlpool_emea_android_v2
client_secret=<see const.py>
```

Body (token refresh — use this to avoid re-locking the account):
```
grant_type=refresh_token
refresh_token=<stored_token>
client_id=whirlpool_emea_android_v2
client_secret=<see const.py>
```

Response fields of interest:
- `access_token` — short-lived bearer token (expires in ~6 hours)
- `refresh_token` — long-lived (years); use to renew without password
- `expires_in` — seconds until access_token expires
- `TS_SAID` — list of TS appliance Smart Appliance IDs (e.g. `["XXXXXXXXXXX"]`)
- `accountId` — numeric account identifier

> **⚠️ Account lockout**: The API returns HTTP 423 after repeated failed password attempts. Always prefer the refresh_token flow. The account can be unlocked by resetting the password via the app.

---

## AWS IoT Credential Flow

Before connecting to the MQTT broker, the OAuth token must be exchanged for temporary AWS credentials.

### Step 2 — Cognito OpenID token

**GET** `https://prod-api.whrcloud.eu/api/v1/cognito/identityid`

Headers: `Authorization: Bearer <access_token>` + standard app headers.

Response:
```json
{
  "identityId": "eu-central-1:<uuid>",
  "token": "<openid_jwt>"
}
```

### Step 3 — AWS temporary credentials

**POST** `https://cognito-identity.eu-central-1.amazonaws.com/`

Headers:
```
Content-Type: application/x-amz-json-1.1
X-Amz-Target: AmazonCognitoIdentity.GetCredentialsForIdentity
```

Body:
```json
{
  "IdentityId": "eu-central-1:<uuid>",
  "Logins": {
    "cognito-identity.amazonaws.com": "<openid_jwt from step 2>"
  }
}
```

Response contains `Credentials.AccessKeyId`, `.SecretKey`, `.SessionToken`, `.Expiration` (~1 hour).

The `identityId` UUID also serves as the **IoT thing group name** containing the user's appliances.

---

## Appliance Discovery

Using the temporary AWS credentials, call the AWS IoT control plane (SigV4-signed):

**GET** `https://iot.eu-central-1.amazonaws.com/thing-groups/<uuid>/things`

The `<uuid>` is the UUID portion of the Cognito `identityId` (after the `:`).

Returns a list of `things` — each item is an appliance SAID (e.g. `XXXXXXXXXXX`).

For each thing, **GET** `https://iot.eu-central-1.amazonaws.com/things/<thingName>` to get:
- `thingTypeName` — the model number, used as the MQTT topic `{model}` component
- `attributes.Brand`, `attributes.Category`, `attributes.Name` (hex-encoded UTF-8)
- `attributes.Serial`, `attributes.WifiMacAddress` (private — don't log or store)

---

## MQTT Connection

**Broker**: `wt-eu.applianceconnect.net:443`
**Transport**: WebSocket + TLS
**Auth**: AWS Signature V4 (signed URL in the WebSocket path)
**Client ID**: `<identityId>_ha`
**Keep-alive**: 30 s

The `awsiotsdk` Python library handles SigV4 signing automatically via `websockets_with_default_aws_signing`.

---

## MQTT Topics

Replace `{model}` with the thing's `thingTypeName`, `{said}` with the SAID, and `{client_id}` with the MQTT client ID.

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `dt/{model}/{said}/state/update` | Subscribe | Oven pushes state changes |
| `cmd/{model}/{said}/request/{client_id}` | Publish | Send commands to the oven |
| `cmd/{model}/{said}/response/{client_id}` | Subscribe | Oven response to commands |

---

## Command Structure

All messages are JSON:

```json
{
  "requestId": "<uuid>",
  "timestamp": <unix_ms>,
  "payload": { ... }
}
```

### Get current state
```json
{ "addressee": "appliance", "command": "getState" }
```

### Start a bake cycle
```json
{
  "addressee": "primaryCavity",
  "command": "run",
  "sessionId": "<uuid>",
  "recipeID": "forcedAir",
  "targetTemperature": 180.0,
  "preheat": "rapidPreheat",
  "cookTimer": { "command": "run", "time": 1200 }
}
```

Known `recipeID` values (others likely exist — check capability file `W20018739`):
- `forcedAir` — fan oven
- `conventional` — top + bottom heat
- `topHeat` — grill
- `bottomHeat` — bottom heat only
- `fullGrill` — full grill

`preheat` values: `rapidPreheat`, `normalPreheat`, `none`

### Stop cooking
```json
{
  "addressee": "primaryCavity",
  "command": "cancel",
  "sessionId": "<sessionId from active state>"
}
```

### Set cavity light
```json
{
  "addressee": "primaryCavity",
  "command": "set",
  "cavityLight": true
}
```

---

## State Schema (primary cavity)

Key fields from the `primaryCavity` object in state responses:

| Field | Type | Description |
|-------|------|-------------|
| `cavityState` | string | `idle`, `preheating`, `cooking`, … |
| `ovenDisplayTemperature` | number | Current cavity temperature (°C) |
| `targetTemperature` | number | Set-point temperature (°C) |
| `recipeExecutionState` | string | `idle`, `running`, `paused` |
| `doorStatus` | string | `open`, `close` |
| `doorLockStatus` | bool | Door locked |
| `cavityLight` | bool | Cavity light on |
| `sessionId` | string | UUID of the active cook session |
| `remoteStartEnable` | bool | Must be `true` for remote commands to work |
| `temperatureUnit` | string | `celsius` or `fahrenheit` |
| `cookTimer.state` | string | `idle`, `running` |
| `cookTimer.time` | number | Remaining cook time (seconds) |

---

## Favourites

**GET** `https://prod-api.whrcloud.eu/api/v1/account/favorites/{SAID}`

Headers: `Authorization: Bearer <access_token>` + standard app headers.

Response structure:
```json
{
  "favoritesList": [
    {
      "favoriteCycles": [
        {
          "id": "<id>",
          "name": "Fan 180c 20 mins",
          "cavity": "OvenUpperCavity",
          "cycleInfo": {
            "cycleMyCreation": {
              "entityCycle": {
                "myCreationCycle": [
                  {
                    "CycleName": "forcedAir",
                    "CavityTargetTemp": "180.0",
                    "CookTimeSetTime": "1200.0",
                    "PreheatType": "rapidPreheat"
                  }
                ]
              }
            }
          }
        }
      ]
    }
  ]
}
```

To start a favourite, extract the `myCreationCycle[0]` fields and map them to the MQTT `run` command (see above). The `cavity` field becomes `addressee`.

---

## Notes

- `remoteStartEnable` must be `true` on the oven for any command to succeed. The user enables this in the app settings.
- AWS credentials from step 3 expire after ~1 hour. Refresh by repeating steps 2–3 (does not require re-login).
- The refresh token from step 1 is very long-lived (years). Always use it in preference to password auth.
- The `SAID` (Smart Appliance ID) is unique per appliance and tied to the user's account. Treat it as PII.
