"""Pure validation and presentation for an inert, account-bound email draft.

No storage, clock, network, subscription or delivery behavior lives here.
"""
from __future__ import annotations

import re
from datetime import datetime


SETTINGS_KEY = "realtime_paper_email_draft_v1"
CONTRACT_VERSION = "paper-email-draft-v1"
MISSING = object()
_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")
_ATOM = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
_LOCAL = re.compile(_ATOM + r"(?:\." + _ATOM + r")*")
_DOMAIN_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


class EmailDraftError(ValueError):
    MESSAGES = {
        "EMAIL_DRAFT_INVALID": (400, "邮件准备草稿格式无效，请核对地址和账户"),
        "EMAIL_DRAFT_ACCOUNT_UNAVAILABLE": (409, "无法核验草稿绑定账户，请重新读取账户状态"),
        "EMAIL_DRAFT_UNAVAILABLE": (503, "邮件草稿配置暂不可用，请稍后核对"),
        "EMAIL_DRAFT_SAVE_FAILED": (503, "邮件草稿未能保存，请重试后核对"),
    }

    def __init__(self, code, binding=None):
        self.code = code
        self.status, self.detail = self.MESSAGES[code]
        self.binding = binding
        super().__init__(self.detail)

    def response(self):
        return {"code": self.code, "detail": self.detail, "retryable": False,
                "binding": self.binding}


def validate_payload(value):
    if type(value) is not dict or set(value) != {"recipient", "account_id"}:
        raise EmailDraftError("EMAIL_DRAFT_INVALID")
    recipient, account_id = value["recipient"], value["account_id"]
    if (type(account_id) is not str or not _ID.fullmatch(account_id)
            or type(recipient) is not str or not 1 <= len(recipient) <= 254
            or not recipient.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in recipient)):
        raise EmailDraftError("EMAIL_DRAFT_INVALID")
    parts = recipient.split("@")
    if len(parts) != 2:
        raise EmailDraftError("EMAIL_DRAFT_INVALID")
    local, domain = parts
    labels = domain.split(".")
    if (not 1 <= len(local) <= 64 or not _LOCAL.fullmatch(local) or len(domain) > 253
            or len(labels) < 2 or any(not _DOMAIN_LABEL.fullmatch(label) for label in labels)
            or not re.fullmatch(r"[A-Za-z]{2,63}", labels[-1])):
        raise EmailDraftError("EMAIL_DRAFT_INVALID")
    return {"recipient": recipient, "account_id": account_id}


def _created(value):
    if type(value) is not str or not 1 <= len(value) <= 80:
        return False
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return moment.tzinfo is not None and moment.utcoffset() is not None
    except (ValueError, TypeError, OverflowError):
        return False


def _current(snapshot):
    if snapshot is None:
        return None, "service_unavailable"
    if type(snapshot) is not dict or snapshot.get("contract_version") != "realtime-paper-v1":
        return None, "account_invalid"
    accounts = snapshot.get("accounts")
    if type(accounts) is not list:
        return None, "account_invalid"
    if not accounts:
        return None, "account_missing"
    if len(accounts) != 1 or type(accounts[0]) is not dict:
        return None, "account_invalid"
    account = accounts[0]
    if (type(account.get("id")) is not str or not _ID.fullmatch(account["id"])
            or account.get("strategy") not in ("D0", "D0I-BOND-WW") or not _created(account.get("created_at"))
            or account.get("status") not in ("running", "paused", "stopped")):
        return None, "account_invalid"
    return {"account_id": account["id"], "account_strategy": account["strategy"],
            "account_created_at": account["created_at"]}, "account_available"


def _stored(saved):
    if type(saved) is not dict or set(saved) != {
            "recipient", "account_id", "account_strategy", "account_created_at"}:
        return None
    if saved["account_strategy"] not in ("D0", "D0I-BOND-WW") or not _created(saved["account_created_at"]):
        return None
    try:
        payload = validate_payload({key: saved[key] for key in ("recipient", "account_id")})
    except EmailDraftError:
        return None
    return {**payload, "account_strategy": saved["account_strategy"], "account_created_at": saved["account_created_at"]}


def _binding(status, reason, account_id=None, account_created_at=None):
    return {"status": status, "reason_code": reason, "account_id": account_id,
            "account_created_at": account_created_at}


def _same(saved, current):
    return all(saved[key] == current[key] for key in ("account_id", "account_strategy", "account_created_at"))


def draft_response(saved, snapshot):
    current, reason = _current(snapshot)
    configured = saved is not MISSING
    draft = _stored(saved) if configured else None
    result = {"contract_version": CONTRACT_VERSION, "preparation_status": "draft_only",
              "sending_enabled": False, "email_status": "not_integrated",
              "draft_status": "empty" if not configured else "saved" if draft else "invalid",
              "draft": {key: draft[key] for key in ("recipient", "account_id")} if draft else None}
    if configured and draft is None:
        binding = _binding("unavailable", "invalid_saved_draft")
    elif current is None:
        binding = _binding("unavailable", reason, draft["account_id"] if draft else None,
                           draft["account_created_at"] if draft else None)
    elif draft is None:
        binding = _binding("not_configured", "no_draft")
    elif not _same(draft, current):
        binding = _binding("unavailable", "account_changed", draft["account_id"], draft["account_created_at"])
    else:
        binding = _binding("available", "account_available", draft["account_id"], draft["account_created_at"])
    return {**result, "binding": binding}


def prepare_draft(value, snapshot, previous=MISSING):
    payload = validate_payload(value)
    current, reason = _current(snapshot)
    if current is None or current["account_id"] != payload["account_id"]:
        reason = reason if current is None else "account_changed"
        code = "EMAIL_DRAFT_UNAVAILABLE" if reason == "service_unavailable" else "EMAIL_DRAFT_ACCOUNT_UNAVAILABLE"
        raise EmailDraftError(code, _binding("unavailable", reason, payload["account_id"]))
    prior = _stored(previous)
    if previous is not MISSING and prior is None:
        raise EmailDraftError("EMAIL_DRAFT_ACCOUNT_UNAVAILABLE",
                              _binding("unavailable", "invalid_saved_draft", payload["account_id"]))
    if prior and prior["account_id"] == payload["account_id"] and not _same(prior, current):
        raise EmailDraftError("EMAIL_DRAFT_ACCOUNT_UNAVAILABLE",
                              _binding("unavailable", "account_changed", payload["account_id"]))
    return {**payload, **current}
