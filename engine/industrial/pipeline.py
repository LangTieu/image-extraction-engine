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
from engine.ocr.pipeline import GeneralOCR, _map_bbox
from engine.preprocessing.mapping import TransformLog
from engine.preprocessing.pipeline import PreprocessingPipeline
from engine.schema import (
    BBox,
    ExtractionResult,
    ExtractionStatus,
    FieldValue,
    ProcessingMeta,
    Provenance,
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

    def _enhance(self, image: np.ndarray):
        """Run the bundled enhancement profile (constructed lazily)."""
        if self._preprocessing is None:
            self._preprocessing = PreprocessingPipeline.for_profile("industrial_screen_photo")
        return self._preprocessing.run(image)

    @staticmethod
    def _corrections_dict(pre) -> dict:
        """Summarize which corrections the enhancement profile applied."""
        info = pre.step_info
        return {
            "profile": pre.profile_name,
            "orientation_90": info.get("orientation", {}).get("orientation_90", 0),
            "deskew_deg": info.get("orientation", {}).get("skew_deg", 0.0),
            "perspective_corrected": bool(
                info.get("perspective", {}).get("corrected", False)
            ),
            "denoise": "skipped" not in info.get("denoise", {"ran": 1}),
            "contrast": "skipped" not in info.get("contrast", {"ran": 1}),
            "sharpen": "skipped" not in info.get("sharpen", {"ran": 1}),
            "upscale_factor": info.get("upscale", {}).get("factor", 1.0),
            "blur_variance_normalized_before": pre.quality_before.blur_variance_normalized,
        }

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

        # Enhancement profile (contrast / denoise / sharpen / deskew) on the
        # rectified screen. Runs after rectification so the gates see final
        # geometry; the pipeline's own quality gates keep it a no-op on clean
        # input. The detected corrections are surfaced in the result.
        pre = self._enhance(working)
        working = pre.image

        # One whole-frame OCR pass, shared by profile matching and (on the
        # generic-HMI fallback) text_blocks. Running recognize_image twice
        # would double OCR cost; the TransformLog handed to the OCR pipeline
        # maps working-image coordinates back to the original photo, so every
        # bbox_original / prov lands in original-image coordinates.
        ocr_log = TransformLog()
        if report.transform is not None:
            # rectify maps original -> rectified; the log needs the inverse.
            ocr_log.add("rectify", np.linalg.inv(report.transform))
        ocr_log.add("enhance", pre.transform_log.homography)
        ocr_document = (
            self._ocr.recognize_image(working, transform_log=ocr_log)
            if self._ocr is not None
            else None
        )
        profile_text = (
            " ".join(t.text for t in ocr_document.tokens) if ocr_document else shallow_text(working)
        )
        profile = match_profile(profile_text, profiles=self._profile_pool())
        if profile is None:
            warnings.append("NO_PROFILE_MATCHED: falling back to generic industrial_hmi parsing")

        regions = detect_regions(working, model_hook=self.detector_hook)
        tables = self._extract_coil_tables(working, profile, warnings, transform_log=ocr_log)
        fields = self._extract_fields(working, regions, profile, transform_log=ocr_log)
        alarm_entries = self._extract_alarms(working, regions, transform_log=ocr_log)

        # Generic-HMI fallback: heuristics found no typed regions (no
        # LABEL_VALUE etc.), so without this the OCR text discovered above
        # was thrown away and the result came back with zero text. The
        # whole-frame blocks go into text_blocks; the OCR pass is reused,
        # not repeated.
        text_blocks: list[TextBlock] = []
        if profile is None and ocr_document is not None:
            for page_blocks in ocr_document.pages:
                for block in page_blocks:
                    if not re.search(r"[A-Za-z0-9]", block.text):
                        continue  # punctuation/noise-only lines from screen glare
                    prov_bbox = block.bbox_original or block.bbox
                    # Prefer the provenance the OCR producer attached (page +
                    # scale from the real tokens); fall back to a local build.
                    prov = block.prov or (
                        [
                            Provenance(
                                page=block.page_index,
                                bbox=BBox(
                                    x0=prov_bbox[0],
                                    y0=prov_bbox[1],
                                    x1=prov_bbox[2],
                                    y1=prov_bbox[3],
                                ),
                                scale=block.scale,
                            )
                        ]
                        if prov_bbox
                        else []
                    )
                    text_blocks.append(
                        TextBlock(
                            text=block.text,
                            bbox=BBox(
                                x0=block.bbox[0],
                                y0=block.bbox[1],
                                x1=block.bbox[2],
                                y1=block.bbox[3],
                            )
                            if block.bbox
                            else None,
                            reading_order=block.reading_order,
                            confidence=block.confidence,
                            prov=prov,
                        )
                    )

        # A row-level note repeats for every data row (one per unmapped
        # header cell); the same warning text belongs in the result once.
        warnings = list(dict.fromkeys(warnings))
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
                    "corrections": self._corrections_dict(pre),
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
        """Cheap whole-frame OCR used only for profile matching.

        No transform_log is passed and none is needed: the tokens here are
        consumed as a text bag for profile cues and are never attached to any
        bbox/prov, so they cannot mislabel provenance.
        """
        if self._ocr is None:
            return shallow_text(image)
        result = self._ocr.recognize_image(image)
        return " ".join(t.text for t in result.tokens)

    def _extract_coil_tables(
        self,
        image: np.ndarray,
        profile: IndustrialProfile | None,
        warnings: list[str],
        *,
        transform_log: TransformLog | None = None,
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
            cell_boxes: list[list[tuple]] | None
            headers, rows, row_alts, cell_boxes = self._read_grid(crop)
            if profile is not None:
                # The first grid row is often a toolbar strip above the real
                # table: pick the row that best matches the profile's column
                # names as the header and re-read below that row.
                header_index = _pick_header_index([headers, *rows], profile)
                # Re-read with the header row fixed (and the profile's
                # per-column whitelists where they resolve, e.g. id columns
                # keep O/0 straight).
                types = [_field_type(profile, h) for h in headers]
                if header_index or any(types):
                    headers, rows, row_alts, cell_boxes = self._read_grid(
                        crop, field_types=types or None, header_index=header_index
                    )
            if not headers or not rows:
                continue
            headers, rows, row_alts, cell_boxes = _drop_noise_columns(
                headers, rows, row_alts, cell_boxes
            )
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
            for note in dict.fromkeys(n for mr in mapped_rows for n in mr.notes):
                warnings.append(note)
            warnings.extend(dict.fromkeys(validate_cells(mapped_rows, profile)))
            tables.append(
                rows_to_table(
                    name,
                    canonical_headers,
                    out_rows,
                    profile,
                    bbox=region.bbox,
                    resolve_headers=False,
                    transform_log=transform_log,
                    cell_bboxes=[
                        [
                            (
                                b[0] + region.bbox[0],
                                b[1] + region.bbox[1],
                                b[2] + region.bbox[0],
                                b[3] + region.bbox[1],
                            )
                            for b in row_boxes
                        ]
                        for row_boxes in (cell_boxes or [])
                    ],
                )
            )
        return tables

    def _read_grid(
        self,
        crop: np.ndarray,
        *,
        field_types: list[str | None] | None = None,
        header_index: int = 0,
    ) -> tuple[list[str], list[list[str]], list[dict[int, list[str]]], list[list[tuple]]]:
        """Read a cropped table as header + row strings (region-grid OCR).

        ``header_index`` is the grid row that carries the real column headers:
        HMI screenshots often include toolbar rows above the table, so the
        first detected grid row is not always the header.

        Returns headers, rows (grid rows after the header), per-row
        {col_index: ocr_alternatives} and per-row cell bboxes (crop
        coordinates, aligned [header row] + data rows).
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
            return [], [], [], []
        rows: list[list[str]] = []
        alts: list[dict[int, list[str]]] = []
        boxes: list[list[tuple]] = []
        row_index = -1
        for top, bottom in zip(hlines, hlines[1:]):
            if bottom - top < 8:  # the line stroke itself, not a cell row
                continue
            row_index += 1
            cells_text: list[str] = []
            cell_boxes: list[tuple] = []
            row_alts: dict[int, list[str]] = {}
            for col_index, (left, right) in enumerate(zip(vlines, vlines[1:])):
                if right - left < 8:
                    continue
                cell_boxes.append((left, top, right, bottom))
                cell = crop[top + 2 : bottom - 2, left + 2 : right - 2]
                # Whitelists (digit-only etc.) apply to data cells only —
                # applying them to the header row strips its letters.
                ftype = (
                    field_types[col_index]
                    if field_types
                    and row_index > header_index
                    and col_index < len(field_types)
                    else None
                )
                reading = read_compact(cell, field_type=ftype or "string")
                cells_text.append(reading.text)
                if row_index > header_index and reading.alternatives:
                    row_alts[col_index] = reading.alternatives
            rows.append(cells_text)
            alts.append(row_alts)
            boxes.append(cell_boxes)
        if not rows:
            return [], [], [], []
        # Keep positional alignment: an empty header cell stays as a
        # placeholder so data-column indices still line up with `headers`.
        header_index = min(max(header_index, 0), len(rows) - 1)
        headers = rows[header_index]
        return headers, rows[header_index + 1 :], alts[header_index + 1 :], boxes[header_index:]

    def _extract_fields(
        self,
        image: np.ndarray,
        regions: list[Region],
        profile: IndustrialProfile | None,
        *,
        transform_log: TransformLog | None = None,
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
                        prov=_prov_for_bbox(region.bbox, transform_log),
                        needs_review=bool(review_notes or reading.flags or format_problems),
                    )
                )
        return fields

    def _extract_alarms(
        self, image: np.ndarray, regions: list[Region], transform_log=None
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
                entry.prov = _prov_for_bbox(region.bbox, transform_log)
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
            "prov": [
                {
                    "page": p.page,
                    "scale": p.scale,
                    "coord_space": p.coord_space,
                    "unit": p.unit,
                    "bbox": (
                        None
                        if p.bbox is None
                        else [p.bbox.x0, p.bbox.y0, p.bbox.x1, p.bbox.y1]
                    ),
                }
                for p in (entry.prov or [])
            ],
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


def _pick_header_index(candidate_rows: list[list[str]], profile: IndustrialProfile) -> int:
    """Index of the grid row that carries the real column headers.

    Scores each of the first few rows by how many of its cells resolve to a
    profile column name (OCR glues/splits words, so compare alphanumeric-only
    forms with containment); toolbar strips above the table resolve to
    nothing. Falls back to row 0 when nothing matches (unknown layout).
    """
    alias_norms = {
        re.sub(r"[^a-z0-9]", "", alias)
        for aliases in profile._alias_index().values()
        for alias in aliases
        if len(alias) >= 2
    }

    def score_row(row: list[str]) -> int:
        score = 0
        for cell in row:
            norm = re.sub(r"[^a-z0-9]", "", (cell or "").lower())
            if len(norm) < 2:
                continue
            if any(norm == a or (len(norm) >= 3 and (norm in a or a in norm)) for a in alias_norms):
                score += 1
        return score

    best, best_score = 0, 0
    for index, row in enumerate(candidate_rows[:6]):
        if index == 0:
            continue  # default candidate; only a better match displaces it
        score = score_row(row)
        if score > best_score:
            best, best_score = index, score
    return best if best_score >= 2 else 0


def _drop_noise_columns(
    headers: list[str],
    rows: list[list[str]],
    row_alts: list[dict[int, list[str]]],
    cell_boxes: list[list[tuple]] | None = None,
) -> tuple[list[str], list[list[str]], list[dict[int, list[str]]], list[list[tuple]] | None]:
    """Drop gutter/noise columns left of the real table.

    A column is noise when (nearly) all of its data cells carry no
    alphanumeric character (checkbox cells, scrollbar slivers, moire dashes).
    Real narrow columns (SEQ `001`, status `5`) survive because their cells
    contain digits.
    """
    if not rows or not headers:
        return headers, rows, row_alts, cell_boxes
    keep: list[int] = []
    for col in range(len(headers)):
        cells = [row[col] if col < len(row) else "" for row in rows]
        alnum = sum(1 for cell in cells if re.search(r"[A-Za-z0-9]", cell or ""))
        if alnum >= 0.25 * len(cells):
            keep.append(col)
    if len(keep) == len(headers):
        return headers, rows, row_alts, cell_boxes
    keep_set = set(keep)
    headers = [headers[col] for col in keep]
    rows = [[row[col] for col in keep if col < len(row)] for row in rows]
    if cell_boxes is not None:
        cell_boxes = [
            [b for i, b in enumerate(row_boxes) if i in keep_set] for row_boxes in cell_boxes
        ]
    row_alts = [
        {new_col: v for new_col, (col, v) in enumerate(
            (col, v) for col, v in alts.items() if col in keep_set
        )}
        for alts in row_alts
    ]
    return headers, rows, row_alts, cell_boxes


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


def _prov_for_bbox(
    bbox: tuple[float, float, float, float],
    transform_log: TransformLog | None,
) -> list[Provenance]:
    """Provenance for one node bbox, in original-image coordinates.

    ``bbox`` stays in processed (working-image) coordinates, like
    text_blocks; prov carries the same box mapped through the
    TransformLog back to the source photo.
    """
    src = bbox
    if transform_log is not None:
        src = _map_bbox(bbox, transform_log)
    return [
        Provenance(
            # Single-image path: 0-based page 0 and scale 1.0, matching the
            # coil_table producers (engine/industrial/coil_table.py) so every
            # FieldValue.prov carries the same page/scale meta as TextBlock
            # and Table/Cell provenance.
            page=0,
            scale=1.0,
            bbox=BBox(x0=src[0], y0=src[1], x1=src[2], y1=src[3]),
        )
    ]


def _crop(image: np.ndarray, bbox: tuple[float, float, float, float]) -> np.ndarray:
    x0, y0, x1, y1 = (int(max(0, v)) for v in bbox)
    return image[y0:y1, x0:x1]


__all__ = ["INDUSTRIAL_CATEGORIES", "IndustrialVision", "MODULE_VERSION"]
