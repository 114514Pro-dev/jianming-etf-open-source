"""One HTTPS request per disposable process, with a parent-owned hard deadline.

urllib's timeout is a socket timeout, not a total request deadline. In particular,
DeepSeek can send blank keepalive lines while a non-streaming request is queued:
https://api-docs.deepseek.com/quick_start/rate_limit/
The worker cannot retry or redirect. Credentials travel only through its stdin.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request


MAX_RESPONSE_BYTES = 2_000_000
MAX_REQUEST_BYTES = 2_000_000
MAX_ERROR_BYTES = 65_536
# Only these exact provider code/type values may cross the process boundary.
# Status matching avoids presenting inconsistent or arbitrary provider text as
# an actionable classification. Unknown 429s remain unclassified.
ERROR_CODE_STATUSES = {
    "insufficient_quota": frozenset({402, 429}),
    "credit_balance_exhausted": frozenset({429}),
    "organization_spend_limit_exceeded": frozenset({429}),
    "project_spend_limit_exceeded": frozenset({429}),
    "organization_usage_limit_exceeded": frozenset({429}),
    "rate_limit_exceeded": frozenset({429}),
    "invalid_api_key": frozenset({401}),
    "model_not_found": frozenset({400, 403, 404}),
    "deepseek_insufficient_balance": frozenset({402}),
}
QUOTA_DETAIL_CODES = frozenset({"credit_balance_exhausted", "organization_spend_limit_exceeded",
                              "project_spend_limit_exceeded", "organization_usage_limit_exceeded"})
DEEPSEEK_ENDPOINTS = frozenset({
    "https://api.deepseek.com/v1/chat/completions",
    "https://api.deepseek.com/chat/completions",
})
ALLOWED_ENDPOINTS = DEEPSEEK_ENDPOINTS | frozenset({
    "https://api.openai.com/v1/responses",
    "https://api.openai.com/v1/chat/completions",
})


def allowed_error_code(code, status, url):
    return (isinstance(code, str) and status in ERROR_CODE_STATUSES.get(code, ())
            and (code != "deepseek_insufficient_balance" or url in DEEPSEEK_ENDPOINTS))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a bearer credential to a redirected endpoint.
        return None


def _provider_error_code(error, url=None):
    """Inspect a bounded error body in the worker, retaining no raw details."""
    try:
        # Official DeepSeek defines HTTP 402 as insufficient account balance.
        # This status meaning is not generalized to OpenAI or other endpoints.
        # https://api-docs.deepseek.com/quick_start/error_codes/
        if error.code == 402 and url in DEEPSEEK_ENDPOINTS:
            return "deepseek_insufficient_balance"
        raw = error.read(MAX_ERROR_BYTES + 1)
        if len(raw) > MAX_ERROR_BYTES:
            return None
        value = json.loads(raw.decode("utf-8"))
        detail = value.get("error") if isinstance(value, dict) else None
        if not isinstance(detail, dict):
            return None
        codes = {detail.get(field) for field in ("code", "type")
                 if allowed_error_code(detail.get(field), error.code, url)}
        # Official billing errors may give a specific code with the broader
        # insufficient_quota type. Preserve that distinction instead of claiming
        # every quota failure means the prepaid balance is zero.
        if len(codes) == 2 and "insufficient_quota" in codes and detail.get("code") in QUOTA_DETAIL_CODES:
            return detail["code"]
        # Conflicting recognized code/type values are ambiguous, not a diagnosis.
        return next(iter(codes)) if len(codes) == 1 else None
    except Exception:
        return None
    finally:
        error.close()


def _validated_request(url, body, api_key, timeout):
    if not isinstance(url, str) or url not in ALLOWED_ENDPOINTS:
        raise ValueError("unsupported_endpoint")
    if not isinstance(body, dict):
        raise ValueError("invalid_request")
    if not isinstance(api_key, str) or not api_key or len(api_key) > 8192 or any(ord(c) < 32 or ord(c) == 127 for c in api_key):
        raise ValueError("invalid_credential")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 120:
        raise ValueError("invalid_timeout")
    return {"url": url, "body": body, "api_key": api_key, "timeout": float(timeout)}


def _worker_command():
    # Absolute paths and isolated mode avoid imports from the current directory.
    return [sys.executable, "-I", str(Path(__file__).resolve())]


def _worker_environment():
    # Do not inherit API keys or unrelated service secrets. These are the only
    # OS/locale variables needed by the absolute Python executable and TLS stack.
    allowed = {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "LC_CTYPE"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def request_json(url, body, api_key, timeout):
    """Return provider JSON or raise a sanitized existing AI-client exception.

    subprocess.run kills and waits for the child on timeout, including draining
    its pipes. There is no request thread left running after this function exits.
    No network retry is performed, including after an ambiguous timeout.
    """
    envelope = _validated_request(url, body, api_key, timeout)
    try:
        payload = json.dumps(envelope, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise ValueError("invalid_request") from None
    if len(payload) > MAX_REQUEST_BYTES:
        raise ValueError("oversized_request")
    try:
        child = subprocess.run(
            _worker_command(), input=payload, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=float(timeout), check=False,
            env=_worker_environment(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError("ai_request_deadline_exceeded") from None
    except OSError:
        raise OSError("ai_transport_unavailable") from None
    if child.returncode != 0 or len(child.stdout) > MAX_RESPONSE_BYTES * 6 + 4096:
        raise ValueError("invalid_transport_response")
    try:
        result = json.loads(child.stdout.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError("invalid_transport_response") from None
    if not isinstance(result, dict):
        raise ValueError("invalid_transport_response")
    if result.get("ok") is True and set(result) == {"ok", "response"}:
        return result["response"]
    if result.get("error") == "http" and type(result.get("http_status")) is int and 100 <= result["http_status"] <= 599:
        error = urllib.error.HTTPError(url, result["http_status"], "AI service request failed", None, None)
        code = result.get("provider_error_code")
        # Recheck the allowlist in the parent; never attach unknown child text.
        if allowed_error_code(code, error.code, url):
            error.provider_error_code = code
        raise error
    if result.get("error") == "timeout":
        raise TimeoutError("ai_request_timeout")
    if result.get("error") == "connection":
        raise OSError("ai_request_connection_failed")
    # Child error descriptions and provider text are never copied to exceptions.
    raise ValueError("ai_request_invalid_response")


def _perform_request(envelope):
    request = _validated_request(**envelope)
    body = json.dumps(request["body"], ensure_ascii=False, allow_nan=False).encode("utf-8")
    post = urllib.request.Request(request["url"], data=body, method="POST", headers={
        "Authorization": "Bearer " + request["api_key"],
        "Content-Type": "application/json", "Accept": "application/json",
    })
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(post, timeout=request["timeout"]) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("oversized_response")
        return json.loads(raw.decode("utf-8"))


def _worker_main():
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("oversized_request")
        envelope = json.loads(raw.decode("utf-8"))
        if not isinstance(envelope, dict) or set(envelope) != {"url", "body", "api_key", "timeout"}:
            raise ValueError("invalid_request")
        result = {"ok": True, "response": _perform_request(envelope)}
        # Serialize inside the protected block: malformed provider numbers and
        # Unicode must not produce an unhandled traceback containing response text.
        output = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except urllib.error.HTTPError as error:
        code = _provider_error_code(error, envelope["url"])
        result = {"ok": False, "error": "http", "http_status": int(error.code)}
        if code:
            result["provider_error_code"] = code
        output = json.dumps(result).encode("ascii")
    except TimeoutError:
        output = b'{"ok":false,"error":"timeout"}'
    except (OSError, urllib.error.URLError):
        output = b'{"ok":false,"error":"connection"}'
    except Exception:
        # Never print an exception, headers, credentials, or provider error body.
        output = b'{"ok":false,"error":"invalid_response"}'
    sys.stdout.buffer.write(output)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    _worker_main()
