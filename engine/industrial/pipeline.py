"""Industrial Vision orchestrator (P4).

``IndustrialVision.process``: router decision/profile in, unified-schema
``ExtractionResult`` out. Fallback per brief item 9: when no profile
matches, parse as generic HMI (``industrial_hmi``) and record a
``NO_PROFILE_MATCHED`` warning. Unknown values are never guessed; they are
flagged with ``needs_review`` / parse notes.
"""

from __future__ import annotations

import re
import time
from typing import Any

import numpy as np

from engine.industrial import alarms as alarm_mod
from engine.industrial.compact_ocr import WHITELISTS, read_compact, shallow_text
from engine.industrial.profiles import IndustrialProfile, match_profile
from engine.industrial.regions import (
    DetectorModelHook,
    Region,
    RegionType,
    UnavailableDetectorHook,
    detect_regions,
)
from engine.industrial.screen import normalize_screen
from engine.industrial.values import parse_value_unit
from engine.ocr.base import OCRToken
from engine.ocr.pipeline import GeneralOCR
from engine.preprocessing.pipeline import PreprocessingPipeline
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
from engine.schema.industrial_fields import DEFAULT_FIELDS, validate_value

MODULE_VERSION = "p4-industrial-0.1.0"

INDUSTRIAL_CATEGORIES = (
    "machine_label",
    "alarm_screen",
    "coil_table",
    "process_diagram",
    "industrial_hmi",
)


