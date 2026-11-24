# Metric Definitions (P0)

Reference implementations: `engine/metrics.py`. Unit tests: `tests/test_metrics.py`.

Normalization common to text metrics: runs of whitespace collapse to a
single space, ends are stripped, case is folded. Reference and hypothesis
are compared after normalization.

## OCR Character Error Rate (CER)

    CER = levenshtein(ref_chars, hyp_chars) / len(ref_chars)

Character-level Levenshtein distance on the normalized strings. If the
reference is empty, CER = 0 when the hypothesis is empty, else 1. Reported
per text block and per document (concatenated blocks).

## Word Error Rate (WER)

    WER = word_levenshtein(ref_words, hyp_words) / len(ref_words)

Words are the whitespace-separated tokens of the normalized text. Same
empty-reference convention as CER.

## Table Structure Accuracy

TEDS is heavy to bootstrap; P0 standardizes a **cell-adjacency F1**
(TEDS-lite): from each table's set of (row_index, col_index) cells, build
the set of right- and down-neighbour pairs. With that set as the positive
class:

    precision = |ref_adj INTERSECT pred_adj| / |pred_adj|
    recall    = |ref_adj INTERSECT pred_adj| / |ref_adj|
    Structure Accuracy (F1) = 2*P*R / (P + R)

Adjacency pairs capture merged cells and shifted rows/columns better than
plain cell counts. TEDS remains a candidate to add in P3 for comparison.

## Field-level Accuracy

    Field Accuracy = (# reference fields whose prediction matches) / (# reference fields)

Strings match case-normalized and stripped; numbers match within a tolerance
(default 1e-6). A missing prediction counts as a miss.

## Coil ID exact-match Accuracy

Exact-match rate for HOT_COIL_NO / COLD_COIL_NO after ID normalization:
uppercase, spaces/hyphens/underscores removed (so `h123-45` == `H12345`).
Exact match means exact; a digit-level difference is a failure, flagged for
review rather than absorbed.

## Processing Time

    mean_ms  = sum(durations_ms) / n
    p95_ms   = durations_ms[round(0.95 * (n - 1))]   (sorted, nearest-rank)
    batch_ms = sum(durations_ms)

Reported per category and per pipeline variant; the benchmark harness (P8)
adds bootstrap confidence intervals.

## Later-phase metrics (defined in P5/P8, listed for completeness)

Router top-1 accuracy; error-catch (recall of known wrong values) and review
rate at a threshold; confidence calibration ECE; robustness curves vs
perturbation severity.
