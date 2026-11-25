"""P2 tests: OCR backends, reading order, PDF fast path, multiscale, orchestrator."""

from __future__ import annotations

import cv2
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
    _write_text_layer_pdf_pages(path, [text])


def _write_text_layer_pdf_pages(path, texts: list[str]) -> None:
    n = len(texts)
    objs: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>"
        % (b" ".join(b"%d 0 R" % (3 + 2 * i) for i in range(n)), n),
    ]
    for i, text in enumerate(texts):
        content = f"BT /F1 24 Tf 72 {700 - 40 * i} Td ({text}) Tj ET".encode()
        objs.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
            b"/Resources << /Font << /F1 %d 0 R >> >> >>"
            % (4 + 2 * i, 3 + 2 * n)
        )
        objs.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content))
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
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


def test_pdf_pages_carry_page_index_and_scale_into_prov(tmp_path):
    from engine.schema import BBox, Provenance

    pdf = str(tmp_path / "two.pdf")
    _write_text_layer_pdf_pages(pdf, ["FIRST PAGE TEXT", "SECOND PAGE TEXT"])

    # Page 0 rendered at 150 DPI, page 1 at 300 DPI (per-page renders).
    pages_low = extract_pdf_pages(pdf, dpi=150)
    pages_high = extract_pdf_pages(pdf, dpi=300)
    assert [p.page_index for p in pages_low] == [0, 1]

    provs: list[Provenance] = []
    page_sizes: list[tuple[float, float]] = []
    for page, dpi in ((pages_low[0], 150), (pages_high[1], 300)):
        (block,) = tokens_to_blocks(page.tokens)
        assert block.page_index == page.page_index
        assert block.scale == pytest.approx(dpi / 72.0)
        x0, y0, x1, y1 = block.bbox
        provs.append(
            Provenance(
                page=block.page_index,
                bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1),
                scale=block.scale,
            )
        )
        page_sizes.append((612 * dpi / 72.0, 792 * dpi / 72.0))

    for prov, (w, h) in zip(provs, page_sizes, strict=True):
        assert prov.scale in (150 / 72, 300 / 72)
        # Boxes land inside the page's rendered pixel size.
        assert 0 <= prov.bbox.x0 < prov.bbox.x1 <= w
        assert 0 <= prov.bbox.y0 < prov.bbox.y1 <= h


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
    # Space/unit bookkeeping on the recorded step.
    (entry,) = log.entries
    assert entry.unit == "px"
    assert entry.space_from == "processed"
    assert entry.space_to == "original"


def test_orchestrator_requires_engine():
    with pytest.raises(ValueError):
        GeneralOCR([])


# --- industrial pipeline: real photo must yield text (OCR-HMI fix) ----------


def _hmi_like_image() -> np.ndarray:
    """Rendered screen with several text lines (NOT a 1x1 placeholder)."""
    img = Image.new("RGB", (640, 400), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 639, 399), outline="black", width=3)
    for i, line in enumerate(
        ("PUMP STATION 3", "MOTOR SPEED 1200 RPM", "TEMP 45.5 C", "ALARM: NONE")
    ):
        draw.text((20, 30 + i * 60), line, fill="black", font=_font(30))
    return np.asarray(img)


def test_industrial_vision_generic_hmi_returns_text_blocks():
    from engine.industrial.pipeline import IndustrialVision
    from engine.preprocessing.pipeline import PreprocessingPipeline

    vision = IndustrialVision(
        preprocessing=PreprocessingPipeline.from_dict("industrial", {}),
        ocr=GeneralOCR([TesseractEngine()]),
    )
    result = vision.process(_hmi_like_image(), file_name="hmi.png")
    assert result.text_blocks, "expected non-empty text_blocks for a text-bearing HMI image"
    joined = " ".join(b.text for b in result.text_blocks)
    assert "MOTOR" in joined and "1200" in joined


# --- coil-table fix: gutter noise columns, toolbar header, duplicate warnings


