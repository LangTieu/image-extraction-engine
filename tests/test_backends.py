"""D2 tests: input backend registry (engine/backends)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from engine.backends import (
    PillowImageBackend,
    PypdfiumPdfBackend,
    UnsupportedInputError,
    clear_registry,
    get_backend,
    register_backend,
    registered_backends,
    unregister_backend,
)
from engine.backends.base import InputBackend
from engine.backends.image import IMAGE_EXTENSIONS
from engine.ocr.pdf import PdfiumTextLayer
from engine.preprocessing.errors import CorruptImageError, SourceNotFoundError
from engine.preprocessing.io import _from_pdf, _sha256_of, load_input


def _write_two_page_pdf(path: Path) -> None:
    first = Image.new("RGB", (200, 100), "white")
    second = Image.new("RGB", (150, 120), "white")
    first.save(path, "PDF", save_all=True, append_images=[second])


# ---------------------------------------------------------------- registry


def test_pdf_resolves_to_pypdfium_backend():
    assert isinstance(get_backend(Path("x.pdf")), PypdfiumPdfBackend)


def test_image_extensions_resolve_to_pillow_backend():
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        assert isinstance(get_backend(Path(f"x{suffix}")), PillowImageBackend)


def test_extension_matching_is_case_insensitive():
    for name in ("PHOTO.PNG", "photo.JPG", "doc.Pdf"):
        backend = get_backend(Path(name))
        assert isinstance(backend, (PillowImageBackend, PypdfiumPdfBackend))


def test_unsupported_format_raises_structured_error():
    with pytest.raises(UnsupportedInputError) as excinfo:
        get_backend(Path("x.docx"))
    assert excinfo.value.format == ".docx"
    assert excinfo.value.supported


def test_extension_wins_over_mime():
    """A known extension decides even when the MIME says something else."""
    backend = get_backend(Path("x.png"), mime="application/pdf")
    assert isinstance(backend, PillowImageBackend)


def test_mime_used_only_without_extension():
    backend = get_backend(Path("stream"), mime="application/pdf")
    assert isinstance(backend, PypdfiumPdfBackend)


def test_mime_parameters_are_stripped():
    backend = get_backend(Path("stream"), mime="Application/PDF; charset=binary")
    assert isinstance(backend, PypdfiumPdfBackend)


def test_unknown_mime_without_extension_raises():
    with pytest.raises(UnsupportedInputError) as excinfo:
        get_backend(Path("stream"), mime="application/x-unknown")
    assert excinfo.value.mime == "application/x-unknown"
    assert excinfo.value.format == "application/x-unknown"
    assert excinfo.value.supported


def test_registry_replaces_same_name_and_unregister_works():
    original = registered_backends()
    try:
        duplicate = PypdfiumPdfBackend()
        register_backend(duplicate)
        names = [backend.name for backend in registered_backends()]
        assert names.count("pypdfium2") == 1
        assert unregister_backend("pypdfium2") is True
        assert unregister_backend("pypdfium2") is False
        assert all(backend.name != "pypdfium2" for backend in registered_backends())
        with pytest.raises(UnsupportedInputError):
            get_backend(Path("x.pdf"))
    finally:
        clear_registry()
        for backend in original:
            register_backend(backend)
    # defaults usable again
    assert isinstance(get_backend(Path("x.pdf")), PypdfiumPdfBackend)


def test_register_rejects_non_protocol_object():
    class NotABackend:
        pass

    with pytest.raises(TypeError):
        register_backend(NotABackend())


def test_custom_backend_keeps_first_match_priority():
    class StubBackend(InputBackend):
        name = "stub"

        def supported_formats(self) -> frozenset[str]:
            return frozenset({".png"})

        def is_valid(self, path: Path) -> bool:
            return True

        def supports_pagination(self) -> bool:
            return False

        def page_count(self, path: Path) -> int:
            return 1

        def load(self, path: Path, *, dpi: int) -> list:
            return []

    original = registered_backends()
    try:
        register_backend(StubBackend())
        assert isinstance(get_backend(Path("a.png")), StubBackend)
    finally:
        unregister_backend("stub")
        # Pillow must resolve .png again
        assert isinstance(get_backend(Path("a.png")), PillowImageBackend)
        assert [b.name for b in original]  # original snapshot untouched


# ---------------------------------------------------------------- backends


def test_pillow_rejects_unknown_extension():
    backend = PillowImageBackend()
    with pytest.raises(UnsupportedInputError):
        backend.load(Path("x.tif"), dpi=150)


def test_load_on_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        PypdfiumPdfBackend().load(tmp_path / "missing.pdf", dpi=150)
    with pytest.raises(FileNotFoundError):
        PillowImageBackend().load(tmp_path / "missing.png", dpi=150)


def test_pillow_page_count_counts_frames(tmp_path):
    colors = ["red", "green", "blue"]
    frames = [Image.new("RGB", (40, 30), color) for color in colors]
    gif = tmp_path / "anim.gif"
    frames[0].save(gif, "GIF", save_all=True, append_images=frames[1:], loop=0)
    with Image.open(gif) as handle:
        expected = getattr(handle, "n_frames", 1)
    assert expected > 1
    assert PillowImageBackend().page_count(gif) == expected


def test_image_page_count_on_corrupt_file(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a png")
    with pytest.raises(CorruptImageError):
        PillowImageBackend().page_count(bad)


def test_pdfium_page_count_on_corrupt_file(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    with pytest.raises(CorruptImageError):
        PypdfiumPdfBackend().page_count(bad)


def test_text_layer_has_name():
    assert PdfiumTextLayer().name == "pypdfium2"


# ------------------------------------------------- equivalence vs oracle


@pytest.fixture(scope="module")
def reportlab_pdf(tmp_path_factory):
    """Two-page PDF built with reportlab: an oracle independent of Pillow.

    reportlab draws vector text; Pillow only rasterizes, so a match between
    the two is real cross-checking, not Pillow checking itself.
    """
    from reportlab.pdfgen import canvas

    path = tmp_path_factory.mktemp("oracle") / "oracle.pdf"
    c = canvas.Canvas(str(path), pagesize=(200, 100))
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, 200, 100, fill=1, stroke=0)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(20, 50, "hello page one")
    c.showPage()
    c.setPageSize((150, 120))
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, 150, 120, fill=1, stroke=0)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(20, 60, "page two")
    c.showPage()
    c.save()
    return path


def test_backend_matches_independent_oracle_pixels(reportlab_pdf):
    """Rasterized pages agree with a reportlab-rendered reference bitmap."""
    import numpy as np
    import pypdfium2 as pdfium

    dpi = 72  # scale 1.0: reportlab points == rendered pixels
    loaded = get_backend(reportlab_pdf).load(reportlab_pdf, dpi=dpi)
    pdf = pdfium.PdfDocument(reportlab_pdf)
    try:
        assert pdfium.PdfDocument(reportlab_pdf) is not None
        for index, page in enumerate(pdf):
            reference = page.render(scale=dpi / 72.0).to_pil().convert("RGB")
            actual = Image.fromarray(loaded[index].data)
            assert actual.size == reference.size
            diff = np.asarray(actual, dtype=int) - np.asarray(reference, dtype=int)
            assert int(np.abs(diff).max()) <= 1
            assert loaded[index].sha256 == _sha256_of(reportlab_pdf)
            assert loaded[index].page == index
    finally:
        pdf.close()


def test_load_input_equals_backend_load(reportlab_pdf):
    dpi = 100
    via_loader = load_input(reportlab_pdf, dpi=dpi)
    via_backend = get_backend(reportlab_pdf).load(reportlab_pdf, dpi=dpi)
    assert [p.page for p in via_loader] == [p.page for p in via_backend] == [0, 1]
    assert [p.format for p in via_loader] == ["pdf", "pdf"]
    for a, b in zip(via_loader, via_backend):
        assert a.data.tobytes() == b.data.tobytes()
        assert a.sha256 == b.sha256


def test_old_and_new_pdf_paths_give_identical_loads(reportlab_pdf):
    """The deprecated _from_pdf() alias and the registry path agree byte for byte."""
    dpi = 150
    old = _from_pdf(reportlab_pdf, _sha256_of(reportlab_pdf), dpi)
    new = get_backend(reportlab_pdf).load(reportlab_pdf, dpi=dpi)
    assert [p.page for p in old] == [0, 1]
    for a, b in zip(old, new):
        assert a.data.tobytes() == b.data.tobytes()
        assert a.sha256 == b.sha256


def test_load_input_missing_file_raises_source_not_found(tmp_path):
    with pytest.raises(SourceNotFoundError):
        load_input(tmp_path / "nope.png")


def test_load_input_image_path(tmp_path):
    png = tmp_path / "photo.png"
    Image.new("RGB", (60, 40), (10, 20, 30)).save(png, "PNG")
    (loaded,) = load_input(png)
    assert loaded.page is None
    assert loaded.format == "png"
    assert loaded.data.shape == (40, 60, 3)


def test_load_input_jpeg_extension(tmp_path):
    jpg = tmp_path / "photo.jpeg"
    Image.new("RGB", (30, 20), "white").save(jpg, "JPEG")
    (loaded,) = load_input(jpg)
    assert loaded.format == "jpg"
    assert loaded.page is None


def test_supported_formats_declare_image_mimes():
    formats = PillowImageBackend().supported_formats()
    assert {"image/jpeg", "image/png", "image/webp"} <= formats
    assert IMAGE_EXTENSIONS <= formats