class IndustrialVision:
    """Industrial screen/photo parser built on P1-P3 public interfaces."""

    def __init__(
        self,
        preprocessing: PreprocessingPipeline | None = None,
        ocr: GeneralOCR | None = None,
        profiles: list[IndustrialProfile] | None = None,
        detector_hook: DetectorModelHook | None = None,
        review_thresholds: Any | None = None,
        review_backend: Any | None = None,
        quality_hook: Any | None = None,
    ) -> None:
        self.profiles = profiles  # None -> bundled profiles loaded lazily
        self.detector_hook = detector_hook or UnavailableDetectorHook()
        self._preprocessing = preprocessing
        self._ocr = ocr
        from engine.validation.review import ReviewThresholds

        self.review_thresholds = review_thresholds or ReviewThresholds()
        self.review_backend = review_backend  # None -> validation only, no queue
        self.quality_hook = quality_hook  # optional callable image -> [0, 1]

    def _profile_pool(self) -> list[IndustrialProfile] | None:
        if self.profiles is not None:
            return self.profiles
        from engine.industrial.profiles import bundled_profiles

        return bundled_profiles()

    def process(
        self,
        image: np.ndarray,
        file_name: str = "industrial_input.png",
        force_rectify: bool = False,
    ) -> ExtractionResult:
        started = time.perf_counter()
        warnings: list[str] = []

        report = normalize_screen(image, force_rectify=force_rectify)
        warnings.extend(report.warnings)
        working = report.rectified

        # One whole-frame OCR pass, shared by profile matching and (on the
        # generic-HMI fallback) text_blocks. Running recognize_image twice
        # doubled the wall time for no extra information.
        ocr_document = self._ocr.recognize_image(working) if self._ocr is not None else None
        profile_text = (
            " ".join(t.text for t in ocr_document.tokens) if ocr_document else shallow_text(working)
        )
        profile = match_profile(profile_text, profiles=self._profile_pool())
        if profile is None:
            warnings.append("NO_PROFILE_MATCHED: falling back to generic industrial_hmi parsing")

        regions = detect_regions(working, model_hook=self.detector_hook)
        tables = self._extract_coil_tables(working, profile, warnings)
        fields = self._extract_fields(working, regions, profile)
        alarm_entries = self._extract_alarms(working, regions)

        # Generic-HMI fallback: heuristics found no typed regions (no
        # LABEL_VALUE etc.), so without this the OCR text discovered above
        # was thrown away and the result came back with zero text. The
        # whole-frame blocks go into text_blocks; the OCR pass is reused,
        # not repeated.
        text_blocks: list[TextBlock] = []
        if profile is None and ocr_document is not None:
            for block in ocr_document.pages[0] if ocr_document.pages else []:
                if not re.search(r"[A-Za-z0-9]", block.text):
                    continue  # punctuation/noise-only lines from screen glare
                text_blocks.append(
                    TextBlock(
                        text=block.text,
                        bbox=BBox(
                            x0=block.bbox[0], y0=block.bbox[1], x1=block.bbox[2], y1=block.bbox[3]
                        )
                        if block.bbox
                        else None,
                        reading_order=block.reading_order,
                        confidence=block.confidence,
                    )
                )

        if any(f.needs_review for f in fields):
            # A field flagged by parse notes / format_regex failures must
            # escalate the whole result to NEEDS_REVIEW.
            status = ExtractionStatus.NEEDS_REVIEW
        elif warnings:
            status = ExtractionStatus.COMPLETED_WITH_WARNINGS
        else:
            status = ExtractionStatus.COMPLETED
        result = ExtractionResult(
            document_type=(
                profile.categories[0] if profile and profile.categories else "industrial_hmi"
            ),
            extraction_status=status,
            source=SourceInfo(file_name=file_name, page=1),
            tables=tables,
            fields=fields,
            text_blocks=text_blocks,
            warnings=warnings,
            processing=ProcessingMeta(
                pipeline_path=["industrial"],
                module_versions={"industrial": MODULE_VERSION},
                timings_ms={"total": round((time.perf_counter() - started) * 1000, 2)},
            ),
            extensions={
                "industrial": {
                    "profile": profile.name if profile else None,
                    "regions": [self._region_dict(r) for r in regions],
                    "screen": {
                        "moire_score": round(report.moire_score, 4),
                        "glare_ratio": round(report.glare_ratio, 4),
                        "perspective_corrected": report.transform is not None,
                    },
                    "alarms": [self._alarm_dict(a) for a in alarm_entries],
                }
            },
        )

        # P5: validation, confidence and review queue on the final result.
        from engine.validation.validate_result import validate_result

        quality = None
        if self.quality_hook is not None:
            quality = self.quality_hook(working)
        result = validate_result(
            result,
            profile_name=profile.name if profile else None,
            thresholds=self.review_thresholds,
            review_backend=self.review_backend,
            quality_score=quality,
        )
        if result.extraction_status == ExtractionStatus.NEEDS_REVIEW:
            status = ExtractionStatus.NEEDS_REVIEW
        elif result.extraction_status == ExtractionStatus.COMPLETED_WITH_WARNINGS or warnings:
            status = ExtractionStatus.COMPLETED_WITH_WARNINGS
        else:
            status = ExtractionStatus.COMPLETED
        result.extraction_status = status
        return result

    # -- internal steps -----------------------------------------------------

    def _ocr_text_shallow(self, image: np.ndarray) -> str:
        """Cheap whole-frame OCR used only for profile matching."""
        if self._ocr is None:
            return shallow_text(image)
        result = self._ocr.recognize_image(image)
        return " ".join(t.text for t in result.tokens)

    def _extract_coil_tables(
        self,
        image: np.ndarray,
        profile: IndustrialProfile | None,
        warnings: list[str],
    ) -> list[Table]:
        """Read table-structured regions into unified-schema Tables."""
        from engine.industrial.coil_table import map_row, rows_to_table, validate_cells

        if profile is None:
            return []
        tables: list[Table] = []
        for region in detect_regions(image, model_hook=self.detector_hook):
            if region.type is not RegionType.TABLE:
                continue
            crop = _crop(image, region.bbox)
            headers, rows, row_alts = self._read_grid(crop)
            if profile is not None:
                # Re-read data cells with the profile's per-column whitelists
                # (e.g. id columns keep O/0 straight).
                types = [_field_type(profile, h) for h in headers]
                if any(types):
                    headers, rows, row_alts = self._read_grid(crop, field_types=types)
            if not headers or not rows:
                continue
            schemas = profile.table_schemas or {}
            name = next(iter(schemas), "coil_table")
            # Keep the OCR'd header text as the column key: the eval (and any
            # downstream consumer of the raw grid) matches on it, while
            # map_row/validate use the profile-resolved names internally.
            canonical_headers = [h.strip().upper() for h in headers]
            resolved = [profile.resolve_column(h) for h in headers]
            mapped_rows = [
                map_row(headers, row, profile, alternatives=alts)
                for row, alts in zip(rows, row_alts)
            ]
            out_rows: list[list[str]] = []
            for mr, raw_row in zip(mapped_rows, rows):
                seen: set[str] = set()
                out_row: list[str] = []
                for res, cell in zip(resolved, raw_row):
                    # Mapped/cleaned value comes from the FIRST column that
                    # resolves to a canonical name (HOT_COIL_NO before
                    # COLD_COIL_NO); later duplicates keep the raw cell.
                    if res is not None and res not in seen:
                        seen.add(res)
                        out_row.append(str(mr.values.get(res) or cell or ""))
                    else:
                        out_row.append(cell or "")
                out_rows.append(out_row)
            for note in [n for mr in mapped_rows for n in mr.notes]:
                warnings.append(note)
            warnings.extend(validate_cells(mapped_rows, profile))
            tables.append(
                rows_to_table(
                    name,
                    canonical_headers,
                    out_rows,
                    profile,
                    bbox=region.bbox,
                    resolve_headers=False,
                )
            )
        return tables

    def _read_grid(
        self, crop: np.ndarray, *, field_types: list[str | None] | None = None
    ) -> tuple[list[str], list[list[str]], list[dict[int, list[str]]]]:
        """Read a cropped table as header + row strings (region-grid OCR).

        Returns headers, rows and per-row {col_index: ocr_alternatives}.
        """
        import cv2

        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        # Grid lines are foreground. On dark HMI screens they are brighter
        # than the background, on scanned tables darker: pick the polarity
        # from the crop's overall brightness.
        if gray.mean() < 127.5:
            line_fg = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2
            )
        else:
            line_fg = cv2.adaptiveThreshold(
                255 - gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2
            )
        height, width = line_fg.shape
        hlines = _line_positions(line_fg.mean(axis=1) / 255.0, min_coverage=0.3)
        vlines = _line_positions(line_fg.mean(axis=0) / 255.0, min_coverage=0.3)
        if len(hlines) < 2 or len(vlines) < 2:
            return [], [], []
        rows: list[list[str]] = []
        alts: list[dict[int, list[str]]] = []
        row_index = -1
        for top, bottom in zip(hlines, hlines[1:]):
            if bottom - top < 8:  # the line stroke itself, not a cell row
                continue
            row_index += 1
            cells_text: list[str] = []
            row_alts: dict[int, list[str]] = {}
            for col_index, (left, right) in enumerate(zip(vlines, vlines[1:])):
                if right - left < 8:
                    continue
                cell = crop[top + 2 : bottom - 2, left + 2 : right - 2]
                # Whitelists (digit-only etc.) apply to data cells only —
                # applying them to the header row strips its letters.
                ftype = (
                    field_types[col_index]
                    if field_types and row_index > 0 and col_index < len(field_types)
                    else None
                )
                reading = read_compact(cell, field_type=ftype or "string")
                cells_text.append(reading.text)
                if row_index > 0 and reading.alternatives:
                    row_alts[col_index] = reading.alternatives
            rows.append(cells_text)
            alts.append(row_alts)
        if not rows:
            return [], [], []
        # Keep positional alignment: an empty header cell stays as a
        # placeholder so data-column indices still line up with `headers`.
        headers = rows[0] if rows else []
        return headers, rows[1:], alts[1:]

    def _extract_fields(
        self,
        image: np.ndarray,
        regions: list[Region],
        profile: IndustrialProfile | None,
    ) -> list[FieldValue]:
        fields: list[FieldValue] = []
        for region in regions:
            if region.type is not RegionType.LABEL_VALUE:
                continue
            crop = _crop(image, region.bbox)
            reading = read_compact(crop, field_type="string")
            if not reading.text:
                continue
            for name, spec in (profile.fields if profile else {}).items():
                # Whole-token match: "T" must not match "THICKNESS"; the
                # matched label is stripped before parsing the value.
                labels = [spec.name, *spec.aliases]
                matched = next(
                    (
                        lab
                        for lab in labels
                        if re.search(rf"\b{re.escape(lab.lower())}\b", reading.text.lower())
                    ),
                    None,
                )
                if matched is None:
                    continue
                value_text = re.sub(
                    rf"\b{re.escape(matched.lower())}\b", " ", reading.text, flags=re.IGNORECASE
                )
                value_text = value_text.strip(" \t:-=\u00a0")
                parsed = parse_value_unit(value_text or reading.text, default_unit=spec.unit)
                review_notes = [
                    n for n in parsed.notes if not n.startswith("unit defaulted")
                ]
                format_problems: list[str] = []
                if name in DEFAULT_FIELDS and parsed.value is not None:
                    format_problems = validate_value(name, str(parsed.value))
                fields.append(
                    FieldValue(
                        name=name,
                        value=parsed.value,
                        raw_text=reading.text,
                        unit=parsed.unit,
                        type=spec.type,
                        confidence=reading.confidence,
                        bbox=BBox(
                            x0=region.bbox[0],
                            y0=region.bbox[1],
                            x1=region.bbox[2],
                            y1=region.bbox[3],
                        ),
                        needs_review=bool(review_notes or reading.flags or format_problems),
                    )
                )
        return fields

    def _extract_alarms(
        self, image: np.ndarray, regions: list[Region]
    ) -> list[alarm_mod.AlarmEntry]:
        entries: list[alarm_mod.AlarmEntry] = []
        for region in regions:
            if region.type is not RegionType.ALARM_BANNER:
                continue
            crop = _crop(image, region.bbox)
            reading = read_compact(crop, field_type="string")
            token = OCRToken(text=reading.text, bbox=region.bbox, confidence=reading.confidence)
            entry = alarm_mod.parse_alarm_row([token], banner_color=region.color)
            if entry is not None:
                entries.append(entry)
        return entries

    @staticmethod
    def _region_dict(region: Region) -> dict[str, object]:
        return {
            "type": str(region.type),
            "bbox": list(region.bbox),
            "score": round(region.score, 3),
            "color": region.color,
            "source": region.source,
        }

    @staticmethod
    def _alarm_dict(entry: alarm_mod.AlarmEntry) -> dict[str, object]:
        return {
            "timestamp": entry.timestamp,
            "code": entry.code,
            "message": entry.message,
            "severity": entry.severity,
            "color": entry.color,
            "flags": entry.flags,
        }


def _field_type(profile: IndustrialProfile, header: str) -> str | None:
    """Map an OCR'd column header to a compact-OCR whitelist type."""
    resolved = profile.resolve_column(header)
    if resolved is None:
        return None
    field_def = profile.fields.get(resolved)
    if field_def is None:
        return None
    return field_def.type if field_def.type in WHITELISTS else None


def _line_positions(profile: np.ndarray, *, min_coverage: float) -> list[int]:
    """Centres of contiguous line bands in a 0..1 coverage profile."""
    bands: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(profile):
        if value >= min_coverage and start is None:
            start = index
        elif value < min_coverage and start is not None:
            bands.append((start, index))
            start = None
    if start is not None:
        bands.append((start, len(profile)))
    return [(a + b) // 2 for a, b in bands]


def _crop(image: np.ndarray, bbox: tuple[float, float, float, float]) -> np.ndarray:
    x0, y0, x1, y1 = (int(max(0, v)) for v in bbox)
    return image[y0:y1, x0:x1]


__all__ = ["INDUSTRIAL_CATEGORIES", "IndustrialVision", "MODULE_VERSION"]
