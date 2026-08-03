"""PDF retrieval for the docs cohort (ADR-0044).

A vendor whose documentation IS a library of PDFs cannot be read by an HTML parser, and the failure
mode if nobody handles it is not loud: a PDF decoded as text is neither empty as bytes nor short as
extracted text, so `EmptyDocument` and `EmptyRender` would both pass it through and the manifest
would record tens of thousands of bytes of mojibake as a successful snapshot.

The PDF below is BUILT here rather than committed as a binary fixture. A 600-byte generator a
reviewer can read beats an opaque blob they cannot, and it keeps the fixture honest: what is being
tested is that a real extractor runs on real PDF bytes, so the bytes have to be real.
"""
import shutil

import pytest

from core import docs_fetch

pytestmark = pytest.mark.skipif(
    shutil.which(docs_fetch.PDF_EXTRACTOR) is None,
    reason=f"{docs_fetch.PDF_EXTRACTOR} not installed — the extractor's own absence is covered by "
           f"test_a_missing_extractor_raises_rather_than_returning_nothing, which mocks it",
)

TEXT = "XR-8300 firmware 12.003"


def _mini_pdf(*lines: str) -> bytes:
    """A minimal, valid, single-page PDF carrying one text line per argument.

    Lines rather than one long string, because `-layout` CLIPS text that runs past the page width —
    which is the mode this project uses, and worth knowing about in the fixture rather than
    discovering in a manifest.
    """
    lines = lines or (TEXT,)
    body = "BT /F1 12 Tf " + " ".join(
        f"1 0 0 1 40 {740 - 16 * i} Tm ({line}) Tj" for i, line in enumerate(lines)) + " ET"
    stream = body.encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1) + b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, xref))
    return bytes(out)


class _Resp:
    """A urlopen stand-in. `content_type` is what the host CLAIMS; the body is what it sent."""

    def __init__(self, body: bytes, content_type: str):
        self._body, self._ct = body, content_type
        self.status = 200
        self.headers = type("H", (), {
            "get_content_charset": lambda _s: "utf-8",
            "get_content_type": lambda _s, ct=content_type: ct,
            # A real response object has this; the stub grew it when `_fetch` started reading
            # Content-Encoding (ADR-0047). Returning the default means "no transfer encoding".
            "get": lambda _s, k, d=None: d,
        })()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fetch_with(monkeypatch, body: bytes, content_type: str) -> docs_fetch.Document:
    monkeypatch.setattr(docs_fetch.urllib.request, "urlopen",
                        lambda req, timeout=30: _Resp(body, content_type))
    return docs_fetch._fetch("https://library.example.invalid/x.pdf")


def test_a_declared_pdf_is_extracted_rather_than_parsed_as_markup(monkeypatch):
    doc = _fetch_with(monkeypatch, _mini_pdf(), "application/pdf")
    assert doc.kind == "pdf"
    assert TEXT in doc.text


def test_a_pdf_served_as_octet_stream_is_still_extracted_as_a_pdf(monkeypatch):
    """The magic bytes are checked as well as the declared type, because literature hosts commonly
    serve their PDFs as `application/octet-stream`. Trusting the header alone would send a PDF
    through the HTML parser and record the result as a page."""
    doc = _fetch_with(monkeypatch, _mini_pdf(), "application/octet-stream")
    assert doc.kind == "pdf"
    assert TEXT in doc.text


def test_html_is_still_html(monkeypatch):
    """The other direction of the same dispatch: nothing about PDF support may change how an HTML
    page is read, because every published API number rests on that path."""
    doc = _fetch_with(monkeypatch, b"<html><body><p>plain page</p></body></html>", "text/html")
    assert doc.kind == "html" and "plain page" in doc.text


def test_the_extractor_version_is_recorded_on_the_page(monkeypatch, tmp_path):
    """Provenance, not decoration. Extraction is lossy and version-dependent, so a snapshot's byte
    count and hash are only reproducible against the tool that produced them (ADR-0043's dependency
    -drift lesson, applied before it bites rather than after)."""
    import yaml

    manifest = {"budget_tokens": 2000, "tasks": {"t1": {"pages": [
        {"url": "https://library.example.invalid/x.pdf", "role": "api-reference", "note": "pub"}]}}}
    mpath = tmp_path / "manifest.yaml"
    mpath.write_text(yaml.safe_dump(manifest, sort_keys=False))

    padded = _mini_pdf(TEXT, *[f"specification detail row {i} of the publication table"
                               for i in range(6)])
    monkeypatch.setattr(docs_fetch, "_fetch",
                        lambda url, timeout=30, user_agent=None: docs_fetch.Document(
                            text=docs_fetch.pdf_to_text(padded), kind="pdf",
                            extracted_by=docs_fetch.pdf_extractor_version()))
    docs_fetch.fetch_all(mpath, tmp_path / "cache", today="2026-08-01")

    page = yaml.safe_load(mpath.read_text())["tasks"]["t1"]["pages"][0]
    assert docs_fetch.PDF_EXTRACTOR in page["extracted_by"]
    assert page["content_hash"].startswith("sha256:")


def test_an_html_page_records_no_extractor_field(monkeypatch, tmp_path):
    """Conditional, so every HTML-only manifest already on disk stays byte-identical."""
    import yaml

    manifest = {"budget_tokens": 2000, "tasks": {"t1": {"pages": [
        {"url": "https://docs.example.invalid/p", "role": "api-reference", "note": "page"}]}}}
    mpath = tmp_path / "manifest.yaml"
    mpath.write_text(yaml.safe_dump(manifest, sort_keys=False))
    monkeypatch.setattr(docs_fetch, "_fetch",
                        lambda url, timeout=30, user_agent=None: docs_fetch.Document(
                            text="documentation body " * 30, kind="html",
                            extracted_by="core.html_text"))
    docs_fetch.fetch_all(mpath, tmp_path / "cache", today="2026-08-01")

    page = yaml.safe_load(mpath.read_text())["tasks"]["t1"]["pages"][0]
    assert "extracted_by" not in page


def test_a_missing_extractor_raises_rather_than_returning_nothing(monkeypatch):
    """THE LOAD-BEARING REFUSAL.

    A missing binary must not look like a vendor whose documentation is empty. That is the
    absent-vs-broken confusion ADR-0043 names, and here it would be worse than a red test: an empty
    extraction is recorded as a fetch result, so a fact about THIS MACHINE would be published as a
    documentation-delivery finding about a vendor.
    """
    monkeypatch.setattr(docs_fetch.shutil, "which", lambda _name: None)
    with pytest.raises(docs_fetch.PdfExtractorMissing) as exc:
        docs_fetch.pdf_to_text(_mini_pdf())
    assert "not installed" in str(exc.value)


def test_a_corrupt_pdf_is_an_error_and_not_a_silent_empty_page(monkeypatch):
    """A body that claims to be a PDF and is not must be recorded as a failed fetch. Returning ""
    would put it in the same bucket as a vendor page that genuinely carries nothing."""
    with pytest.raises(Exception) as exc:
        docs_fetch.pdf_to_text(b"%PDF-1.4\nnot actually a pdf at all\n")
    assert not isinstance(exc.value, docs_fetch.PdfExtractorMissing)


def test_layout_mode_is_used_so_a_specification_table_survives():
    """`-layout` is not cosmetic. A specification table read without it interleaves the columns,
    which for this cohort destroys exactly what is being scored — a catalog number and the revision
    beside it end up adjacent to the wrong row."""
    assert "-layout" in docs_fetch.PDF_EXTRACTOR_ARGS
