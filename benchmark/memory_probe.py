"""D4 memory probe: RSS before/after/peak for N sequential worker-style runs.

Runs the same per-file work ``service/worker/runner.py`` does for one file
(preprocess + shared-factory Tesseract OCR + industrial vision) on one seed
fixture N times with the same config, then records RSS before, after and peak
(``ru_maxrss`` joined with ``/proc/self/status`` VmHWM).

Fails (exit 1) when peak RSS exceeds 7 GB or more than 1.10x the measured
baseline peak (``--baseline-peak-mb``).

Measure the baseline on main (100e608) first with this same script, then run
it on the branch:
    .venv/bin/python -m benchmark.memory_probe --n 10 --baseline-peak-mb <measured>
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

from PIL import Image  # noqa: F401  (kept for probe API parity)

from engine.industrial.pipeline import IndustrialVision
from engine.models import ModelKey, default_factory, options_hash
from engine.ocr.pipeline import GeneralOCR
from engine.ocr.tesseract_backend import TesseractEngine
from engine.preprocessing.pipeline import PreprocessingPipeline

GB_BUDGET_MB = 7 * 1024  # 7 GB budget in MB


def _peak_mb() -> float:
    """Peak RSS in MB: ru_maxrss (KiB on Linux) joined with VmHWM if newer."""
    peak_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                peak_kib = max(peak_kib, int(line.split()[1]))
    except OSError:
        pass
    return peak_kib / 1024.0


def _rss_mb() -> float:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def _build_vision(profile: str) -> tuple[IndustrialVision, int]:
    """What the worker builds per file, with the OCR engine via the factory."""
    from service.worker.runner import build_engine_options

    preprocess_options, ocr_options = build_engine_options({}, profile)
    preprocessing = PreprocessingPipeline.from_options(preprocess_options)
    ocr_engine = default_factory.get(
        ModelKey(
            engine="tesseract",
            variant=ocr_options.tesseract_lang,
            device="cpu",
            options_hash=options_hash(ocr_options),
        ),
        lambda: TesseractEngine.from_options(ocr_options),
    )
    vision = IndustrialVision(
        preprocessing=preprocessing,
        ocr=GeneralOCR.from_options([ocr_engine], ocr_options),
    )
    return vision, preprocess_options.dpi


def _find_image(seed_dir: Path) -> Path:
    images = sorted(seed_dir.glob("images/*.png")) + sorted(seed_dir.glob("images/*.jpg"))
    if not images:
        raise SystemExit(f"no seed image under {seed_dir}/images/")
    return images[0]


def _load_image(path: Path, dpi: int):
    from engine.preprocessing.io import load_input

    return load_input(path, dpi=dpi)[0].data


def run(n: int, seed: Path, profile: str) -> dict[str, object]:
    default_factory.release_all()
    image_path = _find_image(seed)
    _, dpi = _build_vision(profile)  # warm path probe; rebuilt per run below
    image = _load_image(image_path, dpi)

    rss_before = _rss_mb()
    t0 = time.monotonic()
    fields = 0
    for i in range(n):
        # The worker builds a fresh vision stack per file; the factory makes
        # the OCR engine shared, so only run 1 pays the load.
        vision, _ = _build_vision(profile)
        result = vision.process(image, file_name=image_path.name)
        fields = len(result.fields)
        print(f"run {i + 1}/{n}: fields={fields}", flush=True)
    elapsed = time.monotonic() - t0

    return {
        "n": n,
        "seed_image": str(image_path),
        "profile": profile,
        "rss_before_mb": round(rss_before, 1),
        "rss_after_mb": round(_rss_mb(), 1),
        "peak_rss_mb": round(_peak_mb(), 1),
        "elapsed_s": round(elapsed, 2),
        "factory_stats": default_factory.stats(),
        "fields_in_last_result": fields,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument(
        "--seed", default="benchmark/seed/industrial_hmi", help="seed fixture dir"
    )
    parser.add_argument("--profile", default="industrial_screen_photo")
    parser.add_argument(
        "--baseline-peak-mb",
        type=float,
        default=0.0,
        help="peak RSS (MB) measured on main with this same script",
    )
    parser.add_argument("--out", default="benchmark/artifacts/d4_memory.json")
    args = parser.parse_args()

    data = run(args.n, Path(args.seed), args.profile)
    peak = float(data["peak_rss_mb"])  # type: ignore[arg-type]
    data["budget_gb"] = GB_BUDGET_MB / 1024
    if args.baseline_peak_mb > 0:
        data["baseline_peak_mb"] = args.baseline_peak_mb
        data["baseline_x_peak"] = round(peak / args.baseline_peak_mb, 3)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(data, indent=2))

    if peak > GB_BUDGET_MB:
        print(f"FAIL: peak {peak:.0f} MB exceeds 7 GB budget", file=sys.stderr)
        sys.exit(1)
    if args.baseline_peak_mb > 0 and peak > 1.10 * args.baseline_peak_mb:
        print(
            f"FAIL: peak {peak:.0f} MB exceeds 1.10x baseline "
            f"({args.baseline_peak_mb:.0f} MB)",
            file=sys.stderr,
        )
        sys.exit(1)
    print("PASS: peak RSS within budget")


if __name__ == "__main__":
    main()
