"""Isolated child: accepts one public PDF path; emits bounded text-only JSON."""
import json
import os
import sys

if os.name != "nt":
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))

from pypdf import PdfReader

def main():
    reader = PdfReader(sys.argv[1])
    if not 1 <= len(reader.pages) <= 600:
        raise ValueError("page limit")
    pages, total = [], 0
    for i, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        total += len(text.encode("utf8"))
        if total > 4 * 1024 * 1024:
            raise ValueError("text limit")
        pages.append({"page": i, "text": text})
    sys.stdout.buffer.write(json.dumps({"pages": pages}, ensure_ascii=False).encode("utf8"))

if __name__ == "__main__":
    main()
