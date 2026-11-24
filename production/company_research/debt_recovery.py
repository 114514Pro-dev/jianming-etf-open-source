"""Read-only local recovery of debt adapter records from existing company caches.

No network, model calls, writes, fallback zeros, or debt-completeness inference.
Only this boundary reads bytes. The returned records feed pure debt_data helpers.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat

from .debt_data import ADAPTER_VERSION, MAPPINGS, normalize_debt_record

RECOVERY_VERSION = "debt-cache-recovery-1.0"
# Exactly the statement names DataClient.company can request; no arbitrary
# RPT_F10_FINANCE_* or adapter lookalike BINCOME/IINCOME/SINCOME endpoints.
SUPPORTED_REPORTS = frozenset({"RPT_F10_FINANCE_MAINFINADATA", "RPT_F10_FINANCE_GINCOME"} |
    {"RPT_F10_FINANCE_" + prefix + suffix for prefix in "GBIS" for suffix in ("BALANCE", "CASHFLOW")})
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_SOURCE_FILES = 64
MAX_ROWS_PER_FILE = 2000
MAX_RECORDS = 20000


class RecoveryError(ValueError):
    pass


def _gap(code, source=None, **detail):
    source = source if isinstance(source, dict) else {}
    return {"code": code, "source_id": source.get("id"),
            "report_type": (source.get("parameters") or {}).get("reportName") if isinstance(source.get("parameters"), dict) else None,
            **detail}


def _report(source):
    params = source.get("parameters")
    return params.get("reportName") if isinstance(params, dict) else None


def _source_id(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 256


def _relative_parts(value):
    if not isinstance(value, str) or not value or len(value) > 2048 or "\x00" in value:
        raise RecoveryError("raw_path_invalid")
    windows, posix = PureWindowsPath(value), PurePosixPath(value.replace("\\", "/"))
    if windows.drive or windows.root or posix.is_absolute():
        raise RecoveryError("raw_path_absolute_or_drive")
    # Reject Windows alternate data streams, traversal and normalization tricks
    # even when replaying Windows-origin caches on Linux.
    parts = value.replace("\\", "/").split("/")
    if any(p in {"", ".", ".."} or ":" in p or p.endswith((".", " ")) for p in parts):
        raise RecoveryError("raw_path_traversal_or_ambiguous")
    if posix.suffix.lower() != ".json":
        raise RecoveryError("raw_file_format_not_json")
    return parts


def _lstat_no_link(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise RecoveryError("symbolic_link_or_reparse_point")
    return info


def _check_chain(path):
    # Includes cache_dir and its parents, avoiding a trusted-looking root that
    # itself traverses a junction/symlink. A regular final file is checked below.
    for item in [*reversed(path.parents), path]:
        _lstat_no_link(item)


def _windows_opened_path(fd):
    """Check the actual opened handle target, including directory-swap races."""
    import ctypes
    import msvcrt
    from ctypes import wintypes
    fn = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
    fn.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    fn.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    count = fn(msvcrt.get_osfhandle(fd), buffer, len(buffer), 0)
    if not count or count >= len(buffer):
        raise RecoveryError("opened_path_unverifiable")
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return os.path.normcase(os.path.abspath(value))


def _open_local(root, parts):
    path = root.joinpath(*parts)
    _check_chain(path)
    initial = _lstat_no_link(path)
    if not stat.S_ISREG(initial.st_mode):
        raise RecoveryError("raw_path_not_regular_file")
    if os.name == "nt":
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            if _windows_opened_path(fd) != os.path.normcase(os.path.abspath(path)):
                raise RecoveryError("opened_path_changed_or_outside_cache")
        except BaseException:
            os.close(fd)
            raise
    else:
        # Walk each directory via an opened descriptor. O_NOFOLLOW is applied
        # at every source component, not only the final JSON file.
        flags = os.O_RDONLY | os.O_NOFOLLOW
        parent_fd = os.open(root, flags | os.O_DIRECTORY)
        try:
            for part in parts[:-1]:
                next_fd = os.open(part, flags | os.O_DIRECTORY, dir_fd=parent_fd)
                os.close(parent_fd)
                parent_fd = next_fd
            fd = os.open(parts[-1], flags, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
    opened = os.fstat(fd)
    if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (initial.st_dev, initial.st_ino):
        os.close(fd)
        raise RecoveryError("raw_file_changed_during_open")
    return fd, path, opened


def _read_source(root, raw_file, expected_sha, remaining, read_counter):
    parts = _relative_parts(raw_file)
    fd, path, before = _open_local(root, parts)
    try:
        limit = min(MAX_FILE_BYTES, remaining)
        if before.st_size > limit:
            raise RecoveryError("raw_size_limit" if before.st_size > MAX_FILE_BYTES else "total_size_limit")
        chunks, count = [], 0
        while count < limit:
            chunk = os.read(fd, min(65536, limit - count))
            if not chunk: break
            chunks.append(chunk)
            count += len(chunk)
            # Failed hashes/JSON still consume the actual I/O budget.
            read_counter[0] += len(chunk)
        after = os.fstat(fd)
        _check_chain(path)
        current = _lstat_no_link(path)
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if signature(before) != signature(after) or signature(after) != signature(current):
            raise RecoveryError("raw_file_changed_during_read")
        if os.name == "nt" and _windows_opened_path(fd) != os.path.normcase(os.path.abspath(path)):
            raise RecoveryError("opened_path_changed_or_outside_cache")
        content = b"".join(chunks)
        if expected_sha is not None and hashlib.sha256(content).hexdigest() != expected_sha.lower():
            raise RecoveryError("raw_sha256_mismatch")
        return content
    finally:
        os.close(fd)


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value: raise RecoveryError("json_duplicate_key")
        value[key] = item
    return value


def _invalid_constant(value):
    raise RecoveryError("json_nonfinite_number")


def read_cached_company_bundle(cache_dir, code):
    """Read bounded local metadata/text without following links or making calls.

