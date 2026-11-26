"""D2 tests: input backend registry (engine/backends)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from engine.backends import (
    PillowImageBackend,
    PypdfiumPdfBackend,
    UnsupportedInputError,
    get_backend,
)
from engine.preprocessing.io import _from_pdf, _sha256_of


def _write_two_page_pdf(path: Path) -> None:
    first = Image.new("RGB", (200, 100), "white")
    second = Image.new("RGB", (150, 120), "white")
    first.save(path, "PDF", save_all=True, append_images=[second])


def test_pdf_resolves_to_pypdfium_backend():
    assert isinstance(get_backend(Path("x.pdf")), PypdfiumPdfBackend)


def test_image_extensions_resolve_to_pillow_backend():
    for suffix in (".png", ".jpg", ".webp"):
        assert isinstance(get_backend(Path(f"x{suffix}")), PillowImageBackend)


def test_unsupported_format_raises_structured_error():
    with pytest.raises(UnsupportedInputError) as excinfo:
        get_backend(Path("x.docx"))
    assert excinfo.value.format == ".docx"
    assert excinfo.value.supported


def test_old_and_new_pdf_paths_give_identical_loads(tmp_path):
    """The deprecated _from_pdf() alias and the registry path agree byte for byte."""
    pdf = tmp_path / "two.pdf"
    _write_two_page_pdf(pdf)
    sha256 = _sha256_of(pdf)
    old = _from_pdf(pdf, sha256, 150)
    new = get_backend(pdf).load(pdf, dpi=150)
    assert [p.page for p in old] == [0, 1]
    assert [p.page for p in new] == [0, 1]
    assert [p.sha256 for p in old] == [sha256] * 2
    assert [p.sha256 for p in new] == [sha256] * 2
    for a, b in zip(old, new):
        assert a.data.shape == b.data.shape
        assert a.data.tobytes() == b.data.tobytes()


def test_pagination_and_page_count(tmp_path):
    pdf_backend = PypdfiumPdfBackend()
    image_backend = PillowImageBackend()
    assert pdf_backend.supports_pagination() is True
    assert image_backend.supports_pagination() is False
    pdf = tmp_path / "two.pdf"
    _write_two_page_pdf(pdf)
    assert pdf_backend.page_count(pdf) == 2
    png = tmp_path / "one.png"
    Image.new("RGB", (60, 40), "white").save(png, "PNG")
    assert image_backend.page_count(png) == 1
