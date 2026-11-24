"""PDF report exporter: cover + one section per result.

Cover page: project, source files, extraction status, tables/fields counts.
Per result: embedded annotated preview thumbnail, extracted tables, fields,
raw-text blocks, warnings and validation issues. ReportLab-only (no images
beyond the embedded preview bitmap).
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from engine.export.base import ExportArtifact, ExportError, ExportOptions, artifact
from engine.schema.models import ExtractionResult

_STYLES = getSampleStyleSheet()
_BODY = ParagraphStyle(
    "body", parent=_STYLES["BodyText"], fontName="Helvetica", fontSize=9, leading=12
)
_HEAD = ParagraphStyle(
    "head", parent=_STYLES["Heading2"],
    fontName="Helvetica-Bold", fontSize=13, spaceAfter=4,
)
_REVIEW = ParagraphStyle("nr", parent=_BODY, textColor=colors.red)


class PdfExporter:
    name = "pdf"

    def export(
        self, result: ExtractionResult, out_path: Path | str, options: ExportOptions | None = None
    ) -> ExportArtifact:
        options = options or ExportOptions()
        out = Path(out_path)
        if out.suffix.lower() != ".pdf":
            raise ExportError(self.name, f"expected a .pdf path, got {out.name!r}")
        buf = io.BytesIO()
        title = f"Extraction report — {result.source.file_name if result.source else out.name}"
        doc = SimpleDocTemplate(
            buf, pagesize=A4, title=title,
            # Deterministic bytes: reportlab embeds a CreationDate by default.
            invariant=1,
        )
        story: list = []
        src = result.source.file_name if result.source else "(unknown)"

        # Cover
        story.append(Paragraph("Image Extraction Engine — report", _HEAD))
        story.append(Paragraph(f"Source: {src}", _BODY))
        story.append(Paragraph(
            f"Status: {result.extraction_status.value} · document_type: {result.document_type}"
            f" · tables: {len(result.tables)} · fields: {len(result.fields)}",
            _BODY,
        ))
        story.append(Spacer(1, 4 * mm))

        # Annotated preview (if the source image is reachable)
        if result.source is not None and result.source.file_name:
            base = options.image_dir
            src_path = (base / result.source.file_name) if base else Path(result.source.file_name)
            if src_path.is_file():
                with PILImage.open(src_path) as _im:
                    img = _im.convert("RGB").copy()
                img.thumbnail((480, 640))
                pimg = io.BytesIO()
                img.save(pimg, format="PNG")
                height = 120 * mm * img.height / max(img.width, 1)
                story.append(Image(pimg, width=120 * mm, height=height))
                story.append(Spacer(1, 4 * mm))

        for table in result.tables:
            story.append(Paragraph(f"Table: {table.table_name or '(unnamed)'}", _BODY))
            data: list[list] = []
            if table.columns:
                data.append(list(table.columns))
            data.extend([list(r) for r in table.rows])
            if table.cells and not table.rows:
                grid: dict[tuple[int, int], str] = {}
                for c in table.cells:
                    grid[(c.row_index, c.col_index)] = c.text or ""
                n_cols = max((c for _, c in grid), default=-1) + 1
                for r in range(max((r for r, _ in grid), default=-1) + 1):
                    data.append([grid.get((r, c), "") for c in range(n_cols)])
            if data:
                t = Table(data, colWidths=[(A4[0] - 40 * mm) / max(len(data[0]), 1)] * len(data[0]))
                t.setStyle(TableStyle([
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("FONT", (0, 0), (-1, -1), "Helvetica", 7),
                ]))
                story.append(t)
            if table.needs_review:
                story.append(Paragraph("needs review", _REVIEW))
            story.append(Spacer(1, 5 * mm))

        if result.fields:
            story.append(Paragraph("Fields", _BODY))
            for f in result.fields:
                review = " [needs review]" if f.needs_review else ""
                story.append(Paragraph(f"• {f.name}: {f.value!r}{review}", _BODY))
            story.append(Spacer(1, 5 * mm))

        if result.warnings or result.validation_results:
            story.append(Paragraph("Warnings & validation", _BODY))
            for w in result.warnings:
                story.append(Paragraph(f"• [warning] {w}", _BODY))
            for v in result.validation_results:
                story.append(Paragraph(f"• [{v.severity}] {v.id}: {v.message}", _BODY))
            story.append(Spacer(1, 5 * mm))

        story.append(PageBreak())
        doc.build(story)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(buf.getvalue())
        return artifact(out, "application/pdf")


def make():
    return PdfExporter()
