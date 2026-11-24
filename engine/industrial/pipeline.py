"""Industrial Vision orchestrator (P4).

``IndustrialVision.process``: router decision/profile in, unified-schema
``ExtractionResult`` out. Fallback per brief item 9: when no profile
matches, parse as generic HMI (``industrial_hmi``) and record a
``NO_PROFILE_MATCHED`` warning. Unknown values are never guessed; they are
flagged with ``needs_review`` / parse notes.
"""

from __future__ import annotations

import time

import numpy as np

from engine.industrial import alarms as alarm_mod
from engine.industrial.compact_ocr import read_compact
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
)

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
    ) -> None:
        self.profiles = profiles  # None -> bundled profiles loaded lazily
        self.detector_hook = detector_hook or UnavailableDetectorHook()
        self._preprocessing = preprocessing
        self._ocr = ocr

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

        profile = match_profile(
            self._ocr_text_shallow(working),
            profiles=self._profile_pool(),
        )
        if profile is None:
            warnings.append("NO_PROFILE_MATCHED: falling back to generic industrial_hmi parsing")

        regions = detect_regions(working, model_hook=self.detector_hook)
        tables = self._extract_coil_tables(working, profile, warnings)
        fields = self._extract_fields(working, regions, profile)
        alarm_entries = self._extract_alarms(working, regions)

        status = (
            ExtractionStatus.COMPLETED_WITH_WARNINGS
            if warnings
            else ExtractionStatus.COMPLETED
        )
        return ExtractionResult(
            document_type=(
                profile.categories[0] if profile and profile.categories else "industrial_hmi"
            ),
            extraction_status=status,
            source=SourceInfo(file_name=file_name, page=1),
            tables=tables,
            fields=fields,
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

    # -- internal steps -----------------------------------------------------

    def _ocr_text_shallow(self, image: np.ndarray) -> str:
        """Cheap whole-frame OCR used only for profile matching."""
        if self._ocr is None:
            from engine.industrial.compact_ocr import read_compact

            return read_compact(image, field_type="string", upscale=1.0).text
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
            headers, rows = self._read_grid(crop)
            if not headers or not rows:
                continue
            schemas = profile.table_schemas or {}
            name = next(iter(schemas), "coil_table")
            mapped_rows = [map_row(headers, row, profile) for row in rows]
            canonical_headers = [profile.resolve_column(h) or h.strip() for h in headers]
            for note in [n for mr in mapped_rows for n in mr.notes]:
                warnings.append(note)
            warnings.extend(validate_cells(mapped_rows, profile))
            tables.append(
                rows_to_table(
                    name,
                    canonical_headers,
                    [[mr.values.get(col, "") for col in canonical_headers] for mr in mapped_rows],
                    profile,
                    bbox=region.bbox,
                )
            )
        return tables

    def _read_grid(self, crop: np.ndarray) -> tuple[list[str], list[list[str]]]:
        """Read a cropped table as header + row strings (region-grid OCR)."""
        import cv2

        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        binary = cv2.adaptiveThreshold(
            255 - gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2
        )
        horizontal = cv2.dilate(binary, cv2.getStructuringElement(cv2.MORPH_RECT, (80, 1)))
        contours, _ = cv2.findContours(horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        bands = sorted(
            (cv2.boundingRect(c)[1], cv2.boundingRect(c)[3], cv2.boundingRect(c)) for c in contours
        )
        if len(bands) < 2:
            return [], []
        rows: list[list[str]] = []
        for _, _, (x, y, w, h) in bands:
            cells_text: list[str] = []
            row_band = binary[y : y + h, x : x + w]
            vertical = cv2.dilate(
                row_band, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, h)))
            )
            vcontours, _ = cv2.findContours(vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            boxes = sorted(
                (cv2.boundingRect(vc)[0], cv2.boundingRect(vc)[1]) for vc in vcontours
            )
            for cx, _ in boxes:
                reading = read_compact(crop[y : y + h, cx : cx + max(4, w // max(1, len(boxes)))])
                cells_text.append(reading.text)
            rows.append(cells_text)
        headers = [h for h in rows[0] if h]
        return headers, rows[1:]

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
                if spec.name.lower() not in reading.text.lower() and not any(
                    a.lower() in reading.text.lower() for a in spec.aliases
                ):
                    continue
                parsed = parse_value_unit(reading.text, default_unit=spec.unit)
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
                        needs_review=bool(parsed.notes or reading.flags),
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


def _crop(image: np.ndarray, bbox: tuple[float, float, float, float]) -> np.ndarray:
    x0, y0, x1, y1 = (int(max(0, v)) for v in bbox)
    return image[y0:y1, x0:x1]


__all__ = ["INDUSTRIAL_CATEGORIES", "IndustrialVision", "MODULE_VERSION"]
