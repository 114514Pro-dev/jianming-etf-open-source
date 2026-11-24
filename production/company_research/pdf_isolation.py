"""Bound PDF parsing separately from application writers and credentials."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def extract_pdf(content, *, cancel=None, timeout=35, command=None):
    if len(content) > 30 * 1024 * 1024 or not content.startswith(b"%PDF"):
        raise ValueError("PDF格式无效或超过30MB上限")
    worker = command or [sys.executable, "-I", str(Path(__file__).with_name("pdf_worker.py"))]
    allowed = {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "LC_CTYPE"}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    with tempfile.TemporaryDirectory(prefix="etf-pdf-") as folder:
        source, result = Path(folder) / "input.pdf", Path(folder) / "result.json"
        source.write_bytes(content)
        with result.open("wb") as out:
            process = subprocess.Popen(worker + [str(source)], stdout=out, stderr=subprocess.DEVNULL,
                env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                deadline = time.monotonic() + timeout
                while process.poll() is None:
                    if cancel is not None and cancel.is_set():
                        raise InterruptedError("PDF提取已取消")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("PDF提取超过安全时间上限")
                    if result.stat().st_size > 8 * 1024 * 1024:
                        raise ValueError("PDF提取输出超过安全上限")
                    time.sleep(0.03)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
        if process.returncode or result.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("PDF无法在安全资源上限内提取")
        value = json.loads(result.read_text("utf8"))
        pages = value.get("pages")
        if not isinstance(pages, list) or not 1 <= len(pages) <= 600:
            raise ValueError("PDF页数无效或超过600页上限")
        if any(not isinstance(p, dict) or set(p) != {"page", "text"} or p["page"] != i
               or not isinstance(p["text"], str) for i, p in enumerate(pages, 1)):
            raise ValueError("PDF提取结果格式无效")
        return pages
