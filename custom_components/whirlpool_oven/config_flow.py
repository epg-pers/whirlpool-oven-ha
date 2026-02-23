"""Config flow for the Whirlpool Oven integration."""

from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    APP_HEADERS,
    BRAND_CREDENTIALS,
    BRAND_OPTIONS,
    COGNITO_IDENTITY_URL,
    COGNITO_LOGIN_PROVIDER,
    COGNITO_TARGET_HEADER,
    CONF_ACCESS_TOKEN,
    CONF_BRAND,
    CONF_MODEL,
    CONF_REFRESH_TOKEN,
    CONF_SAID,
    CONF_TOKEN_EXPIRES,
    DOMAIN,
    EU_AUTH_URL,
    EU_COGNITO_ID_URL,
    EU_AWS_REGION,
)

_LOGGER = logging.getLogger(__name__)


class WhirlpoolOvenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._username: str = ""
        self._password: str = ""
        self._brand: str = "whirlpool"
        self._access_token: str = ""
        self._refresh_token: str = ""
        self._token_expires: float = 0.0
        self._cognito_identity_id: str = ""
        self._aws_creds: dict[str, str] = {}
        # List of discovered appliances: [{"said": ..., "model": ..., "name": ...}]
        self._discovered: list[dict[str, str]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 1 — collect credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._username = user_input["username"]
            self._password = user_input["password"]
            self._brand = user_input.get(CONF_BRAND, "whirlpool")

            session = async_get_clientsession(self.hass)
            auth_ok = await self._try_authenticate(session)
            if not auth_ok:
                errors["base"] = "invalid_auth"
            else:
                creds_ok = await self._get_cognito_creds(session)
                if not creds_ok:
                    errors["base"] = "cognito_failed"
                else:
                    discovered = await self._discover_appliances(session)
                    if not discovered:
                        errors["base"] = "no_appliances"
                    elif len(discovered) == 1:
                        # Only one appliance — skip selection step
                        return self._create_entry(discovered[0])
                    else:
                        self._discovered = discovered
                        return await self.async_step_select_appliance()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("username"): str,
                    vol.Required("password"): str,
                    vol.Optional(CONF_BRAND, default="whirlpool"): vol.In(BRAND_OPTIONS),
                }
            ),
            errors=errors,
        )

    async def async_step_select_appliance(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 2 — let user pick which appliance to add (if multiple)."""
        if user_input is not None:
            chosen_said = user_input["appliance"]
            appliance = next(
                (a for a in self._discovered if a["said"] == chosen_said), None
            )
            if appliance:
                return self._create_entry(appliance)

        options = {a["said"]: a["name"] for a in self._discovered}
        return self.async_show_form(
            step_id="select_appliance",
            data_schema=vol.Schema(
                {vol.Required("appliance"): vol.In(options)}
            ),
        )

    def _create_entry(self, appliance: dict[str, str]) -> config_entries.FlowResult:
        return self.async_create_entry(
            title=appliance["name"],
            data={
                "username": self._username,
                "password": self._password,
                CONF_BRAND: self._brand,
                CONF_SAID: appliance["said"],
                CONF_MODEL: appliance["model"],
                CONF_ACCESS_TOKEN: self._access_token,
                CONF_REFRESH_TOKEN: self._refresh_token,
                CONF_TOKEN_EXPIRES: self._token_expires,
            },
        )

    # ── Helpers ─────────────────────────────────────────────────────────────────

    async def _try_authenticate(self, session: aiohttp.ClientSession) -> bool:
        creds = BRAND_CREDENTIALS.get(self._brand, BRAND_CREDENTIALS["whirlpool"])
        body = {
            "grant_type": "password",
            "username": self._username,
            "password": self._password,
            **creds,
        }
        try:
            async with session.post(
                EU_AUTH_URL,
                data=body,
                headers={
                    **APP_HEADERS,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("Auth failed: HTTP %s", resp.status)
                    return False
                data = await resp.json()
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Auth request error: %s", err)
            return False

        self._access_token = data["access_token"]
        self._refresh_token = data["refresh_token"]
        self._token_expires = time.time() + float(data.get("expires_in", 3600))
        return True

    async def _get_cognito_creds(self, session: aiohttp.ClientSession) -> bool:
        # Step 1: get Cognito OpenID token from Whirlpool API
        try:
            async with session.get(
                EU_COGNITO_ID_URL,
                headers={
                    **APP_HEADERS,
                    "Authorization": f"Bearer {self._access_token}",
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    return False
                cognito_data = await resp.json()
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Cognito ID request failed: %s", err)
            return False

        identity_id: str = cognito_data["identityId"]
        openid_token: str = cognito_data["token"]
        self._cognito_identity_id = identity_id

        # Step 2: exchange for temporary AWS credentials
        try:
            async with session.post(
                COGNITO_IDENTITY_URL,
                json={
                    "IdentityId": identity_id,
                    "Logins": {COGNITO_LOGIN_PROVIDER: openid_token},
                },
                headers={
                    "Content-Type": "application/x-amz-json-1.1",
                    "X-Amz-Target": COGNITO_TARGET_HEADER,
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    return False
                aws_data = await resp.json()
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("GetCredentialsForIdentity failed: %s", err)
            return False

        c = aws_data["Credentials"]
        self._aws_creds = {
            "AccessKeyId": c["AccessKeyId"],
            "SecretKey": c["SecretKey"],
            "SessionToken": c["SessionToken"],
        }
        return True

    async def _discover_appliances(
        self, session: aiohttp.ClientSession
    ) -> list[dict[str, str]]:
        """Use AWS IoT to discover registered appliances."""
        import asyncio

        loop = asyncio.get_event_loop()
        aws_creds = self._aws_creds
        cognito_id = self._cognito_identity_id
        # The IoT thing group name is the UUID portion of the Cognito identity ID
        thing_group = cognito_id.split(":")[-1]

        def _list_things() -> list[dict[str, str]]:
            import boto3

            client = boto3.client(
                "iot",
                region_name=EU_AWS_REGION,
                aws_access_key_id=aws_creds["AccessKeyId"],
                aws_secret_access_key=aws_creds["SecretKey"],
                aws_session_token=aws_creds["SessionToken"],
            )
            try:
                resp = client.list_things_in_thing_group(thingGroupName=thing_group)
            except Exception as err:
                _LOGGER.error("list_things_in_thing_group failed: %s", err)
                return []

            appliances: list[dict[str, str]] = []
            for thing_name in resp.get("things", []):
                try:
                    desc = client.describe_thing(thingName=thing_name)
                    attrs = desc.get("attributes", {})
                    # Decode hex-encoded name if present
                    raw_name = attrs.get("Name", "")
                    try:
                        display_name = bytes.fromhex(raw_name).decode("utf-8").rstrip("\x00")
                    except (ValueError, UnicodeDecodeError):
                        display_name = raw_name or thing_name
                    brand = attrs.get("Brand", "").title()
                    category = attrs.get("Category", "").title()
                    label = f"{brand} {category} ({display_name})" if display_name else f"{brand} {category}"
                    appliances.append(
                        {
                            "said": thing_name,
                            "model": desc.get("thingTypeName", ""),
                            "name": label.strip() or thing_name,
                        }
                    )
                except Exception as err:
                    _LOGGER.warning("describe_thing failed for %s: %s", thing_name, err)
            return appliances

        return await loop.run_in_executor(None, _list_things)