This cache file has no external immutable hash. Its raw sources are separately
verified by recover_debt_records. Callers must retain the saved report's subject,
cutoff and source/document identities instead of substituting a newer company.
"""
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        return None, [{"code": "company_cache_code_invalid"}]
    try:
        root = Path(os.path.abspath(os.fspath(cache_dir)))
        content = _read_source(root, "companies/" + code + ".json", None, MAX_FILE_BYTES, [0])
        value = json.loads(content.decode("utf-8-sig"), object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
        if not isinstance(value, dict) or not isinstance(value.get("company"), dict) or value["company"].get("code") != code:
            raise RecoveryError("company_cache_subject_mismatch")
        return value, []
    except FileNotFoundError:
        return None, [{"code": "company_cache_missing"}]
    except RecoveryError as exc:
        return None, [{"code": "company_cache_rejected", "reason": str(exc)}]
    except (OSError, ValueError, TypeError, RecursionError, UnicodeError):
        return None, [{"code": "company_cache_invalid"}]


def _decode_rows(content, company_code):
    try:
        value = json.loads(content.decode("utf-8-sig"), object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except RecoveryError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        raise RecoveryError("raw_json_invalid") from None
    if not isinstance(value, dict) or value.get("success") is False or value.get("code") not in (None, 0):
        raise RecoveryError("raw_response_failed_or_invalid")
    result = value.get("result")
    rows = result.get("data") if isinstance(result, dict) else None
    if not isinstance(rows, list): raise RecoveryError("raw_result_data_not_list")
    if not rows: raise RecoveryError("raw_result_data_empty")
    if len(rows) > MAX_ROWS_PER_FILE: raise RecoveryError("raw_row_limit")
    if any(not isinstance(row, dict) for row in rows): raise RecoveryError("raw_row_not_object")
    # One foreign/missing company row invalidates that source, rather than
    # silently returning a filtered subset as a successfully verified table.
    if any(row.get("SECURITY_CODE") != company_code for row in rows):
        raise RecoveryError("raw_company_code_mismatch")
    return rows


def _current_records(bundle, company_code):
    if "debt_financial_records" not in bundle: return None, None
    rows = bundle.get("debt_financial_records")
    if bundle.get("debt_adapter_version") != ADAPTER_VERSION:
        return None, "normalized_cache_version_mismatch"
    if not isinstance(rows, list) or not rows or len(rows) > MAX_RECORDS:
        return None, "normalized_cache_empty_or_invalid"
    try:
        if len(json.dumps(rows, allow_nan=False)) > MAX_TOTAL_BYTES:
            return None, "normalized_cache_size_limit"
    except (TypeError, ValueError, RecursionError):
        return None, "normalized_cache_not_json"
    for row in rows:
        if not isinstance(row, dict) or row.get("adapter_version") != ADAPTER_VERSION or row.get("schema_version") != 1:
            return None, "normalized_record_version_mismatch"
        if row.get("code") != company_code or not _source_id(row.get("source_id")):
            return None, "normalized_record_identity_invalid"
        kind = row.get("report_type")
        if not isinstance(kind, str) or "RPT_F10_FINANCE_" + kind not in SUPPORTED_REPORTS:
            return None, "normalized_record_report_type_unsupported"
        fields = row.get("fields")
        if not isinstance(fields, dict) or not set(fields).issubset(set(MAPPINGS[kind].values())):
            return None, "normalized_record_fields_invalid"
        if not isinstance(row.get("issues"), list) or not isinstance(row.get("field_states"), dict):
            return None, "normalized_record_structure_invalid"
        for key, fact in fields.items():
            if not isinstance(fact, dict) or fact.get("state") not in {"reported_value", "reported_zero", "null", "invalid", "metadata_invalid"}:
                return None, "normalized_fact_invalid"
            if fact.get("verification") != "supplier_only":
                return None, "normalized_fact_verification_invalid"
            state, value = fact["state"], fact.get("value")
            if state in {"reported_value", "reported_zero"}:
                valid_number = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                if key == "audit_opinion_reported":
                    if state != "reported_value" or not isinstance(value, str) or not value.strip():
                        return None, "normalized_fact_value_invalid"
                elif not valid_number or (state == "reported_zero") != (value == 0):
                    return None, "normalized_fact_value_invalid"
            elif state == "null" and value is not None:
                return None, "normalized_fact_value_invalid"
            refs = fact.get("source_refs")
            if not isinstance(refs, list) or not refs:
                return None, "normalized_fact_sources_missing"
            if any(not isinstance(ref, dict) or ref.get("source_id") != row["source_id"] or ref.get("report_type") != kind or MAPPINGS[kind].get(ref.get("raw_field")) != key for ref in refs):
                return None, "normalized_fact_source_identity_invalid"
            if fact.get("report_date") != row.get("report_date") or fact.get("announced_at") != row.get("announced_at"):
                return None, "normalized_fact_period_mismatch"
            for ref in refs:
                if any(ref.get(k) != row.get(k) for k in ("report_date", "announced_at", "currency", "scope")):
                    return None, "normalized_fact_source_metadata_mismatch"
                # Reuse the same pure converter against the retained raw scalar.
                # This checks values, zero/null states, units and source basis
                # without trusting an internally inconsistent cached amount.
                original = {"SECURITY_CODE": company_code, "REPORT_DATE": row.get("report_date"),
                            "NOTICE_DATE": row.get("announced_at"), "CURRENCY": row.get("currency"),
                            "SCOPE": row.get("scope"), "UNIT": ref.get("raw_unit"),
                            ref["raw_field"]: ref.get("raw_value")}
                expected = normalize_debt_record(original, row["source_id"], kind)["fields"][key]
                if any(fact.get(k) != expected.get(k) for k in ("state", "value", "raw_state", "currency", "unit", "scope", "basis")):
                    return None, "normalized_fact_raw_value_or_basis_mismatch"
                expected_ref = expected["source_refs"][0]
                if any(ref.get(k) != expected_ref.get(k) for k in ("unit_factor", "raw_state", "raw_presence", "unit_basis")):
                    return None, "normalized_fact_source_unit_mismatch"
    return deepcopy(rows), None


def recover_debt_records(bundle, cache_dir):
    """Return records plus explicit gaps; never write or fetch missing files.

