"""Generate the P0 seed benchmark set: placeholder images + ground truth.

Usage: python -m benchmark.tools.generate_seed [output_dir]

Creates, for each required content class, 5 samples per category:
a small valid placeholder PNG under <cat>/images/ and a ground-truth JSON
under <cat>/ground_truth/ that validates against the unified schema.
Real images replace the placeholders in P1+ without changing ground truth
format. Idempotent: overwrites the seed set each run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from engine.schema import (
    BBox,
    ExtractionResult,
    ExtractionStatus,
    FieldValue,
    ProcessingMeta,
    SourceInfo,
    Table,
    TextBlock,
)

# 1x1 white PNG (valid image bytes for a placeholder). The earlier hand-typed
# hex was a truncated copy that PIL rejects ("broken PNG file"); this one is
# produced by Pillow and verified loadable.
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
    "0000000c49444154789c63f8ffff3f0005fe02fe0def46b80000000049454e44ae426082"
)

# P0-required content classes, at 5 samples each.
CATEGORIES: dict[str, str] = {
    "photo_document": "Photographed (not scanned) document",
    "form": "Structured form",
    "table_image": "Dense small-font table",
    "screenshot_desktop": "Desktop screenshot",
    "screenshot_mobile": "Mobile screenshot",
    "industrial_hmi": "Angled PLC/HMI screen photo",
    "coil_table": "Coil production table",
}

VI_TEXTS = [
    "Hóa đơn giá trị gia tăng",
    "Khách hàng: Công ty TNHH Thép Việt",
    "Tổng cộng: 12.500.000 VND",
]
EN_TEXTS = ["Invoice number", "Total amount", "Customer signature"]


def make_result(category: str, index: int) -> ExtractionResult:
    file_name = f"{category}_{index:03d}.png"
    texts = VI_TEXTS + EN_TEXTS
    blocks = [
        TextBlock(
            text=t,
            language="vi" if i < len(VI_TEXTS) else "en",
            confidence=1.0,
            bbox=BBox(x0=0, y0=i * 20, x1=400, y1=i * 20 + 18),
        )
        for i, t in enumerate(texts)
    ]
    fields: list[FieldValue] = []
    tables: list[Table] = []
    if category == "coil_table":
        columns = [
            "ZONE",
            "HOT_COIL_NO",
            "COLD_COIL_NO",
            "THICK",
            "WIDTH",
            "WEIGHT",
            "LENGTH",
            "PRODUCT_CODE",
        ]
        rows: list[list[str | None]] = [
            ["ZA", f"H{index:05d}", f"C{index:05d}", "1.20", "1250", "15000", "620", "SPHC"],
            ["ZA", f"H{index + 1:05d}", f"C{index + 1:05d}", "0.80", "1000", "9800", "540", "SPCC"],
        ]
        tables.append(Table(table_name="coil_list", columns=columns, rows=rows, confidence=1.0))
        fields = [
            FieldValue(
                name="HOT_COIL_NO",
                value=f"H{index:05d}",
                raw_text=f"H{index:05d}",
                type="id",
                confidence=1.0,
            ),
            FieldValue(
                name="THICK",
                value=1.2,
                raw_text="1.20",
                unit="mm",
                type="number",
                confidence=1.0,
            ),
        ]
    elif category == "form":
        fields = [
            FieldValue(
                name="customer_name",
                value="Cong ty TNHH Thep Viet",
                raw_text="Cong ty TNHH Thep Viet",
                type="string",
                confidence=1.0,
            ),
            FieldValue(
                name="invoice_number",
                value="2026/000123",
                raw_text="2026/000123",
                type="id",
                confidence=1.0,
            ),
        ]
    return ExtractionResult(
        document_type=category,
        extraction_status=ExtractionStatus.COMPLETED,
        source=SourceInfo(file_name=file_name, page=1, sha256=None),
        text_blocks=blocks,
        tables=tables,
        fields=fields,
        warnings=[],
        exports=["json", "xlsx"],
        processing=ProcessingMeta(
            pipeline_path=["router", "preprocessing", "general"],
            module_versions={"engine": "0.0.1"},
            timings_ms={"total": 0.0},
        ),
    )


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("benchmark/seed")
    count = 0
    for category, description in CATEGORIES.items():
        image_dir = root / category / "images"
        gt_dir = root / category / "ground_truth"
        image_dir.mkdir(parents=True, exist_ok=True)
        gt_dir.mkdir(parents=True, exist_ok=True)
        (root / category / "README.md").write_text(
            f"# {category}\n\n{description}\n\n"
            "Images are synthetic placeholders; replace with real samples in P1+.\n"
            "Ground-truth JSON validates against the unified schema "
            "(`engine/schema/models.py`).\n",
            encoding="utf-8",
        )
        for index in range(1, 6):
            file_name = f"{category}_{index:03d}.png"
            (image_dir / file_name).write_bytes(PNG_1X1)
            result = make_result(category, index)
            assert result.source is not None  # make_result always sets it
            result.source.sha256 = None
            (gt_dir / f"{file_name}.json").write_text(
                json.dumps(result.model_dump(exclude_none=True), ensure_ascii=False, indent=2)
                + "\n",  # noqa: E501
                encoding="utf-8",
            )
            count += 1
    print(f"wrote {count} samples across {len(CATEGORIES)} categories under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
