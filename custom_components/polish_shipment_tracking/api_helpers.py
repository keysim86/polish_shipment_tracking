import aiohttp
import asyncio
import async_timeout
import json
import logging
import re
import urllib.parse


_LOGGER = logging.getLogger(__name__)

# Error responses reach logs and exception messages only as a short snippet
# with credentials and personal data masked.
SNIPPET_LIMIT = 200
_MASK = "***"
# JSON values of keys that hold tokens, codes, PINs, passwords, phone numbers,
# e-mail addresses or device ids.
_SECRET_VALUE_RE = re.compile(
    r'("((?:[\w-]{0,40}(?:token|password|secret|phone|e-?mail)[\w-]{0,40}'
    r'|(?:open|qr|pickup|sms|pin)?_?code|pin|device[_-]?u?id|cookies?))'
    r'"\s*:\s*)("(?:[^"\\]|\\.)*"?|[\w.+-]+)',
    re.IGNORECASE,
)
# Only the scheme and host of a URL are kept: paths and queries can carry
# identifiers (ORLEN puts the phone number and device id in the path).
_URL_RE = re.compile(
    r"(?<![a-z0-9+.-])([a-z][a-z0-9+.-]{0,20}:(?:\\?/){2})(?:[^\s/?#@\"'<>\\]{0,256}@)?"
    r"([^\s/?#\"'<>\\]*)([^\s\"'<>]*)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63})+")
# Long strings with digits: tokens, device ids, hashes.
_OPAQUE_RE = re.compile(r"(?<![\w-])[\w-]{16,}")
# Long digit runs: phone and parcel numbers, PINs, timestamps.
_DIGITS_RE = re.compile(r"\d{6,}")


def _mask_secret_value(match) -> str:
    key, value = match.group(2).lower(), match.group(3).strip('"')
    # Status codes ("code": 401) and error codes ("code": "UNAUTHORIZED") are
    # not secrets, and the coordinator may need them.
    if (value.isdigit() and len(value) <= 3) or (
        key.endswith("code") and not any(ch.isdigit() for ch in value)
    ):
        return match.group(0)
    return f'{match.group(1)}"{_MASK}"'


def _strip_url_path(match) -> str:
    return match.group(1) + match.group(2) + ("/..." if match.group(3) else "")


def _mask_opaque(match) -> str:
    value = match.group(0)
    return _MASK if any(ch.isdigit() for ch in value) else value


def redact(text, limit: int = SNIPPET_LIMIT) -> str:
    """Return text safe and short enough for a log line or error message.

    URL paths and queries, values of secret JSON keys, e-mail addresses, long
    opaque strings and long digit runs are masked. Short words such as HTTP
    statuses and OAuth error codes stay: the coordinator looks for them.
    """
    text = " ".join(str(text or "").split())
    text = _SECRET_VALUE_RE.sub(_mask_secret_value, text)
    text = _URL_RE.sub(_strip_url_path, text)
    text = _EMAIL_RE.sub(_MASK, text)
    text = _OPAQUE_RE.sub(_mask_opaque, text)
    text = _DIGITS_RE.sub(_MASK, text)
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def error_detail(text) -> str:
    """Return a short, masked description of an error response body.

    An OAuth error body is reduced to its ``error`` (e.g. ``invalid_grant``),
    ``error_description`` and ``message``: the coordinator decides on
    re-authentication from them, so they must survive masking and truncation.
    """
    try:
        body = json.loads(text)
    except Exception:
        body = None
    if isinstance(body, dict) and isinstance(body.get("error"), str):
        summary = ": ".join(
            body[key]
            for key in ("error", "error_description", "message")
            if isinstance(body.get(key), str) and body[key]
        )
        if summary:
            text = summary
    return redact(text)


def _url_host(url) -> str:
    """Return only the host of url: paths and queries can carry identifiers."""
    try:
        return urllib.parse.urlsplit(str(url)).hostname or "?"
    except ValueError:
        return "?"


async def request_json(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    json_data=None,
    data=None,
    headers=None,
    params=None,
    allow_redirects: bool = True,
    timeout: int = 30,
    label: str = "API",
    log_401_as_info: bool = False,
    error_with_text: bool = True,
    on_response=None,
):
    """
    Perform a request, parse JSON when possible, and apply consistent error handling.

    Returns parsed JSON when available, otherwise the raw response text.
    Errors are logged and raised with a short, masked body snippet only, and
    never with the URL, whose path can carry identifiers.
    """
    if headers is None:
        headers = {}
    api_label = f"{label} API"
    error_label = f"{api_label} Error"

    try:
        async with async_timeout.timeout(timeout):
            kwargs = {
                "headers": headers,
                "params": params,
                "allow_redirects": allow_redirects,
            }
            if json_data is not None:
                kwargs["json"] = json_data
            if data is not None:
                kwargs["data"] = data

            async with session.request(method, url, **kwargs) as resp:
                if on_response:
                    on_response(resp)

                text = await resp.text()
                if resp.status >= 400:
                    detail = error_detail(text)
                    if resp.status == 401 and log_401_as_info:
                        _LOGGER.info("%s error %s: %s", label, resp.status, detail)
                    else:
                        _LOGGER.error("%s error %s: %s", label, resp.status, detail)
                    if error_with_text:
                        raise Exception(f"{error_label}: {resp.status} - {detail}")
                    raise Exception(f"{error_label}: {resp.status}")
                try:
                    return json.loads(text)
                except Exception:
                    return text
    except asyncio.TimeoutError:
        # Host only. "from None" keeps the aiohttp error, whose text can hold
        # the full URL, out of tracebacks too.
        _LOGGER.error("%s %s request to %s timed out", api_label, method, _url_host(url))
        raise Exception(f"{api_label} request timed out") from None
    except aiohttp.ClientError as err:
        detail = redact(str(err))
        _LOGGER.error("%s client error: %s", api_label, detail)
        raise Exception(f"{api_label} client error: {detail}") from None


def normalize_phone(phone: str) -> str:
    """Return a 9-digit phone number as a string."""
    clean = re.sub(r"\D", "", str(phone))
    if len(clean) > 9 and clean.startswith("48"):
        clean = clean[2:]
    elif len(clean) > 9 and clean.startswith("0048"):
        clean = clean[4:]
    return clean
