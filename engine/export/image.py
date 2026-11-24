"""Image preview exporter: annotated JPEG/PNG copy of the source page.

Draws table grids, field bboxes and text blocks, colour-coded by confidence
(green ≥ 0.8, yellow ≥ 0.7, red below or unknown), plus a legend. Optional
per-field crop thumbnails (``options.field_crops``). The source file is
never modified.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from engine.export.base import ExportArtifact, ExportError, ExportOptions, artifact, conf_band
from engine.schema.models import ExtractionResult

_COLORS = {
    "table": (30, 30, 220),
    "field": (30, 140, 30),
    "text": (140, 140, 140),
}
_BAND_COLORS = {"green": (30, 170, 60), "yellow": (230, 190, 30), "red": (220, 50, 50)}


class ImageExporter:
    name = "jpg"

    def __init__(self, image_dir: Path | str | None = None) -> None:
        self.image_dir = Path(image_dir) if image_dir else None

    def _source(self, result: ExtractionResult, options: ExportOptions) -> Path:
        if result.source is None or not result.source.file_name:
            raise ExportError(self.name, "result has no source file to preview")
        base = options.image_dir or self.image_dir
        if base is not None and not isinstance(base, Path):
            base = Path(base)
        src = (base / result.source.file_name) if base else Path(result.source.file_name)
        if not src.is_file():
            raise ExportError(self.name, f"source image not found: {src}")
        return src

    def export(
        self, result: ExtractionResult, out_path: Path | str, options: ExportOptions | None = None
    ) -> ExportArtifact:
        options = options or ExportOptions()
        out = Path(out_path)
        if out.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            raise ExportError(self.name, f"expected a .jpg/.png path, got {out.name!r}")
        with Image.open(self._source(result, options)) as _im:
            img = _im.convert("RGB").copy()
        draw = ImageDraw.Draw(img)

        def box(bbox, color, label):
            draw.rectangle([bbox.x0, bbox.y0, bbox.x1, bbox.y1], outline=color, width=2)
            if label:
                draw.text((bbox.x0 + 2, max(0, bbox.y0 - 10)), label, fill=color)

        for t in result.tables:
            if t.bbox:
                box(t.bbox, _COLORS["table"], f"table {t.table_name or ''}".strip())
            for c in t.cells:
                if c.bbox and c.confidence is not None:
                    box(c.bbox, _BAND_COLORS[conf_band(c.confidence)], None)
        for f in result.fields:
            if f.bbox:
                if f.confidence is not None:
                    color = _BAND_COLORS[conf_band(f.confidence)]
                else:
                    color = _COLORS["field"]
                box(f.bbox, color, str(f.name))
        for b in result.text_blocks:
            if b.bbox:
                box(b.bbox, _COLORS["text"], None)

        # legend
        lx, ly = 6, img.height - 46
        legend = (("green", "conf >= 0.8"), ("yellow", "0.7-0.8"), ("red", "< 0.7 / review"))
        for i, (band, label) in enumerate(legend):
            y = ly + i * 14
            draw.rectangle([lx, y, lx + 10, y + 10], outline=_BAND_COLORS[band], width=2)
            draw.text((lx + 16, y), label, fill=(0, 0, 0))

        if options.field_crops and result.fields:
            crops_dir = out.parent / f"{out.stem}_field_crops"
            crops_dir.mkdir(parents=True, exist_ok=True)
            for i, f in enumerate(result.fields):
                if f.bbox and f.name:
                    x0, y0 = max(0, int(f.bbox.x0) - 4), max(0, int(f.bbox.y0) - 4)
                    x1, y1 = min(img.width, int(f.bbox.x1) + 4), min(img.height, int(f.bbox.y1) + 4)
                    if x1 > x0 and y1 > y0:
                        img.crop((x0, y0, x1, y1)).save(crops_dir / f"{i:02d}_{f.name}.png")

        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, quality=90) if out.suffix.lower() != ".png" else img.save(out)
        return artifact(out, "image/png" if out.suffix.lower() == ".png" else "image/jpeg")


def make():
    return ImageExporter()
