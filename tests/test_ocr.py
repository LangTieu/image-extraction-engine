"""P2 tests: OCR backends, reading order, PDF fast path, multiscale, orchestrator."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from engine.ocr.base import OCREngine, OCRResult, OCRToken, normalize_text
from engine.ocr.multiscale import reocr_low_confidence
from engine.ocr.pdf import extract_pdf_pages
from engine.ocr.pipeline import GeneralOCR
from engine.ocr.reading_order import blocks_to_text, split_columns, tokens_to_blocks
from engine.ocr.tesseract_backend import TesseractEngine
from engine.preprocessing.mapping import TransformLog


def _font(size: int = 28):
    for name in ("DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_image(text: str = "HELLO 123", size: tuple[int, int] = (320, 100)) -> np.ndarray:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 30), text, fill="black", font=_font())
    return np.asarray(img)


class StubEngine(OCREngine):
    """Deterministic engine implementing the OCREngine ABC."""

    name = "stub"

    def __init__(self, tokens=None, empty_first=False):
        self._tokens = tokens if tokens is not None else []
        self._empty_first = empty_first
        self.calls = 0
        self.last_image = None

    def recognize(self, image, *, languages=("vi", "en"), min_confidence=0.0):
        self.calls += 1
        self.last_image = image
        if self._empty_first and self.calls == 1:
            return OCRResult(tokens=[], engine=self.name, elapsed_ms=0.0)
        tokens = [
            OCRToken(text=t, bbox=b, confidence=c)
            for (t, b, c) in self._tokens
            if c >= min_confidence
        ]
        return OCRResult(tokens=tokens, engine=self.name, elapsed_ms=0.0)


# --- base: interface + normalization ---------------------------------------


def test_normalize_text_nfc():
    decomposed = "ho\u0301a t\u00f4\u0309ng"  # combining marks on o
    assert normalize_text(decomposed) == "hóa tổng"
    assert normalize_text("HỌC") == "HỌC"


def test_stub_engine_is_an_ocr_engine():
    eng = StubEngine([("A", (0, 0, 10, 10), 0.9)])
    assert isinstance(eng, OCREngine)
    res = eng.recognize(np.zeros((10, 10, 3), dtype=np.uint8), min_confidence=0.5)
    assert res.engine == "stub" and [t.text for t in res.tokens] == ["A"]


# --- tesseract backend ------------------------------------------------------


def _tesseract_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


requires_tesseract = pytest.mark.skipif(
    not _tesseract_available(), reason="tesseract binary not available"
)


@requires_tesseract
def test_tesseract_word_tokens_vie_eng():
    img = _text_image("HELLO 123")
    engine = TesseractEngine(lang="vie+eng")
    res = engine.recognize(img, min_confidence=0.0)
    assert res.engine == "tesseract"
    assert res.tokens, "expected at least one word token"
    h, w = img.shape[:2]
    for tok in res.tokens:
        assert 0.0 <= tok.confidence <= 1.0
        assert tok.language == "vie"  # first lang of "vie+eng"
        x0, y0, x1, y1 = tok.bbox
        assert 0 <= x0 <= x1 <= w and 0 <= y0 <= y1 <= h
    joined = " ".join(t.text for t in res.tokens)
    assert "HELLO" in joined and "123" in joined


# --- reading order ----------------------------------------------------------


def _tok(text, x0, y0, x1, y1, conf=0.9):
    return OCRToken(text=text, bbox=(x0, y0, x1, y1), confidence=conf)


def test_split_columns_respects_gap():
    tokens = [_tok("A", 0, 0, 30, 20), _tok("B", 40, 0, 70, 20), _tok("C", 200, 0, 230, 20)]
    columns = split_columns(tokens)
    assert len(columns) == 2
    assert [t.text for t in columns[0]] == ["A", "B"]
    assert [t.text for t in columns[1]] == ["C"]


def test_word_spacing_does_not_split_column():
    tokens = [_tok("A", 0, 0, 30, 20), _tok("B", 40, 0, 70, 20)]
    assert len(split_columns(tokens)) == 1


def test_group_lines_and_reading_order():
    # column 1: two lines; column 2: one line
    tokens = [
        _tok("A", 0, 0, 30, 20),
        _tok("B", 40, 0, 70, 20),
        _tok("C", 0, 100, 30, 120),
        _tok("D", 400, 0, 430, 20),
    ]
    blocks = tokens_to_blocks(tokens)
    assert [b.text for b in blocks] == ["A B", "C", "D"]
    assert [b.reading_order for b in blocks] == [0, 1, 2]
    assert blocks_to_text(blocks).splitlines() == ["A B", "C", "D"]


# --- PDF paths --------------------------------------------------------------


def _write_text_layer_pdf(path, text="HELLO TEXT LAYER") -> None:
    content = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    with open(path, "wb") as fh:
        fh.write(out)


def _write_image_only_pdf(path) -> None:
    Image.new("RGB", (200, 100), "white").save(path, "PDF")


def test_pdf_text_layer_fast_path(tmp_path):
    pdf = str(tmp_path / "text.pdf")
    _write_text_layer_pdf(pdf)
    pages = extract_pdf_pages(pdf, dpi=150)
    assert len(pages) == 1
    page = pages[0]
    assert page.has_text_layer
    assert page.render is None  # fast path: no rasterization, no OCR
    joined = " ".join(t.text for t in page.tokens)
    assert "HELLO" in joined and "LAYER" in joined


def test_pdf_image_only_page_uses_ocr_path(tmp_path):
    pdf = str(tmp_path / "img.pdf")
    _write_image_only_pdf(pdf)
    pages = extract_pdf_pages(pdf, dpi=100)
    assert len(pages) == 1
    assert not pages[0].has_text_layer
    assert pages[0].render is not None and pages[0].render.dtype == np.uint8
    doc = GeneralOCR([StubEngine([("IMG", (0, 0, 10, 10), 0.9)])])
    result = doc.recognize_pdf(pdf)
    assert result.engines_used == ["stub"]
    assert result.text() == "IMG"


def test_pdf_fast_path_skips_ocr(tmp_path):
    pdf = str(tmp_path / "text.pdf")
    _write_text_layer_pdf(pdf)
    engine = StubEngine()
    doc = GeneralOCR([engine])
    result = doc.recognize_pdf(pdf)
    assert engine.calls == 0  # no OCR run
    assert result.engines_used == []
    assert "HELLO" in result.text()


# --- multiscale re-OCR ------------------------------------------------------


def test_multiscale_replaces_low_confidence_token():
    img = np.full((60, 120, 3), 255, dtype=np.uint8)
    low = OCRToken(text="875", bbox=(20, 20, 60, 40), confidence=0.2, language="vi")
    result = OCRResult(
        tokens=[low, OCRToken(text="ok", bbox=(80, 20, 100, 40), confidence=0.95)], engine="stub"
    )

    class RetryEngine(StubEngine):
        def recognize(self, image, **kw):
            self.last_image = image
            # crop passed here is a 2x upscaled ROI
            return OCRResult(
                tokens=[OCRToken(text="875C", bbox=(0, 0, 10, 10), confidence=0.91)],
                engine=self.name,
            )

    retry = RetryEngine()
    out = reocr_low_confidence(img, result, retry, threshold=0.6)
    assert retry.last_image is not None  # re-OCR ran on the upscaled crop
    by_conf = {round(t.confidence, 2): t for t in out.tokens}
    assert 0.91 in by_conf and by_conf[0.91].text == "875C"
    assert by_conf[0.95].text == "ok"  # high-confidence token untouched
    # bbox mapped back into the original image's neighbourhood
    fixed = by_conf[0.91].bbox
    assert 0 <= fixed[0] < 120 and 0 <= fixed[1] < 60


def test_multiscale_keeps_token_when_retry_fails():
    img = np.full((60, 120, 3), 255, dtype=np.uint8)
    low = OCRToken(text="x", bbox=(20, 20, 60, 40), confidence=0.2)
    result = OCRResult(tokens=[low], engine="stub")

    class FailingEngine(StubEngine):
        def recognize(self, image, **kw):
            raise RuntimeError("backend boom")

    out = reocr_low_confidence(img, result, FailingEngine(), threshold=0.6)
    assert [t.text for t in out.tokens] == ["x"]
    assert out.tokens[0].confidence == 0.2


# --- orchestrator -----------------------------------------------------------


def test_orchestrator_fallback_on_empty_primary():
    primary = StubEngine(empty_first=True)
    backup = StubEngine([("FB", (0, 0, 10, 10), 0.9)])
    doc = GeneralOCR([primary, backup])
    result = doc.recognize_image(np.zeros((20, 20, 3), dtype=np.uint8))
    assert result.engines_used == ["stub"]
    assert [t.text for t in result.tokens] == ["FB"]
    assert primary.calls == 1 and backup.calls == 1


def test_orchestrator_bbox_original_through_homography():
    tokens = [("A", (10, 10, 40, 30), 0.9)]
    doc = GeneralOCR([StubEngine(tokens)])
    log = TransformLog()
    dx, dy = 10.0, 20.0
    # processed -> original translate
    log.add("translate", np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], dtype=float))
    result = doc.recognize_image(np.zeros((50, 50, 3), dtype=np.uint8), transform_log=log)
    (tok,) = result.tokens
    assert tok.bbox_original == (10 + dx, 10 + dy, 40 + dx, 30 + dy)
    (block,) = result.pages[0]
    assert block.bbox_original == (10 + dx, 10 + dy, 40 + dx, 30 + dy)
    # processed coords unchanged
    assert tok.bbox == (10.0, 10.0, 40.0, 30.0)


def test_orchestrator_requires_engine():
    with pytest.raises(ValueError):
        GeneralOCR([])
