"""Public A-share research inputs; no credentials, generated data or trading writes.

Amounts are CNY yuan. Ratios are fractions, not percentage points. Statement
flows are year-to-date, never implicitly annualized. Eastmoney is an aggregator;
CNINFO PDFs are the primary disclosure evidence. Cache contains exact responses.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from .debt_data import ADAPTER_VERSION as DEBT_ADAPTER_VERSION, normalize_debt_record
from .business_data import prepare_business_bundle
from .industry_data import prepare_industry_bundle, recover_scan_industry_inputs

EM = "https://datacenter-web.eastmoney.com/api/data/v1/get"
QUOTE = "https://push2.eastmoney.com/api/qt/clist/get"
CNINFO = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
TZ = timezone(timedelta(hours=8))
FIELDS = ("revenue parent_profit net_profit adjusted_profit op_cashflow roe "
          "gross_margin debt_ratio revenue_yoy profit_yoy total_assets "
          "total_liabilities cash interest_debt capex eps bvps pe_ttm pb "
          "receivables inventory roic op_cashflow_yoy").split()


class DataError(RuntimeError):
    pass


class DataCancelled(DataError):
    pass


def now():
    return datetime.now(TZ).isoformat(timespec="seconds")


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value).replace(",", ""))
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def code_exchange(code):
    code = str(code).strip().upper()
    code = re.sub(r"^(SH|SZ|BJ)", "", code).split(".")[0]
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("请输入6位A股证券代码")
    if code.startswith("6"):
        return code, "SH"
    if code.startswith(("0", "3")):
        return code, "SZ"
    if code.startswith(("4", "8", "92")):
        return code, "BJ"
    raise ValueError("仅支持沪深北A股证券代码；本模块暂未覆盖港股")


def _check(cancel):
    if cancel is not None and (cancel.is_set() if hasattr(cancel, "is_set") else cancel()):
        raise DataCancelled("用户已取消数据采集")


def _emit(progress, **values):
    if progress:
        progress(values)


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + str(threading.get_ident()) + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def normalize(row, source=None):
    """Normalize one vendor row without turning absent numbers into zeros."""
    code, exchange = code_exchange(row.get("SECURITY_CODE", ""))
    result = {k: None for k in FIELDS}
    result.update(code=code, exchange=exchange,
                  name=row.get("SECURITY_NAME_ABBR") or code,
                  industry=row.get("INDUSTRY_NAME") or row.get("PUBLISHNAME") or row.get("BOARD_NAME"),
                  report_date=str(row.get("REPORT_DATE") or row.get("REPORTDATE") or "")[:10] or None,
                  announced_at=str(row.get("NOTICE_DATE") or "")[:10] or None,
                  currency="CNY", flow_basis="year_to_date", field_sources={})
    mapping = {
        "revenue": ("TOTALOPERATEREVE", "TOTAL_OPERATE_INCOME", "OPERATE_INCOME"),
        "parent_profit": ("PARENTNETPROFIT", "PARENT_NETPROFIT"),
        "net_profit": ("NETPROFIT",),
        "adjusted_profit": ("KCFJCXSYJLR", "DEDUCT_PARENT_NETPROFIT"),
        "op_cashflow": ("NETCASH_OPERATE", "NETCASH_OPERATE_PK"),
        "roe": ("ROEJQ", "WEIGHTAVG_ROE"),
        "gross_margin": ("XSMLL",), "debt_ratio": ("ZCFZL", "DEBT_ASSET_RATIO"),
        "revenue_yoy": ("TOTALOPERATEREVETZ", "TOTAL_OPERATE_INCOME_YOY", "YSTZ", "TOI_RATIO"),
        "profit_yoy": ("PARENTNETPROFITTZ", "PARENT_NETPROFIT_YOY", "SJLTZ", "PARENT_NETPROFIT_RATIO"),
        "total_assets": ("TOTAL_ASSETS", "TOTAL_ASSETS_PK"),
        "total_liabilities": ("TOTAL_LIABILITIES", "LIABILITY"),
        "cash": ("MONETARYFUNDS",), "capex": ("CONSTRUCT_LONG_ASSET",),
        "eps": ("EPSJB", "BASIC_EPS"), "bvps": ("BPS",),
        "receivables": ("ACCOUNTS_RECE",), "inventory": ("INVENTORY",),
        "roic": ("ROIC",), "op_cashflow_yoy": ("NETCASH_OPERATE_YOY",),
    }
    percentages = {"roe", "gross_margin", "debt_ratio", "revenue_yoy", "profit_yoy", "roic", "op_cashflow_yoy"}
    for field, keys in mapping.items():
        for key in keys:
            value = number(row.get(key))
            if value is not None:
                result[field] = value / 100 if field in percentages else value
                result["field_sources"][field] = {"source_id": source, "field": key,
                    "report_date": result["report_date"], "announced_at": result["announced_at"]}
                break
    result["financial_type"] = row.get("ORG_TYPE")
    result["source_records"] = [{"source_id": source, "code": code,
        "report_date": result["report_date"], "announced_at": result["announced_at"]}]
    return result


def _merge(target, incoming):
    """Merge same-period sources, keeping revisions and unresolved differences."""
    if target.get("report_date") and incoming.get("report_date") != target["report_date"]:
        return target
    retained_fields = set()
    for key in FIELDS:
        old, new = number(target.get(key)), number(incoming.get(key))
        if old is None or new is None:
            continue
        before = target.get("field_sources", {}).get(key, {})
        after = incoming.get("field_sources", {}).get(key, {})
        # An explicitly unknown field publication date stays unknown. The row
        # date may belong to a different statement merged into this same period.
        old_date = before["announced_at"] if "announced_at" in before else target.get("announced_at")
        new_date = after["announced_at"] if "announced_at" in after else incoming.get("announced_at")
        if math.isclose(old, new, rel_tol=1e-8, abs_tol=1e-6):
            # Equal numbers do not authorize moving provenance back in time:
            # a later intermediate correction would otherwise beat the true
            # newest version after its date was overwritten by this older row.
            if old_date and (not new_date or old_date > new_date):
                retained_fields.add(key)
            continue
        item = {"field": key, "report_date": target.get("report_date"),
                "previous_value": old, "incoming_value": new,
                "previous_source": before, "incoming_source": after,
                "previous_announced_at": old_date, "incoming_announced_at": new_date}
        if old_date and new_date and old_date != new_date:
            item["selected"] = "incoming" if new_date > old_date else "previous"
            target.setdefault("source_revisions", []).append(item)
            if new_date < old_date:
                retained_fields.add(key)
        else:
            # Same or unknown disclosure dates cannot establish a winning version.
            target.setdefault("source_conflicts", []).append(item)
            retained_fields.add(key)
    for key, value in incoming.items():
        if key == "field_sources":
            target.setdefault(key, {}).update({k: v for k, v in value.items() if k not in retained_fields})
        elif key == "source_records":
            target.setdefault(key, []).extend(value)
        elif key in ("source_conflicts", "source_revisions"):
            target.setdefault(key, []).extend(value)
        elif key in retained_fields:
            continue
        elif value is not None and value != "":
            if key == "industry" and target.get("universe_source_id") and target.get("industry"):
                continue
            if key == "announced_at":
                target[key] = max(value, target.get(key) or "")
            else:
                target[key] = value
    return target


def _valuation_sources(item):
    sid = item.get("quote_source_id")
    if sid:
        mapping = {"pe_ttm": "PE_TTM", "pb": "PB_MRQ", "price": "CLOSE_PRICE", "market_cap": "TOTAL_MARKET_CAP"} if item.get("valuation_basis") == "daily_close" else {"pe_ttm": "f115", "pb": "f23", "price": "f2", "market_cap": "f20"}
        for field, raw in mapping.items():
            if item.get(field) is not None:
                item.setdefault("field_sources", {})[field] = {"source_id": sid, "field": raw}
        item["source_ids"] = sorted(set(item.get("source_ids") or []) | {sid})


class DataClient:
    def __init__(self, cache_dir, *, timeout=20, retries=1, min_interval=0.4, cache_hours=6):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = max(2, min(45, timeout))
        self.retries = max(0, min(2, retries))
        self.min_interval = max(0, min_interval)
        self.cache_seconds = cache_hours * 3600
        self._last_request = 0.0
        self._lock = threading.Lock()
        self._request_local = threading.local()

    @contextmanager
    def request_scope(self, *, fresh=False):
        """Track one scan and optionally bypass every HTTP response cache.

        Thread-local policy leaves ordinary background caching and concurrent
        users of this client unchanged. Counts describe attempted HTTP requests
        and successful cache reads, not changed financial facts.
        """
        if type(fresh) is not bool:
            raise ValueError("fresh must be a boolean")
        previous = getattr(self._request_local, "scope", None)
        scope = {"requested_fresh": fresh, "measurement_available": True,
                 "network_requests": 0, "cache_hits": 0,
                 "source_fetched_at_min": None, "source_fetched_at_max": None}
        self._request_local.scope = scope
        try:
            yield scope
        finally:
            self._request_local.scope = previous

    def _request_scope(self):
        return getattr(getattr(self, "_request_local", None), "scope", None)

    def _record_source_time(self, source):
        scope = self._request_scope()
        if scope is None:
            return
        try:
            observed = datetime.fromisoformat(source.get("fetched_at"))
            if observed.tzinfo is None:
                return
            for key, earlier in (("source_fetched_at_min", True), ("source_fetched_at_max", False)):
                current = datetime.fromisoformat(scope[key]) if scope[key] else None
                if current is None or (observed < current if earlier else observed > current):
                    scope[key] = source["fetched_at"]
        except (ValueError, TypeError, AttributeError):
            pass

    def _fetch(self, url, params=None, *, post=False, cancel=None, ttl=None):
        _check(cancel)
        encoded = urllib.parse.urlencode(params or {})
        request_url = url if post or not encoded else url + "?" + encoded
        key = hashlib.sha256((request_url + (encoded if post else "")).encode()).hexdigest()
        cache = self.cache_dir / "responses" / (key + ".json")
        ttl = self.cache_seconds if ttl is None else ttl
        scope = self._request_scope()
        if scope is not None and scope["requested_fresh"]:
            ttl = 0
        if cache.exists() and time.time() - cache.stat().st_mtime < ttl:
            try:
                saved = json.loads(cache.read_text(encoding="utf-8"))
                saved["source"]["cache_hit"] = True
                if scope is not None:
                    scope["cache_hits"] += 1
                    self._record_source_time(saved["source"])
                return saved["data"], saved["source"]
            except (OSError, ValueError, KeyError):
                pass
        error = None
        for attempt in range(self.retries + 1):
            _check(cancel)
            with self._lock:
                delay = self.min_interval - (time.monotonic() - self._last_request)
                if delay > 0:
                    time.sleep(delay)
                self._last_request = time.monotonic()
            try:
                req = urllib.request.Request(request_url, data=encoded.encode() if post else None,
                    headers={"User-Agent": "Mozilla/5.0 CompanyResearch/1.0",
                             "Referer": "https://www.cninfo.com.cn/" if "cninfo" in url else "https://data.eastmoney.com/",
                             "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
                if scope is not None:
                    scope["network_requests"] += 1
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    content = response.read(35 * 1024 * 1024 + 1)
                if len(content) > 35 * 1024 * 1024:
                    raise DataError("数据响应超过35MB安全上限")
                data = json.loads(content.decode("utf-8-sig"))
                digest = hashlib.sha256(content).hexdigest()
                raw_path = self.cache_dir / "raw" / (key + "-" + digest[:16] + ".json")
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(content)
                source = {"id": key[:20], "publisher": "巨潮资讯" if "cninfo" in url else "东方财富",
                          "url": request_url, "source_url": request_url,
                          "method": "POST" if post else "GET", "parameters": params or {},
                          "fetched_at": now(), "sha256": digest,
                          "raw_file": str(raw_path.relative_to(self.cache_dir)), "cache_hit": False}
                _write(cache, {"source": source, "data": data})
                self._record_source_time(source)
                return data, source
            except (urllib.error.URLError, OSError, ValueError, DataError) as exc:
                error = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
        raise DataError(f"{urllib.parse.urlparse(url).netloc} 获取失败：{error}")

    def _report(self, report, filter_, *, sort="SECURITY_CODE", cancel=None, progress=None, columns="ALL"):
        rows, sources, errors = [], [], []
        expected, pages, page = None, 1, 1
        while page <= pages:
            _check(cancel)
            params = {"reportName": report, "columns": columns, "pageSize": 500,
                      "pageNumber": page, "sortColumns": sort, "sortTypes": "-1" if "DATE" in sort else "1",
                      "filter": filter_, "source": "WEB", "client": "WEB"}
            try:
                data, source = self._fetch(EM, params, cancel=cancel)
                result = data.get("result")
                if not data.get("success") or not result:
                    raise DataError(str(data.get("message") or "财报结果为空"))
                current_count = int(result["count"])
                if expected is None:
                    expected, pages = current_count, int(result["pages"])
                    if pages > 300:
                        raise DataError("财报分页超出上限，拒绝无界抓取")
                elif expected != current_count:
                    errors.append("采集期间总条数发生变化，需要重新扫描")
                chunk = result.get("data") or []
                if not chunk and expected:
                    raise DataError(f"第{page}页为空")
                rows.extend((r, source["id"]) for r in chunk)
                sources.append(source)
                _emit(progress, stage="financials", report=report, page=page, pages=pages,
                      completed=len(rows), total=expected)
            except DataCancelled:
                raise
            except (DataError, KeyError, TypeError, ValueError) as exc:
                errors.append(f"{report} 第{page}页：{exc}")
                # First-page failure has no trustworthy page count.
                if expected is None:
                    break
            page += 1
        return rows, {"report": report, "expected": expected, "received": len(rows),
                      "complete": expected is not None and len(rows) == expected and not errors,
                      "errors": errors}, sources

    def _quote_universe(self, progress=None, cancel=None):
        rows, sources, errors = {}, [], []
        total, pages, page = None, 1, 1
        failures = 0
        started = time.monotonic()
        while page <= pages:
            _check(cancel)
            if time.monotonic() - started > 300:
                errors.append("估值行情补充超过5分钟上限；保留已取得部分，其余估值留空")
                break
            params = {"pn": page, "pz": 100, "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
                      "fields": "f12,f14,f13,f2,f115,f23,f20,f124", "fid": "f12", "po": 0, "np": 1, "fltt": 2}
            try:
                data, source = self._fetch(QUOTE, params, cancel=cancel, ttl=min(self.cache_seconds, 1800))
                result = data.get("data") or {}
                count = int(result["total"])
                if total is None:
                    total, pages = count, math.ceil(count / 100)
                    if pages > 150:
                        raise DataError("市场名单超过150页上限")
                elif total != count:
                    errors.append("市场名单总数在分页期间变化；覆盖待复核")
                chunk = result.get("diff") or []
                if isinstance(chunk, dict):
                    chunk = list(chunk.values())
                if not chunk:
                    raise DataError("行情名单分页为空")
                for r in chunk:
                    code, exchange = code_exchange(r.get("f12", ""))
                    if code in rows:
                        errors.append(f"行情名单重复代码{code}")
                    item = {field: None for field in FIELDS}
                    item.update(code=code, exchange=exchange, name=r.get("f14") or code,
                                industry=None, report_date=None, announced_at=None,
                                price=number(r.get("f2")), pe_ttm=number(r.get("f115")), pb=number(r.get("f23")),
                                market_cap=number(r.get("f20")), quote_fetched_at=source["fetched_at"],
                                quote_source_id=source["id"], source_url=source["url"])
                    stamp = number(r.get("f124"))
                    item["valuation_as_of"] = datetime.fromtimestamp(stamp, TZ).isoformat(timespec="seconds") if stamp and stamp > 0 else None
                    rows[code] = item
                sources.append(source)
                failures = 0
                _emit(progress, stage="universe", page=page, pages=pages, completed=len(rows), total=total)
            except DataCancelled:
                raise
            except (DataError, KeyError, TypeError, ValueError) as exc:
                errors.append(f"市场名单第{page}页：{exc}")
                failures += 1
                if total is None or failures >= 2:
                    break
            page += 1
        return rows, {"expected": total, "received": len(rows), "complete": total is not None and len(rows) == total and not errors,
                      "errors": errors}, sources

    def _universe(self, progress=None, cancel=None):
        fields = "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,LISTING_STATE,LISTING_DATE,SECURITY_TYPE,TRADE_MARKET,BOARD_NAME_2LEVEL,ORG_TYPE"
        filter_ = f'(SECURITY_TYPE_CODE="058001001")(LISTING_STATE="0")(LISTING_DATE<=\'{date.today().isoformat()}\')'
        records, meta, sources = self._report("RPT_F10_ORG_BASICINFO", filter_, columns=fields,
                                             progress=progress, cancel=cancel)
        rows = {}
        for r, sid in records:
            code, exchange = code_exchange(r["SECURITY_CODE"])
            if r.get("LISTING_STATE") != "0" or r.get("SECURITY_TYPE") != "A股":
                meta["errors"].append("证券主数据返回了非存续A股：" + code)
                continue
            if code in rows:
                meta["errors"].append("证券主数据代码重复：" + code)
                continue
            item = {field: None for field in FIELDS}
            item.update(code=code, exchange=exchange, name=r["SECURITY_NAME_ABBR"],
                        industry=r.get("BOARD_NAME_2LEVEL"), financial_type=r.get("ORG_TYPE"),
                        report_date=None, announced_at=None, listing_date=str(r.get("LISTING_DATE") or "")[:10],
                        listing_state="listed", universe_source_id=sid, source_url=EM,
                        field_sources={}, source_records=[])
            rows[code] = item
        meta.update(received=len(rows), complete=meta["complete"] and len(rows) == meta["expected"] and not meta["errors"],
                    exchange_counts=dict(Counter(x["exchange"] for x in rows.values())))
        return rows, meta, sources

    def _valuations(self, progress=None, cancel=None, code=None):
        """Daily valuation table has explicit PE_TTM and a true trading date."""
        sources, values = [], {}
        columns = "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,PE_TTM,PB_MRQ,CLOSE_PRICE,TOTAL_MARKET_CAP"
        try:
            # A dated liquid constituent finds the last available market day. It
            # does not restrict the subsequent whole-market valuation request.
            params = {"reportName": "RPT_VALUEANALYSIS_DET", "columns": columns,
                      "pageSize": 1, "pageNumber": 1, "sortColumns": "TRADE_DATE", "sortTypes": "-1",
                      "filter": f'(SECURITY_CODE="{code or "000001"}")(TRADE_DATE<=\'{datetime.now(TZ).date().isoformat()}\')'}
            data, source = self._fetch(EM, params, cancel=cancel)
            sources.append(source)
            rows = (data.get("result") or {}).get("data") or []
            if not data.get("success") or not rows:
                raise DataError(data.get("message") or "未取得最新收盘估值日期")
            trade_date = str(rows[0]["TRADE_DATE"])[:10]
            if code:
                records = [(rows[0], source["id"])]
                meta = {"expected": 1, "received": 1, "complete": True, "errors": []}
            else:
                records, meta, ss = self._report("RPT_VALUEANALYSIS_DET", f'(TRADE_DATE=\'{trade_date}\')',
                                                columns=columns, progress=progress, cancel=cancel)
                sources.extend(ss)
            by_id = {s["id"]: s for s in sources}
            for row, sid in records:
                sec, _ = code_exchange(row["SECURITY_CODE"])
                if sec in values:
                    meta["errors"].append("估值数据重复证券代码：" + sec)
                    meta["complete"] = False
                values[sec] = {"pe_ttm": number(row.get("PE_TTM")), "pb": number(row.get("PB_MRQ")),
                               "price": number(row.get("CLOSE_PRICE")), "market_cap": number(row.get("TOTAL_MARKET_CAP")),
                               "valuation_as_of": str(row["TRADE_DATE"])[:10], "quote_source_id": sid,
                               "quote_fetched_at": by_id[sid]["fetched_at"], "valuation_basis": "daily_close"}
            meta["trade_date"] = trade_date
            meta["provider"] = "东方财富日终估值（PE_TTM、PB_MRQ）"
            return values, meta, sources
        except DataCancelled:
            raise
        except (DataError, KeyError, TypeError, ValueError) as exc:
            return {}, {"expected": None, "received": 0, "complete": False, "errors": [str(exc)]}, sources

    def scan(self, progress=None, cancel=None):
        started = now()
        companies, market, sources = self._universe(progress, cancel)
        quote_rows, quote_meta, qs = self._valuations(progress, cancel)
        if not quote_rows:
            fallback_rows, fallback_meta, fallback_sources = self._quote_universe(progress, cancel)
            fallback_meta["daily_valuation_error"] = quote_meta["errors"]
            quote_rows, quote_meta = fallback_rows, fallback_meta
            qs.extend(fallback_sources)
        sources.extend(qs)
        for code, quote in quote_rows.items():
            if code in companies:
                for field in ("pe_ttm", "pb", "price", "market_cap", "quote_fetched_at", "quote_source_id", "valuation_as_of", "valuation_basis"):
                    if quote.get(field) is not None:
                        companies[code][field] = quote[field]
        summary, summary_meta, ss = self._report("RPT_LICO_FN_CPD", '(ISNEW="1")(SECURITY_TYPE_CODE="058001001")',
                                               progress=progress, cancel=cancel)
        sources.extend(ss)
        statements = [summary_meta]
        # If current listing fails, preserve financial evidence, but explicitly mark
        # an unverified universe. Never silently replace full market with a sample.
        for row, sid in summary:
            incoming = normalize(row, sid)
            code = incoming["code"]
            if code not in companies:
                if market["complete"]:
                    continue
                companies[code] = {"listing_unverified": True}
            target = companies[code]
            if not target.get("report_date") or incoming["report_date"] >= target["report_date"]:
                quote = {k: target.get(k) for k in ("pe_ttm", "pb", "price", "market_cap", "quote_fetched_at", "quote_source_id")}
                industry = target.get("industry")
                target.update(incoming)
                if industry and target.get("universe_source_id"):
                    target["industry"] = industry
                target.update({k: v for k, v in quote.items() if v is not None})
        dates = Counter(x.get("report_date") for x in companies.values() if x.get("report_date"))
        common_date = dates.most_common(1)[0][0] if dates else None
        if common_date:
            for report in ("RPT_F10_FINANCE_GINCOME", "RPT_DMSK_FN_BALANCE", "RPT_DMSK_FN_CASHFLOW"):
                columns = "SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,NOTICE_DATE,NETPROFIT,DEDUCT_PARENT_NETPROFIT,ORG_TYPE" if report.endswith("GINCOME") else "ALL"
                rows, meta, ss = self._report(report, f'(REPORT_DATE=\'{common_date}\')(SECURITY_TYPE_CODE="058001001")',
                                              progress=progress, cancel=cancel, columns=columns)
                sources.extend(ss)
                statements.append(meta)
                # Multiple restated versions: newest announcement wins, stable code order.
                rows.sort(key=lambda p: (p[0].get("NOTICE_DATE") or "", p[0].get("UPDATE_DATE") or ""))
                for row, sid in rows:
                    if row.get("SECURITY_CODE") in companies:
                        _merge(companies[row["SECURITY_CODE"]], normalize(row, sid))
        source_times = {s["id"]: s.get("fetched_at") for s in sources if isinstance(s, dict) and s.get("id")}
        for item in companies.values():
            item["missing_fields"] = [f for f in FIELDS if item.get(f) is None]
            item["data_status"] = "financials_available" if item.get("report_date") else "financials_missing"
            item["warnings"] = [] if item.get("report_date") else ["公开财报接口未返回该公司最新摘要，不能据此评分"]
            if item.get("report_date") and item["report_date"] != common_date:
                item["warnings"].append("报告期落后于市场常见报告期，未混入其他期间三表数据")
            item["as_of"] = datetime.now(TZ).date().isoformat()
            item["source_ids"] = sorted({r["source_id"] for r in item.get("source_records", []) if r.get("source_id")})
            # This is the actual financial-source retrieval time. Reusing a
            # cached response cannot turn yesterday's retrieval into today's.
            item["fetched_at"] = max((source_times[sid] for sid in item["source_ids"]
                                      if isinstance(source_times.get(sid), str)), default=None)
            _valuation_sources(item)
        complete = market["complete"] and all(x["complete"] for x in statements)
        coverage = {"scope": "沪深北存续A股（证券类型A股、上市状态0、上市日期不晚于采集日）", "expected_total": market["expected"],
                    "universe_total": len(companies), "market_received": market["received"],
                    "financials_total": sum(bool(c.get("report_date")) for c in companies.values()),
                    "cashflow_total": sum(c.get("op_cashflow") is not None for c in companies.values()),
                    "balance_total": sum(c.get("total_assets") is not None for c in companies.values()),
                    "complete": complete, "universe_complete": market["complete"],
                    "report_date": common_date, "report_dates": dict(dates),
                    "started_at": started, "fetched_at": now(), "market": market, "statements": statements,
                    "quotes": quote_meta, "quote_total": sum(c.get("quote_fetched_at") is not None for c in companies.values()),
                    "quote_only_codes_excluded": sorted(set(quote_rows) - set(companies)),
                    "financial_only_codes_excluded": sorted({r["SECURITY_CODE"] for r, sid in summary} - set(companies)),
                    "errors": market["errors"] + [e for s in statements for e in s["errors"]],
                    "missing_financial_codes": sorted(c for c, v in companies.items() if not v.get("report_date")),
                    "note": "完整表示已核对公开接口全部分页，不表示每家公司资料齐全。行情估值是采集快照；财务流量为报告期累计，未经年化。"}
        result = {"companies": sorted(companies.values(), key=lambda x: x["code"]), "coverage": coverage,
                  "sources": sources, "fetched_at": now(), "schema_version": 1}
        _check(cancel)
        industry_inputs = recover_scan_industry_inputs(result, self.cache_dir)
        for company in result["companies"]:
            company.update(industry_inputs.get(company["code"], {}))
        _write(self.cache_dir / "scan-latest.json", result)
        if complete:
            _write(self.cache_dir / "scan-last-complete.json", result)
        return result

    def company(self, code, progress=None, cancel=None):
        code, exchange = code_exchange(code)
        cutoff = f"{date.today().year - 5}-01-01"
        history, sources, warnings, statuses = {}, [], [], []
        debt_financial_records = []
        org_type = None
        for base_report in ("RPT_F10_FINANCE_MAINFINADATA", "RPT_F10_FINANCE_GINCOME", "RPT_F10_FINANCE_GBALANCE", "RPT_F10_FINANCE_GCASHFLOW"):
            report = base_report
            prefix = {"银行": "B", "保险": "I", "证券": "S"}.get(org_type)
            if prefix and (base_report.endswith("GBALANCE") or base_report.endswith("GCASHFLOW")):
                report = base_report.replace("_G", "_" + prefix)
            rows, meta, ss = self._report(report, f'(SECURITY_CODE="{code}")(REPORT_DATE>=\'{cutoff}\')',
                                          sort="REPORT_DATE", cancel=cancel, progress=progress)
            sources.extend(ss)
            statuses.append(meta)
            warnings.extend(meta["errors"])
            statement_sources = {s["id"]: s for s in ss if isinstance(s, dict) and s.get("id")}
            rows.sort(key=lambda p: (p[0].get("NOTICE_DATE") or "", p[0].get("UPDATE_DATE") or ""))
            for row, sid in rows:
                # Separate fact objects never replace cash/scalars consumed by
                # the established financial screen or AI evidence fingerprint.
                debt_financial_records.append(normalize_debt_record(row, sid, report, statement_sources.get(sid)))
                if base_report == "RPT_F10_FINANCE_MAINFINADATA" and row.get("ORG_TYPE"):
                    org_type = row["ORG_TYPE"]
                if row.get("CURRENCY") not in (None, "CNY"):
                    warnings.append(f"{report} {row.get('REPORT_DATE')}为非人民币，未合并金额")
                    continue
                normalized = normalize(row, sid)
                key = normalized["report_date"]
                if key not in history:
                    history[key] = normalized
                else:
                    _merge(history[key], normalized)
        ordered = sorted(history.values(), key=lambda r: r["report_date"], reverse=True)
        for item in ordered:
            item["source_ids"] = sorted({r["source_id"] for r in item.get("source_records", []) if r.get("source_id")})
        company = dict(ordered[0]) if ordered else {"code": code, "name": code, "exchange": exchange, **{f: None for f in FIELDS}}
        company["as_of"] = datetime.now(TZ).date().isoformat()
        company["listing_unverified"] = True
        try:
            scan = json.loads((self.cache_dir / "scan-latest.json").read_text(encoding="utf-8"))
            found = next((c for c in scan["companies"] if c["code"] == code), None)
            if found:
                for field in ("industry", "pe_ttm", "pb", "price", "market_cap", "quote_fetched_at", "quote_source_id", "valuation_as_of", "valuation_basis", "listing_state", "universe_source_id"):
                    if found.get(field) is not None:
                        company[field] = found[field]
                company["listing_unverified"] = found.get("listing_unverified", not bool(found.get("universe_source_id")))
                if found.get("universe_source_id"):
                    sources.extend(s for s in scan["sources"] if s["id"] == found["universe_source_id"])
                if found.get("quote_source_id"):
                    sources.extend(s for s in scan["sources"] if s["id"] == found["quote_source_id"])
        except (OSError, ValueError, KeyError):
            warnings.append("暂无全市场行情快照，市盈率/市净率保持缺失")
        if not company.get("valuation_as_of"):
            valuations, valuation_meta, valuation_sources = self._valuations(cancel=cancel, code=code)
            sources.extend(valuation_sources)
            if code in valuations:
                company.update(valuations[code])
            else:
                warnings.extend("单股估值获取失败：" + e for e in valuation_meta["errors"])
        _valuation_sources(company)
        documents, doc_sources, doc_warnings = self._documents(code, company.get("name"), exchange, cancel=cancel, progress=progress)
        sources.extend(doc_sources)
        warnings.extend(doc_warnings)
        if not ordered:
            warnings.append("未取得有效财务历史，不能作公司质量判断")
        if len([x for x in ordered if x["report_date"].endswith("12-31")]) < 5:
            warnings.append("近五个年度财报未齐全；可能上市历史较短或数据源缺失")
        warnings.extend(["财务历史为数据供应商当前版本，可能含追溯调整，不能直接作为历史时点回测输入。",
                         "货币资金不等于可自由支配现金；受限资金、担保及债务到期安排需查公告附注。",
                         "interest_debt在未核实全部有息债务项目时保持缺失，不把空白负债项目当零。"])
        result = {"company": company, "history": ordered, "documents": documents,
                  "debt_financial_records": debt_financial_records,
                  "debt_adapter_version": DEBT_ADAPTER_VERSION,
                  "sources": list({s["id"]: s for s in sources}.values()), "warnings": list(dict.fromkeys(warnings)),
                  "fetched_at": now(), "coverage": {"history_rows": len(ordered), "from_date": cutoff,
                  "statements": statuses, "extracted_documents": sum(d.get("extraction_status") == "complete" for d in documents)},
                  "schema_version": 1}
        # Reuse the just-cached public raw files. This deterministic addition
        # cannot replace any financial scalar, source document, or old score.
        result.update(prepare_business_bundle(result, self.cache_dir, as_of=company["as_of"]))
        result.update(prepare_industry_bundle(result, self.cache_dir, as_of=company["as_of"]))
        _check(cancel)
        _write(self.cache_dir / "companies" / (code + ".json"), result)
        return result

    def _documents(self, code, name, exchange, *, cancel=None, progress=None):
        warnings, sources, documents = [], [], []
        start = f"{date.today().year - 5}-01-01"
        # CNINFO groups Beijing reports under its szse query backend; "bse"
        # silently returns zero even for valid current Beijing codes.
        body = {"pageNum": 1, "pageSize": 100, "column": "sse" if exchange == "SH" else "szse",
                "tabName": "fulltext", "stock": "", "searchkey": name or code,
                "category": "category_ndbg_szsh;category_bndbg_szsh;category_yjdbg_szsh;category_sjdbg_szsh;",
                "plate": "", "seDate": start + "~" + date.today().isoformat(),
                "sortName": "time", "sortType": "desc", "isHLtitle": "false"}
        try:
            data, source = self._fetch(CNINFO, body, post=True, cancel=cancel)
            sources.append(source)
            for row in data.get("announcements") or []:
                if str(row.get("secCode")) != code:
                    continue
                title = re.sub("<[^>]+>", "", row.get("announcementTitle") or "")
                path = row.get("adjunctUrl") or ""
                if not re.fullmatch(r"finalpage/\d{4}-\d{2}-\d{2}/[\w.-]+\.PDF", path, re.I):
                    continue
                if any(word in title for word in ("摘要", "英文", "取消", "更正公告", "提示性公告", "说明", "意见", "回复")):
                    continue
                if not re.search(r"\d{4}年?(?:半年度|年度|第一季度|第三季度|一季度|三季度)报告", title):
                    continue
                documents.append({"id": str(row["announcementId"]), "title": title,
                                  "url": "https://static.cninfo.com.cn/" + path,
                                  "source_url": "https://static.cninfo.com.cn/" + path,
                                  "published_at": datetime.fromtimestamp(row["announcementTime"] / 1000, TZ).date().isoformat(),
                                  "source_id": source["id"], "pages": [], "extraction_status": "not_requested",
                                  "extraction_note": "仅发现原文链接，尚未提取全文"})
            # Latest report plus latest annual report; older originals remain linked.
            selected = documents[:1]
            annual = next((d for d in documents if "年度报告" in d["title"] and "半年度" not in d["title"]), None)
            if annual and annual not in selected:
                selected.append(annual)
            for doc in selected:
                _check(cancel)
                _emit(progress, stage="documents", title=doc["title"], completed=selected.index(doc), total=len(selected))
                self._extract(doc, cancel=cancel)
                if doc["extraction_status"] != "complete":
                    warnings.append(doc["title"] + "：" + doc["extraction_note"])
            if not documents:
                warnings.append("巨潮未找到与证券代码匹配的定期报告；未编造原文证据")
            if data.get("hasMore"):
                warnings.append("公告查询仅返回最近100条匹配结果，较早公告可能未包含")
        except DataCancelled:
            raise
        except (DataError, KeyError, ValueError, TypeError) as exc:
            warnings.append("官方公告获取失败：" + str(exc))
        return documents, sources, warnings

    def _extract(self, document, *, cancel=None):
        try:
            from pypdf import PdfReader
        except ImportError:
            document.update(extraction_status="unavailable", extraction_note="服务器未安装PDF提取组件pypdf，尚未读取全文")
            return
        try:
            _check(cancel)
            path = self.cache_dir / "pdf" / (document["id"] + ".pdf")
            if path.exists():
                content = path.read_bytes()
            else:
                req = urllib.request.Request(document["url"], headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/"})
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    content = response.read(30 * 1024 * 1024 + 1)
                if len(content) > 30 * 1024 * 1024:
                    raise DataError("PDF超过30MB上限")
                if not content.startswith(b"%PDF"):
                    raise DataError("下载内容不是PDF")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            from .pdf_isolation import extract_pdf
            try:
                pages = extract_pdf(content, cancel=cancel)
            except InterruptedError:
                raise DataCancelled("PDF提取已取消")
            document.update(pages=pages, total_pages=len(pages), sha256=hashlib.sha256(content).hexdigest(),
                            fetched_at=now(), extraction_status="complete", extraction_note="逐页文字提取完成；图像与复杂表格仍可能缺失，未作OCR核验")
            if sum(len(p["text"].strip()) for p in pages) < 100:
                document.update(extraction_status="needs_ocr", extraction_note="提取文字过少，疑似扫描件，尚未读取全文")
        except DataCancelled:
            raise
        except Exception as exc:
            document.update(extraction_status="failed", extraction_note="PDF提取失败：" + str(exc)[:240])