def _coil_like_image() -> np.ndarray:
    """Rendered coil-list screen: toolbar strip above the table, a
    checkbox-gutter column with no alphanumeric data, and known data rows."""
    img = Image.new("RGB", (760, 460), "white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 8), "View Coils in Cold Rolling Work Unit", fill="black", font=_font(18))
    # toolbar rows ABOVE the table (would be garbage if read as header/data)
    draw.text((20, 40), "Fac: 1CRM   Oper: PCM   Type: Confirm", fill="black", font=_font(16))
    headers = ["", "SEQ", "C.COIL", "Thickness", "Weight", "Dest Name"]
    data = [
        ("", "001", "97CB0774", "4.000", "21080", "LONG AN"),
        ("", "002", "97CA9601", "4.500", "16725", "PORT KELANG"),
        ("", "003", "97CA9602", "4.000", "24505", "PORT KELANG"),
    ]
    x0, y0, col_w, row_h = 20, 80, 120, 40
    # column separators (incl. the checkbox gutter at x0)
    for c in range(len(headers) + 1):
        draw.line((x0 + c * col_w, y0, x0 + c * col_w, y0 + row_h * (len(data) + 2)), fill="black")
    # header + toolbar-noise row + len(data) data rows need len(data)+3 lines
    for r in range(len(data) + 3):
        draw.line((x0, y0 + r * row_h, x0 + len(headers) * col_w, y0 + r * row_h), fill="black")
    for c, head in enumerate(headers):
        draw.text((x0 + c * col_w + 8, y0 + 8), head, fill="black", font=_font(16))
    # row 0 of the grid: toolbar remnants (non-alphanumeric cells)
    noise = ["[v]", "---", "___", "___", "___", "-----"]
    for c, cell in enumerate(noise):
        draw.text((x0 + c * col_w + 8, y0 + row_h + 8), cell, fill="black", font=_font(16))
    for r, row in enumerate(data):
        for c, cell in enumerate(row):
            if cell:
                draw.text(
                    (x0 + c * col_w + 8, y0 + row_h * (r + 2) + 8),
                    cell, fill="black", font=_font(16),
                )
    return np.asarray(img)


def test_coil_table_drops_noise_columns_and_toolbar_rows():
    from engine.industrial.pipeline import IndustrialVision

    vision = IndustrialVision(ocr=GeneralOCR([TesseractEngine()]))
    result = vision.process(_coil_like_image(), file_name="coil-list.png")
    assert result.tables, "expected a table for a ruled coil-list image"
    table = result.tables[0]
    headers = [h.lower() for h in table.columns]
    # the checkbox gutter column (empty header, no alphanumeric data) is gone
    assert "seq" in headers, f"gutter/noise columns not dropped: {table.columns}"
    joined = " ".join(table.columns).lower()
    assert "97cb0774" not in joined, "a data value leaked into the header row"
    body = "\n".join(" ".join(row) for row in table.rows)
    # toolbar strip above the table is not emitted as a data row
    assert "fac" not in body and "1crm" not in body, "toolbar row leaked into data rows"
    # Tesseract misreads glyphs in the id (e.g. '97CB0774' -> '97CB0O774'):
    # OCR accuracy is out of scope for this fix, so assert the stable
    # prefix/suffix rather than exact glyph-level output
    assert any(
        "97CB" in cell.upper() and "774" in cell.upper()
        for row in table.rows
        for cell in row
    ), "coil id row 97CB0774 missing from data rows"
    # the last drawn data row (003) must be inside the grid, not clipped
    assert any(
        "97CA" in cell.upper() and "9602" in cell.upper()
        for row in table.rows
        for cell in row
    ), "third data row 003 clipped from the grid"
    # each warning text appears once
    assert len(result.warnings) == len(set(result.warnings)), "duplicate warnings"


# --- image correction on real screen photos (deskew / perspective / deblur)


def test_deskew_straightens_known_rotation():
    """Brief: 5-degree skewed image — deskew straightens within tolerance."""
    from engine.preprocessing import transforms as tx

    img = _hmi_like_image()
    rotated, _ = tx.rotate(img, tx.RotateConfig(angle=-5.0))
    skew = tx.deskew_angle(rotated)
    assert skew is not None
    assert abs(skew - 5.0) < 1.0, f"detected {skew:.2f} deg, expected ~5"


def test_sharpen_runs_on_quality_flagged_blur_only():
    """Brief: synthetic blurred image — sharpen runs when the quality flag
    fires and stays a no-op on clean input."""
    from engine.preprocessing.pipeline import PreprocessingPipeline

    pipe = PreprocessingPipeline.from_dict(
        "sharp", {"sharpen": {"strength": 0.8, "radius": 3}}
    )
    clean = _hmi_like_image()
    blurry = cv2.GaussianBlur(clean, (0, 0), 5.0)

    out_clean = pipe.run(clean)
    out_blur = pipe.run(blurry)
    assert "skipped" in out_clean.step_info["sharpen"], (
        "sharpen must not run on clean input"
    )
    assert "skipped" not in out_blur.step_info["sharpen"], (
        "sharpen must run on a blurry photo"
    )


def test_blur_flag_uses_resolution_normalized_variance():
    """A genuinely blurry high-res photo must flag BLURRY (the raw Laplacian
    variance scales with resolution and masked it before)."""
    from engine.preprocessing.quality import QualityWarning, compute_quality

    big = np.asarray(Image.fromarray(_hmi_like_image()).resize((3000, 1875)))
    blurry = cv2.GaussianBlur(big, (0, 0), 5.0)
    report = compute_quality(blurry)
    assert QualityWarning.BLURRY in report.warnings
    assert report.blur_variance_normalized < 100.0


def test_perspective_falls_back_to_border_lines():
    """Glare-broken screen outline: the quad detector must still find the
    screen via the border-line / gradient fallback, and the enhancement
    pipeline must run to completion.

    Uses a synthetic photographed-screen image (bright rectangle on a dark
    bezel, with text-like strokes) instead of a real photo: the previous
    version loaded /tmp/tcm-plc.jpg, a file that exists only on LV3, so CI
    on GitHub-hosted runners failed with FileNotFoundError.
    """
    import numpy as np

    from engine.industrial.screen import _border_line_quad

    img = np.full((600, 800, 3), 40, dtype=np.uint8)
    img[80:520, 100:700] = 210
    # Text-like dark strokes inside the screen, so the OCR pass has content.
    for y in (140, 200, 260, 320):
        img[y : y + 18, 140:560] = 60
    quad = _border_line_quad(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY))
    assert quad is not None, "border-line fallback should find the screen quad"
    from engine.industrial.pipeline import IndustrialVision

    vision = IndustrialVision(ocr=GeneralOCR([TesseractEngine()]))
    result = vision.process(img, file_name="synthetic-screen.jpg")
    corrections = result.extensions["industrial"]["corrections"]
    assert corrections["profile"] == "industrial_screen_photo"
    assert "screen boundary not detected" not in " ".join(result.warnings)
