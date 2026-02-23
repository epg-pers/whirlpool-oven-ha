"""Data coordinator — auth, MQTT, and state management for a Whirlpool oven."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    APP_HEADERS,
    BRAND_CREDENTIALS,
    COGNITO_LOGIN_PROVIDER,
    CMD_GET_STATE,
    CMD_RUN,
    CONF_ACCESS_TOKEN,
    CONF_BRAND,
    CONF_MODEL,
    CONF_REFRESH_TOKEN,
    CONF_SAID,
    CONF_TOKEN_EXPIRES,
    DOMAIN,
    EU_AUTH_URL,
    EU_AWS_REGION,
    EU_COGNITO_ID_URL,
    EU_FAVOURITES_URL,
    EU_IOT_ENDPOINT,
    TOPIC_CMD_REQUEST,
    TOPIC_CMD_RESPONSE,
    TOPIC_STATE_UPDATE,
)

_LOGGER = logging.getLogger(__name__)

# How long before token/cred expiry we proactively refresh (seconds)
_REFRESH_BUFFER = 300


class WhirlpoolOvenCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manages authentication, MQTT connection, and oven state."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        session: aiohttp.ClientSession,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{config_entry.data[CONF_SAID]}",
            update_interval=timedelta(minutes=5),
        )
        self._entry = config_entry
        self._session = session
        self._said: str = config_entry.data[CONF_SAID]
        self._model: str = config_entry.data[CONF_MODEL]
        self._brand: str = config_entry.data.get(CONF_BRAND, "whirlpool")

        # Auth
        self._access_token: str | None = config_entry.data.get(CONF_ACCESS_TOKEN)
        self._refresh_token: str | None = config_entry.data.get(CONF_REFRESH_TOKEN)
        self._token_expires: float = float(config_entry.data.get(CONF_TOKEN_EXPIRES, 0))

        # AWS / Cognito
        self._cognito_identity_id: str | None = None
        self._aws_creds: dict[str, str] | None = None
        self._aws_creds_expire: float = 0.0
        self._client_id: str | None = None

        # MQTT
        self._mqtt_connection: Any = None

        # State / favourites
        self._state: dict[str, Any] = {}
        self._favourites: list[dict[str, Any]] = []

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def said(self) -> str:
        return self._said

    @property
    def state(self) -> dict[str, Any]:
        return self._state

    @property
    def favourites(self) -> list[dict[str, Any]]:
        return self._favourites

    @property
    def primary_cavity(self) -> dict[str, Any]:
        return self._state.get("primaryCavity", {})

    # ── Setup / teardown ────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Initialise auth, MQTT, and fetch favourites. Called once on startup."""
        await self._ensure_auth()
        await self._ensure_cognito_creds()
        await self._connect_mqtt()
        await self._fetch_favourites()
        # Ask the oven for its current state immediately
        await self._publish_command({"addressee": "appliance", "command": CMD_GET_STATE})

    async def async_shutdown(self) -> None:
        """Disconnect MQTT cleanly."""
        if self._mqtt_connection is None:
            return
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: self._mqtt_connection.disconnect().result(timeout=5),
            )
        except Exception:  # noqa: BLE001
            pass
        self._mqtt_connection = None

    # ── Authentication ──────────────────────────────────────────────────────────

    def _is_token_valid(self) -> bool:
        return (
            bool(self._access_token)
            and time.time() < self._token_expires - _REFRESH_BUFFER
        )

    async def _ensure_auth(self) -> None:
        if self._is_token_valid():
            return
        # Prefer refresh token to avoid the account-lockout risk of password auth
        if self._refresh_token and await self._do_auth(use_refresh=True):
            return
        _LOGGER.warning("Refresh token failed; falling back to password auth")
        if not await self._do_auth(use_refresh=False):
            raise UpdateFailed("Authentication failed")

    async def _do_auth(self, *, use_refresh: bool) -> bool:
        creds = BRAND_CREDENTIALS.get(self._brand, BRAND_CREDENTIALS["whirlpool"])
        if use_refresh:
            body: dict[str, str] = {
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token or "",
            }
        else:
            body = {
                "grant_type": "password",
                "username": self._entry.data["username"],
                "password": self._entry.data["password"],
            }
        body.update(creds)

        try:
            async with self._session.post(
                EU_AUTH_URL,
                data=body,
                headers={
                    **APP_HEADERS,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("Auth returned HTTP %s", resp.status)
                    return False
                data = await resp.json()
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Auth request error: %s", err)
            return False

        self._access_token = data["access_token"]
        self._refresh_token = data["refresh_token"]
        self._token_expires = time.time() + float(data.get("expires_in", 3600))

        # Persist updated tokens so they survive HA restarts
        new_data = {
            **self._entry.data,
            CONF_ACCESS_TOKEN: self._access_token,
            CONF_REFRESH_TOKEN: self._refresh_token,
            CONF_TOKEN_EXPIRES: self._token_expires,
        }
        self.hass.config_entries.async_update_entry(self._entry, data=new_data)
        _LOGGER.debug("Auth successful (refresh=%s)", use_refresh)
        return True

    # ── AWS Cognito ─────────────────────────────────────────────────────────────

    def _is_cognito_valid(self) -> bool:
        return (
            self._aws_creds is not None
            and time.time() < self._aws_creds_expire - _REFRESH_BUFFER
        )

    async def _ensure_cognito_creds(self) -> None:
        if self._is_cognito_valid():
            return
        await self._ensure_auth()

        # Step 1: exchange Whirlpool OAuth token for a Cognito OpenID token
        try:
            async with self._session.get(
                EU_COGNITO_ID_URL,
                headers={
                    **APP_HEADERS,
                    "Authorization": f"Bearer {self._access_token}",
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                cognito_data = await resp.json()
        except Exception as err:
            raise UpdateFailed(f"Cognito identity request failed: {err}") from err

        identity_id: str = cognito_data["identityId"]
        openid_token: str = cognito_data["token"]
        self._cognito_identity_id = identity_id
        self._client_id = f"{identity_id}_ha"

        # Step 2: exchange the OpenID token for temporary AWS credentials via boto3
        loop = asyncio.get_running_loop()
        try:
            aws_creds, expire_ts = await loop.run_in_executor(
                None, self._get_aws_creds_sync, identity_id, openid_token
            )
        except Exception as err:
            raise UpdateFailed(f"GetCredentialsForIdentity failed: {err}") from err

        self._aws_creds = aws_creds
        self._aws_creds_expire = expire_ts
        _LOGGER.debug("Cognito credentials obtained, expire at %s", expire_ts)

    @staticmethod
    def _get_aws_creds_sync(
        identity_id: str, openid_token: str
    ) -> tuple[dict[str, str], float]:
        """Call GetCredentialsForIdentity via boto3 (blocking — run in executor)."""
        import boto3
        from datetime import timezone

        client = boto3.client("cognito-identity", region_name=EU_AWS_REGION)
        resp = client.get_credentials_for_identity(
            IdentityId=identity_id,
            Logins={COGNITO_LOGIN_PROVIDER: openid_token},
        )
        c = resp["Credentials"]
        creds = {
            "AccessKeyId": c["AccessKeyId"],
            "SecretKey": c["SecretKey"],
            "SessionToken": c["SessionToken"],
        }
        exp = c.get("Expiration", 0)
        if hasattr(exp, "timestamp"):
            expire_ts = exp.astimezone(timezone.utc).timestamp()
        elif isinstance(exp, str):
            from datetime import datetime
            expire_ts = datetime.fromisoformat(
                exp.replace("Z", "+00:00")
            ).astimezone(timezone.utc).timestamp()
        else:
            expire_ts = float(exp)
        return creds, expire_ts

    # ── MQTT ────────────────────────────────────────────────────────────────────

    async def _connect_mqtt(self) -> None:
        await self._ensure_cognito_creds()
        loop = asyncio.get_running_loop()

        aws_creds = self._aws_creds
        client_id = self._client_id

        def _do_connect():
            from awscrt.auth import AwsCredentialsProvider
            from awsiot import mqtt_connection_builder

            provider = AwsCredentialsProvider.new_static(
                access_key_id=aws_creds["AccessKeyId"],
                secret_access_key=aws_creds["SecretKey"],
                session_token=aws_creds["SessionToken"],
            )
            conn = mqtt_connection_builder.websockets_with_default_aws_signing(
                endpoint=EU_IOT_ENDPOINT,
                region=EU_AWS_REGION,
                credentials_provider=provider,
                client_id=client_id,
                on_connection_interrupted=self._on_mqtt_interrupted,
                on_connection_resumed=self._on_mqtt_resumed,
                clean_session=True,
                keep_alive_secs=30,
            )
            conn.connect().result(timeout=30)
            return conn

        try:
            self._mqtt_connection = await loop.run_in_executor(None, _do_connect)
            _LOGGER.info("MQTT connected for %s", self._said)
        except Exception as err:
            raise UpdateFailed(f"MQTT connection failed: {err}") from err

        await self._subscribe_topics()

    async def _subscribe_topics(self) -> None:
        loop = asyncio.get_running_loop()
        topics = [
            TOPIC_STATE_UPDATE.format(model=self._model, said=self._said),
            TOPIC_CMD_RESPONSE.format(
                model=self._model, said=self._said, client_id=self._client_id
            ),
        ]

        def _subscribe():
            from awscrt.mqtt import QoS
            for topic in topics:
                future, _ = self._mqtt_connection.subscribe(
                    topic=topic,
                    qos=QoS.AT_LEAST_ONCE,
                    callback=self._on_mqtt_message,
                )
                future.result(timeout=10)
                _LOGGER.debug("Subscribed to %s", topic)

        await loop.run_in_executor(None, _subscribe)

    def _on_mqtt_message(self, topic: str, payload: bytes, **_kwargs: Any) -> None:
        """Callback from MQTT thread — bridge to HA event loop."""
        try:
            data: dict[str, Any] = json.loads(payload)
        except json.JSONDecodeError as err:
            _LOGGER.warning("Unparseable MQTT payload on %s: %s", topic, err)
            return

        # State update topics carry the state dict directly.
        # Command response topics wrap state in a "payload" key.
        if "/state/update" in topic:
            state_data = data
        else:
            state_data = data.get("payload", data)

        if isinstance(state_data, dict):
            self.hass.loop.call_soon_threadsafe(self._apply_state_update, state_data)

    def _apply_state_update(self, data: dict[str, Any]) -> None:
        """Merge new state into _state and notify HA entities (runs in HA loop)."""
        self._state.update(data)
        self.async_set_updated_data(dict(self._state))

    def _on_mqtt_interrupted(self, connection: Any, error: Any, **_kwargs: Any) -> None:
        _LOGGER.warning("MQTT interrupted for %s: %s", self._said, error)

    def _on_mqtt_resumed(
        self, connection: Any, return_code: Any, session_present: bool, **_kwargs: Any
    ) -> None:
        _LOGGER.info("MQTT resumed for %s (session_present=%s)", self._said, session_present)
        # Re-subscribe if the broker didn't preserve the session
        if not session_present:
            self.hass.loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(self._subscribe_topics())
            )

    async def _publish_command(self, payload: dict[str, Any]) -> None:
        if self._mqtt_connection is None:
            _LOGGER.error("Cannot publish — MQTT not connected")
            return
        topic = TOPIC_CMD_REQUEST.format(
            model=self._model, said=self._said, client_id=self._client_id
        )
        message = json.dumps(
            {
                "requestId": str(uuid.uuid4()),
                "timestamp": int(time.time() * 1000),
                "payload": payload,
            }
        )
        loop = asyncio.get_running_loop()

        def _publish():
            from awscrt.mqtt import QoS
            future, _ = self._mqtt_connection.publish(
                topic=topic,
                payload=message,
                qos=QoS.AT_LEAST_ONCE,
            )
            future.result(timeout=10)

        await loop.run_in_executor(None, _publish)

    # ── Favourites ──────────────────────────────────────────────────────────────

    async def _fetch_favourites(self) -> None:
        await self._ensure_auth()
        url = EU_FAVOURITES_URL.format(said=self._said)
        try:
            async with self._session.get(
                url,
                headers={
                    **APP_HEADERS,
                    "Authorization": f"Bearer {self._access_token}",
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Favourites request returned HTTP %s", resp.status)
                    return
                data = await resp.json()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to fetch favourites: %s", err)
            return

        favs: list[dict[str, Any]] = []
        for fav_list in data.get("favoritesList", []):
            for cycle in fav_list.get("favoriteCycles", []):
                favs.append(
                    {
                        "id": cycle.get("id", ""),
                        "name": cycle.get("name", "Unnamed"),
                        "cavity": cycle.get("cavity", "primaryCavity"),
                        "cycleInfo": cycle.get("cycleInfo", {}),
                    }
                )
        self._favourites = favs
        _LOGGER.debug("Loaded %d favourite(s)", len(favs))

    async def async_refresh_favourites(self) -> None:
        """Re-fetch favourites (e.g. after user adds one in the app)."""
        await self._fetch_favourites()

    # ── Commands ────────────────────────────────────────────────────────────────

    async def async_trigger_favourite(self, fav_id: str) -> None:
        """Start cooking using a saved favourite preset."""
        fav = next((f for f in self._favourites if f["id"] == fav_id), None)
        if fav is None:
            _LOGGER.error("Favourite '%s' not found", fav_id)
            return

        cycles: list[dict] = (
            fav.get("cycleInfo", {})
            .get("cycleMyCreation", {})
            .get("entityCycle", {})
            .get("myCreationCycle", [])
        )
        if not cycles:
            _LOGGER.error("Favourite '%s' has no cycle data", fav_id)
            return

        cycle = cycles[0]
        payload: dict[str, Any] = {
            "addressee": fav.get("cavity", "primaryCavity"),
            "command": CMD_RUN,
            "sessionId": str(uuid.uuid4()),
        }
        if cycle_name := cycle.get("CycleName"):
            payload["recipeId"] = cycle_name
        if target_temp := cycle.get("CavityTargetTemp"):
            payload["targetTemperature"] = float(target_temp)
        if preheat := cycle.get("PreheatType"):
            payload["preheat"] = preheat
        if cook_time := cycle.get("CookTimeSetTime"):
            payload["cookTimer"] = {"command": CMD_RUN, "time": int(float(cook_time))}

        await self._publish_command(payload)
        _LOGGER.info("Triggered favourite '%s'", fav.get("name"))

    async def async_stop_cooking(self) -> None:
        """Cancel the active cooking cycle."""
        cavity = self.primary_cavity
        session_id = cavity.get("sessionId") or str(uuid.uuid4())
        await self._publish_command(
            {
                "addressee": "primaryCavity",
                "command": "cancel",
                "sessionId": session_id,
            }
        )

    async def async_set_cavity_light(self, on: bool) -> None:
        """Turn the cavity light on or off."""
        await self._publish_command(
            {"addressee": "primaryCavity", "command": "set", "cavityLight": on}
        )

    # ── DataUpdateCoordinator callback ──────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """Fallback polling — refresh auth/creds if needed and poll state."""
        try:
            await self._ensure_auth()

            # Reconnect MQTT if Cognito creds expired
            if not self._is_cognito_valid() or self._mqtt_connection is None:
                await async_shutdown_and_reconnect(self)

            await self._publish_command({"addressee": "appliance", "command": CMD_GET_STATE})
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Polling update error: %s", err)

        return self._state


async def async_shutdown_and_reconnect(coordinator: WhirlpoolOvenCoordinator) -> None:
    """Tear down and recreate the MQTT connection (e.g. after cred expiry)."""
    await coordinator.async_shutdown()
    await coordinator._ensure_cognito_creds()  # noqa: SLF001
    await coordinator._connect_mqtt()  # noqa: SLF001
