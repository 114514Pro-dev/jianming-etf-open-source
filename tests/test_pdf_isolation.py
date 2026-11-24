import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'production'
sys.path.insert(0, str(ROOT))
from company_research.pdf_isolation import extract_pdf
from pypdf import PdfWriter

def blank(pages=1):
    writer = PdfWriter()
    for _ in range(pages): writer.add_blank_page(width=72, height=72)
    out = io.BytesIO(); writer.write(out)
    return out.getvalue()

class PdfIsolationTests(unittest.TestCase):
    def test_valid_pdf_preserves_page_identity(self):
        self.assertEqual(extract_pdf(blank(2)), [{'page': 1, 'text': ''}, {'page': 2, 'text': ''}])

    def test_representative_existing_public_report_extracts(self):
        report = next(ROOT.glob('*.pdf'))
        pages = extract_pdf(report.read_bytes())
        self.assertGreater(sum(len(p['text']) for p in pages), 1000)

    def test_invalid_input_and_page_limit(self):
        with self.assertRaises(ValueError): extract_pdf(b'not a PDF')
        with self.assertRaises(ValueError): extract_pdf(blank(601))

    def test_timeout_and_cancellation_reap_the_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = Path(tmp) / 'sleep.py'
            worker.write_text('import time; time.sleep(20)', encoding='utf8')
            command = [sys.executable, '-I', str(worker)]
            began = time.monotonic()
            with self.assertRaises(TimeoutError): extract_pdf(blank(), command=command, timeout=0.15)
            self.assertLess(time.monotonic() - began, 3)
            cancel = threading.Event(); cancel.set()
            with self.assertRaises(InterruptedError): extract_pdf(blank(), command=command, cancel=cancel)

    def test_credentials_are_not_inherited(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = Path(tmp) / 'environment.py'
            worker.write_text('import os,json;print(json.dumps({"pages":[{"page":1,"text":os.getenv("AUDIT_SYNTHETIC_SECRET","absent")}]}))', encoding='utf8')
            os.environ['AUDIT_SYNTHETIC_SECRET'] = 'must-not-reach-parser'
            try:
                self.assertEqual(extract_pdf(blank(), command=[sys.executable, '-I', str(worker)])[0]['text'], 'absent')
            finally: os.environ.pop('AUDIT_SYNTHETIC_SECRET', None)

    def test_oversized_child_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = Path(tmp) / 'output.py'
            worker.write_text('import sys;sys.stdout.write("x" * (9*1024*1024))', encoding='utf8')
            with self.assertRaises(ValueError): extract_pdf(blank(), command=[sys.executable, '-I', str(worker)])

if __name__ == '__main__': unittest.main()
