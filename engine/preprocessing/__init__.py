"""Phase P1 - preprocessing: load, normalize, geometry-correct, enhance, report."""

from engine.preprocessing.debug import save_debug_comparison
from engine.preprocessing.errors import (
    CorruptImageError,
    InputLimitError,
    PreprocessingError,
    SourceNotFoundError,
    UnsupportedFormatError,
)
from engine.preprocessing.io import DEFAULT_DPI, LoadedImage, load_input
from engine.preprocessing.mapping import TransformLog
from engine.preprocessing.pipeline import PreprocessedImage, PreprocessingPipeline
from engine.preprocessing.quality import QualityReport, QualityWarning, compute_quality

__all__ = [
    "DEFAULT_DPI",
    "CorruptImageError",
    "InputLimitError",
    "LoadedImage",
    "PreprocessedImage",
    "PreprocessingError",
    "PreprocessingPipeline",
    "QualityReport",
    "QualityWarning",
    "SourceNotFoundError",
    "TransformLog",
    "UnsupportedFormatError",
    "compute_quality",
    "load_input",
    "save_debug_comparison",
]
