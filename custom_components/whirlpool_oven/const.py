"""Constants for the Whirlpool Oven integration."""

DOMAIN = "whirlpool_oven"

# ── API URLs ──────────────────────────────────────────────────────────────────
# Base URL for the EMEA Whirlpool cloud API
EU_BASE_URL = "https://prod-api.whrcloud.eu"
EU_AUTH_URL = f"{EU_BASE_URL}/oauth/token"
EU_COGNITO_ID_URL = f"{EU_BASE_URL}/api/v1/cognito/identityid"
EU_FAVOURITES_URL = f"{EU_BASE_URL}/api/v1/account/favorites/{{said}}"

# AWS IoT MQTT endpoint (EMEA production)
EU_IOT_ENDPOINT = "wt-eu.applianceconnect.net"
EU_AWS_REGION = "eu-central-1"

# AWS Cognito endpoint (no auth needed – identity verified via openid token)
COGNITO_IDENTITY_URL = (
    f"https://cognito-identity.{EU_AWS_REGION}.amazonaws.com/"
)
COGNITO_TARGET_HEADER = "AmazonCognitoIdentity.GetCredentialsForIdentity"
COGNITO_LOGIN_PROVIDER = "cognito-identity.amazonaws.com"

# ── Brand client credentials ─────────────────────────────────────────────────
# These are embedded in the official app binary and are the same for all users
# of each brand. They are not personal credentials.
BRAND_CREDENTIALS: dict[str, dict[str, str]] = {
    "whirlpool": {
        "client_id": "whirlpool_emea_android_v2",
        "client_secret": "90_3TBRfXfcdCYJj6L5BThEqOBZNkEchrTPT7loqm0gBS_tyeFIIEv47mmYTZkb6",
    },
    "hotpoint": {
        "client_id": "hotpoint_emea_android_v2",
        "client_secret": "Z55aTMbCvlpjyma4ynW0m16S3ro1IA9cxzRQGf3IHN9mcfKesZyPT6bfnfevPdr1",
    },
    "kitchenaid": {
        "client_id": "Kitchenaid_iOS",
        "client_secret": "kkdPquOHfNH-iIinccTdhAkJmaIdWBhLehhLrfoXRWbKjEpqpdu92PISF_yJEWQs72D2yeC0PdoEKeWgHR9JRA",
    },
    "maytag": {
        "client_id": "maytag_ios",
        "client_secret": "OfTy3A3rV4BHuhujkPThVDE9-SFgOymJyUrSbixjViATjCGviXucSKq2OxmPWm8DDj9D1IFno_mZezTYduP-Ig",
    },
}

BRAND_OPTIONS = list(BRAND_CREDENTIALS.keys())

# ── Required HTTP headers ─────────────────────────────────────────────────────
# These match what the official Android app sends on every request.
APP_HEADERS: dict[str, str] = {
    "User-Agent": "okhttp/3.12.0",
    "wp-client-brand": "WHIRLPOOL",
    "wp-client-region": "EMEA",
    "wp-client-country": "GB",
    "wp-client-language": "en",
    "wp-client-version": "7.0.5",
    "wp-client-appName": "com.adbglobal.whirlpool",
    "wp-client-platform": "ANDROID",
}

# ── Config entry keys ─────────────────────────────────────────────────────────
CONF_BRAND = "brand"
CONF_SAID = "said"          # Smart Appliance ID (discovered, not entered by user)
CONF_MODEL = "model"        # AWS IoT thingTypeName (discovered, not entered by user)
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_TOKEN_EXPIRES = "token_expires"

# ── MQTT topics ───────────────────────────────────────────────────────────────
# {model} = AWS IoT thingTypeName  {said} = appliance SAID  {client_id} = unique per connection
TOPIC_STATE_UPDATE = "dt/{model}/{said}/state/update"
TOPIC_CMD_REQUEST = "cmd/{model}/{said}/request/{client_id}"
TOPIC_CMD_RESPONSE = "cmd/{model}/{said}/response/{client_id}"

# ── Commands ──────────────────────────────────────────────────────────────────
CMD_GET_STATE = "getState"
CMD_RUN = "run"
CMD_CANCEL = "cancel"
CMD_SET = "set"

# ── State values ──────────────────────────────────────────────────────────────
CAVITY_STATE_IDLE = "idle"
CAVITY_STATE_PREHEATING = "preheating"
CAVITY_STATES_ACTIVE = {"preheating", "cooking", "broiling", "warming"}

# ── HA entity platforms ───────────────────────────────────────────────────────
PLATFORMS = ["sensor", "switch", "select", "button"]