Current normalized caches require both bundle.debt_adapter_version and every
record.adapter_version to match, plus the normalizer's identity/provenance shape.
That fast path does not re-read raw files and says so in coverage. Invalid or old
normalized caches fall back to independently validated raw manifests. A failure
rejects its entire source; other valid sources can still recover as partial.
"""
    output = {"recovery_version": RECOVERY_VERSION, "adapter_version": ADAPTER_VERSION,
              "mode": "raw_cache", "status": "unavailable", "records": [], "gaps": [], "sources": [],
              "coverage": {"candidate_sources": 0, "verified_sources": 0, "verified_bytes": 0,
                           "read_bytes": 0, "normalized_records": 0, "reused_normalized_records": 0,
                           "raw_hashes_rechecked": False, "debt_scope_complete": False}}
    if not isinstance(bundle, dict) or not isinstance(bundle.get("company"), dict):
        output["gaps"].append(_gap("bundle_company_missing")); return output
    code = bundle["company"].get("code")
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        output["gaps"].append(_gap("company_code_invalid")); return output
    try:
        reused, issue = _current_records(bundle, code)
    except (TypeError, ValueError, OverflowError, RecursionError):
        reused, issue = None, "normalized_cache_structure_invalid"
    if reused is not None:
        output.update(mode="normalized_cache", status="reused", records=reused)
        output["coverage"].update(normalized_records=len(reused), reused_normalized_records=len(reused))
        issues = sorted({item for record in reused for item in record.get("issues", []) if isinstance(item, str)})
        if issues:
            output["gaps"].append(_gap("normalized_record_metadata_issues", issues=issues))
            output["status"] = "partial"
        return output
    if issue: output["gaps"].append(_gap(issue))
    try:
        root = Path(os.path.abspath(os.fspath(cache_dir)))
        _check_chain(root)
        if not root.is_dir(): raise RecoveryError("cache_root_not_directory")
    except RecoveryError as exc:
        output["gaps"].append(_gap(str(exc))); return output
    except (OSError, TypeError, ValueError):
        output["gaps"].append(_gap("cache_root_unavailable")); return output
    manifest = bundle.get("sources")
    if not isinstance(manifest, list):
        output["gaps"].append(_gap("source_manifest_missing")); return output
    candidates = []
    for item in manifest:
        if not isinstance(item, dict):
            output["gaps"].append(_gap("source_manifest_entry_invalid")); continue
        report = _report(item)
        if not isinstance(report, str) or report not in SUPPORTED_REPORTS:
            if isinstance(report, str) and report.startswith("RPT_F10_FINANCE_"):
                output["gaps"].append(_gap("source_report_type_unsupported", item))
            continue  # quote, listing and document sources are not debt inputs
        candidates.append(item)
    output["coverage"]["candidate_sources"] = len(candidates)
    if not candidates:
        output["gaps"].append(_gap("no_supported_statement_sources")); return output
    # Same identifier with different provenance is unresolved, regardless of
    # source ordering. Never choose the last dictionary as its resolution.
    fingerprints, invalid_fingerprints = {}, set()
    for source in manifest:
        if not isinstance(source, dict): continue
        sid = source.get("id")
        if _source_id(sid):
            try:
                # Includes every input consumed by the normalizer and the full
                # request parameters. Also detect collisions with nonfinancial
                # manifest entries, whose same ID would mislabel references.
                fingerprint = json.dumps({key: source.get(key) for key in
                    ("parameters", "report_type", "raw_file", "sha256", "url", "source_url")},
                    sort_keys=True, ensure_ascii=True, allow_nan=False)
                fingerprints.setdefault(sid, set()).add(fingerprint)
            except (ValueError, TypeError, RecursionError):
                invalid_fingerprints.add(sid)
    processed, used_bytes, read_counter = set(), 0, [0]
    for index, source in enumerate(candidates):
        if index >= MAX_SOURCE_FILES:
            output["gaps"].append(_gap("source_count_limit", source)); continue
        sid = source.get("id")
        if not _source_id(sid):
            output["gaps"].append(_gap("source_id_missing_or_invalid", source)); continue
        if sid in processed: continue
        processed.add(sid)
        if sid in invalid_fingerprints:
            output["gaps"].append(_gap("source_metadata_not_json", source)); continue
        if len(fingerprints[sid]) > 1:
            output["gaps"].append(_gap("source_identity_conflict", source)); continue
        sha = source.get("sha256")
        if not isinstance(sha, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", sha):
            output["gaps"].append(_gap("source_sha256_missing_or_invalid", source)); continue
        summary = {"source_id": sid, "report_type": _report(source), "raw_file": source.get("raw_file"),
                   "sha256": sha, "status": "rejected", "rows": 0}
        output["sources"].append(summary)
        try:
            content = _read_source(root, source.get("raw_file"), sha, MAX_TOTAL_BYTES-read_counter[0], read_counter)
            # Count verified bytes even when subsequent JSON/schema checks fail.
            used_bytes += len(content)
            rows = _decode_rows(content, code)
            if len(output["records"]) + len(rows) > MAX_RECORDS:
                raise RecoveryError("total_record_limit")
            records = [normalize_debt_record(row, sid, _report(source), source) for row in rows]
        except RecoveryError as exc:
            summary["reason"] = str(exc)
            output["gaps"].append(_gap(str(exc), source)); continue
        except FileNotFoundError:
            summary["reason"] = "raw_file_missing"
            output["gaps"].append(_gap("raw_file_missing", source)); continue
        except (OSError, ValueError, TypeError, RecursionError):
            summary["reason"] = "raw_read_or_normalization_failed"
            output["gaps"].append(_gap("raw_read_or_normalization_failed", source)); continue
        output["records"].extend(records)
        summary.update(status="verified", rows=len(records), bytes=len(content))
        output["coverage"]["verified_sources"] += 1
        issues = sorted({issue for record in records for issue in record.get("issues", [])})
        if issues: output["gaps"].append(_gap("normalized_record_metadata_issues", source, issues=issues))
    output["coverage"].update(verified_bytes=used_bytes, read_bytes=read_counter[0], normalized_records=len(output["records"]),
                              raw_hashes_rechecked=bool(output["coverage"]["verified_sources"]))
    if output["records"]:
        output["status"] = "partial" if output["gaps"] else "recovered"
    return output
