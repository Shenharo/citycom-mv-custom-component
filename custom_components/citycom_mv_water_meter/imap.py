"""Reads the Citycom 2FA code from a mailbox over IMAP."""

from __future__ import annotations

import asyncio
import contextlib
import email
import imaplib
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import Message
from email.utils import parsedate_to_datetime
from html import unescape

from .const import LOGGER

# Citycom's email reads "קוד האימות שלך הוא: 482915". Fall back to a code
# after a word like "code"/"קוד", then to any standalone 4-8 digit number.
_CITYCOM_CODE = re.compile(r"(?:הוא|is)\s*:?\s*(\d{4,8})(?!\d)", re.IGNORECASE)
_CODE_NEAR_KEYWORD = re.compile(
    r"(?:code|קוד|verification|אימות)\D{0,60}?(?<![\d/.:-])(\d{4,8})(?![\d/.:-])",
    re.IGNORECASE,
)
_ANY_CODE = re.compile(r"(?<![\d/.:+-])(\d{4,8})(?![\d/.:-])")
_TAGS = re.compile(r"<[^>]+>")

# Allow for clock skew between HA and the mail server.
_SINCE_SLACK = timedelta(minutes=2)


class ImapError(Exception):
    """The mailbox could not be read."""


class ImapAuthError(ImapError):
    """The mailbox rejected the credentials."""


class CodeNotFoundError(ImapError):
    """No code email arrived in time."""


@dataclass(frozen=True)
class ImapSettings:
    """Where to look for the code email."""

    host: str
    port: int
    username: str
    password: str
    folder: str
    sender: str


def extract_code(message: Message) -> str | None:
    """Return the 2FA code in an email, or None."""
    parts = [str(message.get("Subject", ""))]
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_maintype() != "text":
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if part.get_content_subtype() == "html":
            text = unescape(_TAGS.sub(" ", text))
        parts.append(text)
    text = "\n".join(parts)
    match = (
        _CITYCOM_CODE.search(text)
        or _CODE_NEAR_KEYWORD.search(text)
        or _ANY_CODE.search(text)
    )
    return match.group(1) if match else None


def _message_time(message: Message) -> datetime | None:
    try:
        value = parsedate_to_datetime(message["Date"])
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _connect(settings: ImapSettings) -> imaplib.IMAP4_SSL:
    try:
        client = imaplib.IMAP4_SSL(settings.host, settings.port, timeout=30)
    except OSError as err:
        raise ImapError(f"Cannot connect to {settings.host}: {err}") from err
    try:
        client.login(settings.username, settings.password)
    except imaplib.IMAP4.error as err:
        raise ImapAuthError(str(err)) from err
    status, _ = client.select(f'"{settings.folder}"', readonly=True)
    if status != "OK":
        client.logout()
        raise ImapError(f"Cannot open folder {settings.folder}")
    return client


def check_login(settings: ImapSettings) -> None:
    """Raise if the mailbox cannot be opened."""
    _connect(settings).logout()


def find_code(settings: ImapSettings, since: datetime) -> str | None:
    """Return the code in the newest matching email received after `since`."""
    client = _connect(settings)
    try:
        day = (since - _SINCE_SLACK).strftime("%d-%b-%Y")
        criteria = f'(SINCE {day} FROM "{settings.sender}")'
        status, data = client.search(None, criteria)
        if status != "OK":
            raise ImapError(f"Search failed: {data}")
        for num in reversed(data[0].split()):
            status, fetched = client.fetch(num, "(BODY.PEEK[])")
            if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                continue
            message = email.message_from_bytes(fetched[0][1])
            received = _message_time(message)
            if received is None or received < since - _SINCE_SLACK:
                # Results are oldest first, so everything before this is older too.
                break
            if code := extract_code(message):
                return code
        return None
    except imaplib.IMAP4.error as err:
        raise ImapError(str(err)) from err
    finally:
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            client.logout()


async def async_wait_for_code(
    hass,
    settings: ImapSettings,
    since: datetime,
    timeout: float = 120,
    interval: float = 5,
) -> str:
    """Poll the mailbox until the code email arrives."""
    deadline = time.monotonic() + timeout
    while True:
        code = await hass.async_add_executor_job(find_code, settings, since)
        if code:
            LOGGER.debug("Found 2FA code email")
            return code
        if time.monotonic() >= deadline:
            raise CodeNotFoundError(
                f"No email from '{settings.sender}' with a code arrived within {timeout:.0f}s"
            )
        await asyncio.sleep(interval)
