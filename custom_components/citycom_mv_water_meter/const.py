"""Constants for citycom_mv_water_meter."""

from datetime import timedelta
from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

NAME = "Citycom MV water meter"
DOMAIN = "citycom_mv_water_meter"
MANUFACTURER = "Citycom MV"
ATTRIBUTION = "Data provided by Citycom MV"

# Polling only reads data with the current token; it sends no email.
# Meters report a few times a day, so polling often gains little.
CONF_UPDATE_INTERVAL = "update_interval"
DEFAULT_UPDATE_INTERVAL = 30  # minutes
MIN_UPDATE_INTERVAL = 5
MAX_UPDATE_INTERVAL = 24 * 60

# Tokens last 10 hours and cannot be refreshed. Log in again (with a code
# sent by email) when less than this is left, so a poll never hits an
# expired token.
TOKEN_RENEW_MARGIN = timedelta(minutes=45)

CONF_IMAP_HOST = "imap_host"
CONF_IMAP_PORT = "imap_port"
CONF_IMAP_USERNAME = "imap_username"
CONF_IMAP_PASSWORD = "imap_password"  # noqa: S105
CONF_IMAP_FOLDER = "imap_folder"
CONF_CODE_SENDER = "code_sender"
CONF_TOKEN = "token"  # noqa: S105

DEFAULT_IMAP_HOST = "imap.gmail.com"
DEFAULT_IMAP_PORT = 993
DEFAULT_IMAP_FOLDER = "INBOX"
# Sender of "קוד אימות CityCom" emails. IMAP FROM search is a substring match.
DEFAULT_CODE_SENDER = "citycom@gaon.com"

# A meter that has not reported for this long is flagged as not reporting.
STALE_READING_AFTER = timedelta(hours=24)
HISTORY_UPDATE_INTERVAL = timedelta(hours=3)
HISTORY_DAYS = 35
