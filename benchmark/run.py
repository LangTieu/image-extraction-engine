"""P8 benchmark runner: one command for metrics, comparison, robustness,
performance, error analysis, artifacts and charts.

Usage:
    .venv/bin/python -m benchmark.run [--split dev|test|all] [--seed 42]
        [--category coil_table] [--variant default_tesseract] [--quick]
        [--no-robustness] [--profile] [--tag ci]

Writes an artifact directory benchmark/artifacts/<tag or timestamp>_<sha8>/
with config.json, metrics.json, errors.json, robustness.json,
performance.json and charts under reports/. Exits non-zero on gate failure.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import platform
import pstats
import sys
import time
from pathlib import Path

import numpy as np

from benchmark.harness import (
    VARIANTS,
    PipelineVariant,
    aggregate_text_cer_wer,
    bootstrap_ci,
    environment_info,
    expected_calibration_error,
    gt_text,
    load_gt,
    render_scene,
    score_sample,
    split_seed,
)
from benchmark.robustness import (
    BREAKDOWN_DROP,
    MAX_SEVERITY,
    PERTURBATIONS,
    breakdown_severity,
)
from engine.metrics import cer as cer_metric
from engine.metrics import wer as wer_metric


def fnum(s: dict[str, object], key: str) -> float:
    value = s[key]
    assert isinstance(value, (int, float, bool, str))
    return float(value)


def flist(s: dict[str, object], key: str) -> list[object]:
    value = s[key]
    assert isinstance(value, list)
    return value


ARTIFACTS = Path(__file__).parent / "artifacts"
PRIMARY_GATES = {
    "route_accuracy": 0.5,
    "field_accuracy": 0.3,
    "cer": 0.6,
}


def pred_text(result) -> str:
    return gt_text(result)


# --------------------------------------------------------------------------
# one variant over one split


def run_variant(
    variant_name: str,
    samples: list[dict[str, str]],
    *,
    category_filter: str | None = None,
) -> dict[str, object]:
    variant = VARIANTS[variant_name]
    runner = PipelineVariant(name=variant_name, **variant).build()  # type: ignore[arg-type]
    per_sample: list[dict[str, object]] = []
    cer_wer: list[tuple[float, float]] = []
    for entry in samples:
        if category_filter and entry["category"] != category_filter:
            continue
        gt = load_gt(entry["gt"])
        image = render_scene(gt)
        pred, elapsed_ms = runner.process(image, file_name=Path(entry["gt"]).stem)
        scores = score_sample(gt, pred, elapsed_ms)
        scores["category"] = entry["category"]
        scores["sample"] = Path(entry["gt"]).stem
        ref_text, hyp_text = gt_text(gt), pred_text(pred)
        c, w = cer_metric(ref_text, hyp_text), wer_metric(ref_text, hyp_text)
        cer_wer.append((c, w))
        scores["cer"] = c
        scores["wer"] = w
        per_sample.append(scores)

    text = aggregate_text_cer_wer(per_sample, cer_wer)

    route_acc = float(np.mean([fnum(s, "route_ok") for s in per_sample])) if per_sample else 0.0
    field_acc = (
        float(np.mean([fnum(s, "field_accuracy") for s in per_sample])) if per_sample else 0.0
    )
    structure = [
        fnum(s, "table_structure_f1")
        for s in per_sample
        if s["table_structure_f1"] is not None
    ]
    latencies = [fnum(s, "elapsed_ms") for s in per_sample]

    conf: list[float] = []
    corr: list[bool] = []
    wrong_flagged = wrong_total = 0
    for s in per_sample:
        conf.extend(float(str(c)) for c in flist(s, "field_confidences"))
        corr.extend(bool(c) for c in flist(s, "field_correctness"))
        wrong_total += len(flist(s, "field_wrong"))
        wrong_flagged += len(flist(s, "wrong_flagged"))
    calibration = expected_calibration_error(conf, corr)

    per_category: dict[str, dict[str, float]] = {}
    categories: list[str] = sorted({str(s["category"]) for s in per_sample})
    for category in categories:
        rows = [s for s in per_sample if s["category"] == category]
        per_category[category] = {
            "n": len(rows),
            "route_accuracy": float(np.mean([fnum(r, "route_ok") for r in rows])),
            "field_accuracy": float(np.mean([fnum(r, "field_accuracy") for r in rows])),
            "coil_id_accuracy": float(np.mean([fnum(r, "coil_id_accuracy") for r in rows])),
            "cer": float(np.mean([fnum(r, "cer") for r in rows])),
            "mean_ms": float(np.mean([fnum(r, "elapsed_ms") for r in rows])),
        }

    field_ci = bootstrap_ci([fnum(s, "field_accuracy") for s in per_sample])
    struct_mean = float(np.mean(structure)) if structure else None
    structure_f1: float | None = struct_mean
    return {
        "variant": variant_name,
        "n_samples": len(per_sample),
        "route_accuracy": route_acc,
        "field_accuracy": field_acc,
        "coil_id_accuracy": float(np.mean([fnum(s, "coil_id_accuracy") for s in per_sample]))
        if per_sample
        else 0.0,
        "cer": text["cer"],
        "wer": text["wer"],
        "table_structure_f1": structure_f1,
        "latency": bootstrap_ci(latencies, statistic="median"),
        "batch_ms": float(sum(latencies)),
        "throughput_img_per_s": len(latencies) / (sum(latencies) / 1000) if latencies else 0.0,
        "ece": calibration["ece"],
        "reliability_bins": calibration["bins"],
        "wrong_fields_total": wrong_total,
        "wrong_fields_flagged": wrong_flagged,
        "error_catch_rate": wrong_flagged / wrong_total if wrong_total else None,
        "field_accuracy_ci": field_ci,
        "per_category": per_category,
        "samples": per_sample,
    }


# --------------------------------------------------------------------------
# robustness / performance / errors


def run_robustness(
    samples: list[dict[str, str]],
    variant_name: str = "default_tesseract",
) -> dict[str, object]:
    runner = PipelineVariant(name=variant_name, **VARIANTS[variant_name]).build()  # type: ignore[arg-type]
    curves: dict[str, object] = {}
    for name, fn in sorted(PERTURBATIONS.items()):
        severities: list[dict[str, float]] = []
        for severity in range(MAX_SEVERITY + 1):
            accs: list[float] = []
            for entry in samples:
                gt = load_gt(entry["gt"])
                image = fn(render_scene(gt), severity)
                pred, _ms = runner.process(image, file_name=Path(str(entry["gt"])).stem)
                scores = score_sample(gt, pred, 0.0)
                accs.append(fnum(scores, "field_accuracy"))
            severities.append(
                {
                    "severity": severity,
                    "field_accuracy": float(np.mean(accs)) if accs else 0.0,
                }
            )
        clean = severities[0]["field_accuracy"]
        curves[name] = {
            "curve": severities,
            "breakdown_severity": breakdown_severity(
                [float(s["field_accuracy"]) for s in severities], clean
            ),
        }
    return {"variant": variant_name, "breakdown_drop": BREAKDOWN_DROP, "curves": curves}


def run_performance(
    samples: list[dict[str, str]],
    variant_name: str = "default_tesseract",
    *,
    profile: bool = False,
) -> dict[str, object]:
    runner = PipelineVariant(name=variant_name, **VARIANTS[variant_name]).build()  # type: ignore[arg-type]
    scenes = []
    for entry in samples[:12]:
        gt = load_gt(entry["gt"])
        scenes.append((Path(entry["gt"]).stem, render_scene(gt)))
    for stem, image in scenes[:2]:  # warm-up (model load, caches)
        runner.process(image, file_name=stem)

    prof = cProfile.Profile() if profile else None
    latencies: list[float] = []
    t0 = time.perf_counter()
    if prof:
        prof.enable()
    for stem, image in scenes:
        _pred, ms = runner.process(image, file_name=stem)
        latencies.append(ms)
    if prof:
        prof.disable()
    wall_ms = (time.perf_counter() - t0) * 1000

    out: dict[str, object] = {
        "variant": variant_name,
        "n_images": len(latencies),
        "mean_ms": float(np.mean(latencies)),
        "p95_ms": float(np.quantile(latencies, 0.95)),
        "batch_ms": wall_ms,
        "throughput_img_per_s": len(latencies) / (wall_ms / 1000),
        "latencies_ms": latencies,
        "hardware": {
            "processors": __import__("os").cpu_count(),
            "platform": platform.platform(),
        },
    }
    if prof:
        stream = io.StringIO()
        stats = pstats.Stats(prof, stream=stream).sort_stats("cumulative")
        stats.print_stats(15)
        out["profile_top_cumulative"] = stream.getvalue()
    return out


def analyze_errors(run_result: dict[str, object]) -> dict[str, object]:
    samples_obj = run_result["samples"]
    assert isinstance(samples_obj, list)
    samples: list[dict[str, object]] = samples_obj
    groups: dict[str, list[dict[str, object]]] = {
        "routing_mismatch": [],
        "field_missing": [],
        "field_wrong": [],
        "field_extra": [],
        "table_structure": [],
        "high_cer": [],
    }
    for s in samples:
        entry = {"sample": f"{s['category']}/{s['sample']}"}
        if not s["route_ok"]:
            groups["routing_mismatch"].append(
                {**entry, "gt": s["gt_type"], "pred": s["pred_type"]}
            )
        missing = s["field_missing"]
        assert isinstance(missing, list)
        for name in missing:
            groups["field_missing"].append({**entry, "field": name})
        wrong = s["field_wrong"]
        assert isinstance(wrong, list)
        fields_gold = s["fields_gold"]
        assert isinstance(fields_gold, dict)
        fields_pred = s["fields_pred"]
        assert isinstance(fields_pred, dict)
        for name in wrong:
            groups["field_wrong"].append(
                {
                    **entry,
                    "field": name,
                    "gt": fields_gold.get(name),
                    "pred": fields_pred.get(name),
                }
            )
        extra = s["field_extra"]
        assert isinstance(extra, list)
        for name in extra:
            groups["field_extra"].append({**entry, "field": name})
        structure_f1 = s["table_structure_f1"]
        cer = s["cer"]
        assert isinstance(structure_f1, (int, float)) or structure_f1 is None
        assert isinstance(cer, (int, float))
        if structure_f1 is not None and structure_f1 < 0.5:
            groups["table_structure"].append(
                {**entry, "structure_f1": structure_f1}
            )
        if cer > 0.3:
            groups["high_cer"].append({**entry, "cer": cer})
    return {
        "counts": {k: len(v) for k, v in groups.items()},
        "groups": groups,
        "next_steps": NEXT_STEPS,
    }


NEXT_STEPS = {
    "routing_mismatch": (
        "Extend router rules / profile keywords for the missed categories (engine/router)."
    ),
    "field_missing": (
        "Check profile field regexes and region detection coverage (engine/industrial)."
    ),
    "field_wrong": (
        "Tune OCR for numeric fields and unit parsing; most errors are OCR-level (see high_cer)."
    ),
    "field_extra": (
        "Suppress hallucinated fields: require profile header match before emitting a field."
    ),
    "table_structure": (
        "Prefer the ruled backend on ruled coil tables; tune ruled_line_scale / cluster_gap_factor."
    ),
    "high_cer": (
        "Preprocessing profile for dark HMI scenes (invert/contrast) is the highest-leverage fix."
    ),
}


# --------------------------------------------------------------------------
# charts


def write_charts(out_dir: Path, metrics: dict[str, object], robustness: dict[str, object]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    reports = out_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    variants_map = metrics["variants"]
    assert isinstance(variants_map, dict)
    variants = [v for v in variants_map.values() if v["n_samples"]]
    names = [v["variant"] for v in variants]
    x = range(len(variants))
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(
        [i - 0.2 for i in x],
        [v["field_accuracy"] for v in variants],
        width=0.4,
        label="field_accuracy",
    )
    ax.bar(
        [i + 0.2 for i in x],
        [v["route_accuracy"] for v in variants],
        width=0.4,
        label="route_accuracy",
    )
    ax.set_xticks(list(x))
    ax.set_xticklabels(names, rotation=20, ha="right", fontsize=8)
    ax.set_ylim(0, 1)
    ax.legend()
    fig.tight_layout()
    fig.savefig(reports / "variant_comparison.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    curves_map = robustness.get("curves", {})
    assert isinstance(curves_map, dict)
    for name, curve in curves_map.items():
        sev = [p["severity"] for p in curve["curve"]]
        acc = [p["field_accuracy"] for p in curve["curve"]]
        ax.plot(sev, acc, marker="o", label=name)
    ax.set_xlabel("severity")
    ax.set_ylabel("field accuracy")
    ax.set_ylim(0, 1)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(reports / "robustness_curves.png", dpi=140)
    plt.close(fig)

    default = variants_map.get("default_tesseract")
    if default and default["n_samples"]:
        lat = [s["elapsed_ms"] for s in default["samples"]]
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.hist(lat, bins=12)
        ax.set_xlabel("ms / image")
        fig.tight_layout()
        fig.savefig(reports / "latency_hist.png", dpi=140)
        plt.close(fig)

        bins = default["reliability_bins"]
        if bins:
            fig, ax = plt.subplots(figsize=(4.5, 4.5))
            ax.plot([0, 1], [0, 1], "k--", lw=1)
            ax.plot([b["confidence"] for b in bins], [b["accuracy"] for b in bins], "o-")
            ax.set_xlabel("confidence")
            ax.set_ylabel("accuracy")
            fig.tight_layout()
            fig.savefig(reports / "reliability_diagram.png", dpi=140)
            plt.close(fig)


# --------------------------------------------------------------------------
# gates


def check_gates(metrics: dict[str, object]) -> list[str]:
    failures: list[str] = []
    variants_map = metrics["variants"]
    assert isinstance(variants_map, dict)
    default = variants_map.get("default_tesseract")
    if not default or not default["n_samples"]:
        return ["default variant produced no samples"]
    for key, threshold in PRIMARY_GATES.items():
        value = default[key]
        assert isinstance(value, float)
        if key == "cer" and value > threshold:
            failures.append(f"gate {key}={value:.3f} > {threshold}")
        elif key != "cer" and value < threshold:
            failures.append(f"gate {key}={value:.3f} < {threshold}")
    return failures


# --------------------------------------------------------------------------
# main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "test", "all"], default="all")
    parser.add_argument("--seed", type=int, default=42, help="split seed")
    parser.add_argument("--category", default=None)
    parser.add_argument("--variant", default=None, help="limit to one variant")
    parser.add_argument("--no-robustness", action="store_true")
    parser.add_argument("--profile", action="store_true", help="cProfile the run")
    parser.add_argument(
        "--quick", action="store_true", help="CI subset: industrial categories, no robustness"
    )
    parser.add_argument("--tag", default=None, help="artifact dir name (default: timestamp)")
    args = parser.parse_args()

    import subprocess

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()[:8]

    categories = ["coil_table", "industrial_hmi"] if args.quick else None
    split = split_seed(split_seed=args.seed, categories=categories)
    wanted = {"dev": ["dev"], "test": ["test"], "all": ["dev", "test"]}[args.split]
    samples = [s for bucket in wanted for s in split[bucket]]
    if not samples:
        print("no samples selected", file=sys.stderr)
        return 2

    variant_names = [args.variant] if args.variant else list(VARIANTS)
    variants_out: dict[str, dict[str, object]] = {}
    for name in variant_names:
        started = time.perf_counter()
        variants_out[name] = run_variant(name, samples, category_filter=args.category)
        default = variants_out.get("default_tesseract") or variants_out[variant_names[0]]
        assert default is not None
        samples_list = default["samples"]
        assert isinstance(samples_list, list)
        mean_ms = float(np.mean([fnum(s, "elapsed_ms") for s in samples_list]))
        print(
            f"[{name}] field_acc={variants_out[name]['field_accuracy']:.3f} "
            f"route_acc={variants_out[name]['route_accuracy']:.3f} "
            f"cer={variants_out[name]['cer']:.3f} "
            f"mean_ms={mean_ms:.0f} "
            f"({time.perf_counter() - started:.1f}s)"
        )

    default = variants_out.get("default_tesseract") or variants_out[variant_names[0]]
    assert default is not None
    errors = analyze_errors(default)

    robustness: dict[str, object] = {"skipped": True}
    if not args.no_robustness and not args.quick:
        print("running robustness sweep ...")
        robustness = run_robustness(split["dev"], "default_tesseract")

    performance = run_performance(
        samples, args.variant or "default_tesseract", profile=args.profile
    )
    print(
        f"[perf] mean={performance['mean_ms']:.0f}ms p95={performance['p95_ms']:.0f}ms "
        f"throughput={performance['throughput_img_per_s']:.2f} img/s"
    )

    tag = args.tag or time.strftime("%Y%m%d-%H%M%S")
    out_dir = ARTIFACTS / f"{tag}_{sha}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.json").write_text(
        json.dumps(
            {
                "git_sha": sha,
                "git_branch": subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True,
                    text=True,
                ).stdout.strip(),
                "split_seed": args.seed,
                "split": {k: [s["gt"] for s in v] for k, v in split.items()},
                "split_used": wanted,
                "categories": categories,
                "variants": variant_names,
                "args": vars(args),
                "environment": environment_info(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    metrics: dict[str, object] = {"variants": variants_out}
    for name, payload in (
        ("metrics.json", metrics),
        ("errors.json", errors),
        ("robustness.json", robustness),
        ("performance.json", performance),
    ):
        (out_dir / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_charts(out_dir, metrics, robustness)
    print(f"artifact: {out_dir}")

    if args.quick:
        failures = check_gates(metrics)
        for failure in failures:
            print(f"GATE FAIL: {failure}", file=sys.stderr)
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
