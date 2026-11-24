"""Bounded extra issuer disclosures, stored only in the deep-research cache."""
from datetime import date, datetime
import hashlib
import re
import urllib.request
from urllib.parse import urlsplit

from .data import CNINFO, TZ, DataClient, DataError, DataCancelled, _check

MAX_DOCUMENTS = 8
MAX_PDF_BYTES = 30 * 1024 * 1024
ANNUAL = re.compile(r"(20\d{2})年?年度报告")
EVENTS = re.compile(r"回购|发行|募集资金|收购|关联交易|担保|处罚|诉讼|重大合同|权益分派")


def official_pdf_url(value):
    if not isinstance(value, str):
        return False
    u = urlsplit(value)
    return (u.scheme == "https" and u.netloc == "static.cninfo.com.cn" and not u.query and not u.fragment
            and bool(re.fullmatch(r"/finalpage/\d{4}-\d{2}-\d{2}/[\w.-]+\.PDF", u.path, re.I)))


class _OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not official_pdf_url(newurl):
            raise DataError("官方PDF重定向超出允许来源")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class DeepDataClient(DataClient):
    """Inherits financial acquisition; its cache_dir must be deep-cache."""

    def _extract(self, document, *, cancel=None):
        # The ordinary collector invokes this virtual method for its first two
        # reports too, so no PDF bypasses these same bounded checks.
        try:
            _check(cancel)
            sid = str(document.get("id") or "")
            published = date.fromisoformat(str(document.get("published_at") or ""))
            if not re.fullmatch(r"\d{6,25}", sid) or not official_pdf_url(document.get("url")) or published > datetime.now(TZ).date():
                raise DataError("文档身份、来源或公告日期无效")
            folder = self.cache_dir / "pdf"
            path = folder / (sid + ".pdf")
            for parent in (self.cache_dir, folder, path):
                if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
                    raise DataError("PDF缓存路径不能为链接")
            if not path.resolve().is_relative_to(self.cache_dir.resolve()):
                raise DataError("PDF缓存路径越界")
            if path.exists():
                if path.stat().st_size > MAX_PDF_BYTES:
                    raise DataError("PDF超过30MB上限")
                content = path.read_bytes()
            else:
                request = urllib.request.Request(document["url"], headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/"})
                with urllib.request.build_opener(_OfficialRedirect()).open(request, timeout=self.timeout) as response:
                    if not official_pdf_url(response.geturl()):
                        raise DataError("PDF最终来源不在允许范围")
                    content = response.read(MAX_PDF_BYTES + 1)
                if len(content) > MAX_PDF_BYTES or not content.startswith(b"%PDF"):
                    raise DataError("PDF大小或格式无效")
                folder.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(content)
            if not content.startswith(b"%PDF") or len(content) > MAX_PDF_BYTES:
                raise DataError("缓存PDF格式或大小无效")
            expected = document.get("sha256")
            if expected and hashlib.sha256(content).hexdigest() != expected:
                raise DataError("缓存PDF校验失败")
            super()._extract(document, cancel=cancel)
        except DataCancelled:
            raise
        except (DataError, OSError, ValueError, TypeError):
            document.update(pages=[], extraction_status="failed", extraction_note="文档身份、日期、官方来源或PDF读取未通过检查")

    def _documents(self, code, name, exchange, *, cancel=None, progress=None):
        documents, sources, warnings = super()._documents(code, name, exchange, cancel=cancel, progress=progress)
        today = datetime.now(TZ).date()
        usable = []
        for doc in documents:
            try:
                if date.fromisoformat(doc["published_at"]) <= today:
                    usable.append(doc)
            except (ValueError, KeyError, TypeError):
                continue
        usable.sort(key=lambda d: (d["published_at"], d["id"]), reverse=True)
        selected = usable[:1]
        years = set()
        for doc in usable:
            match = ANNUAL.search(doc["title"])
            if match and int(match[1]) < today.year and match[1] not in years:
                years.add(match[1])
                if doc not in selected:
                    selected.append(doc)
                if len(years) == 5:
                    break
        selected = selected[:6]
        # One extra, bounded official query for capital/governance/risk notices.
        body = {"pageNum": 1, "pageSize": 50, "column": "sse" if exchange == "SH" else "szse", "tabName": "fulltext",
                "stock": "", "searchkey": name or code, "category": "", "plate": "",
                "seDate": f"{today.year - 2}-01-01~{today.isoformat()}", "sortName": "time", "sortType": "desc", "isHLtitle": "false"}
        try:
            data, source = self._fetch(CNINFO, body, post=True, cancel=cancel)
            sources.append(source)
            for row in (data.get("announcements") or [])[:50]:
                _check(cancel)
                if str(row.get("secCode")) != code:
                    continue
                title = re.sub("<[^>]+>", "", str(row.get("announcementTitle") or ""))
                sid, adjunct = str(row.get("announcementId") or ""), str(row.get("adjunctUrl") or "")
                url = "https://static.cninfo.com.cn/" + adjunct
                if not EVENTS.search(title) or not re.fullmatch(r"\d{6,25}", sid) or not official_pdf_url(url):
                    continue
                published = datetime.fromtimestamp(row["announcementTime"] / 1000, TZ).date()
                if published > today or sid in {d["id"] for d in selected}:
                    continue
                selected.append({"id": sid, "company_code": code, "title": title, "url": url, "source_url": url,
                                 "published_at": published.isoformat(), "source_id": source["id"], "document_type": "announcement",
                                 "pages": [], "extraction_status": "not_requested"})
                if len([d for d in selected if d.get("document_type") == "announcement"]) >= 2 or len(selected) >= MAX_DOCUMENTS:
                    break
        except DataCancelled:
            raise
        except (DataError, KeyError, ValueError, TypeError, OSError):
            warnings.append("深度研究的补充公告查询未完成；不代表没有相关事项")
        for position, doc in enumerate(selected[:MAX_DOCUMENTS]):
            _check(cancel)
            doc["company_code"] = code
            doc.setdefault("document_type", "annual_report" if ANNUAL.search(doc["title"]) else "periodic_report")
            if progress:
                progress({"phase": "documents", "progress": 15 + position * 3,
                          "message": f"深研正文 {position + 1}/{len(selected)}：{doc['title']}"})
            if doc.get("extraction_status") != "complete":
                self._extract(doc, cancel=cancel)
        warnings += ["深研最多读取最新定期报告、五个年度报告及两份补充公告；查询与全文数量均有限，不能视为完整尽调。",
                     "官方PDF仅作文字提取，图像、扫描件和复杂表格可能遗漏；企业披露不是独立经营证据。"]
        if len(years) < 3:
            warnings.append("未取得至少三个年度报告的原文链接，多年度经营证据仍有缺口。")
        return selected[:MAX_DOCUMENTS], sources, list(dict.fromkeys(warnings))
