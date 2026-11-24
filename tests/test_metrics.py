"""Unit tests for the metric reference implementations."""

from engine.metrics import (
    cer,
    coil_id_accuracy,
    field_accuracy,
    processing_time,
    table_structure_accuracy,
    wer,
)


def pytest_approx(expected):
    class _Approx:
        def __eq__(self, other):
            return abs(other - expected) < 1e-9

        def __repr__(self):
            return f"~{expected}"

    return _Approx()


class TestCER:
    def test_identical_is_zero(self):
        assert cer("Hoa don gia tri gia tang", "Hoa don gia tri gia tang") == 0.0

    def test_case_and_whitespace_ignored(self):
        assert cer("Total  Amount", "total amount") == 0.0

    def test_partial_edit_distance(self):
        # "abc" -> "abd" is 1 substitution over 3 chars.
        assert cer("abc", "abd") == pytest_approx(1 / 3)

    def test_missing_diacritic_is_one_char(self):
        assert cer("hoa don", "ho don") == pytest_approx(1 / 7)

    def test_empty_reference_empty_hypothesis_is_zero(self):
        assert cer("", "") == 0.0

    def test_empty_reference_nonempty_hypothesis_is_one(self):
        assert cer("", "extra") == 1.0


class TestWER:
    def test_identical_is_zero(self):
        assert wer("the coil table", "the coil table") == 0.0

    def test_one_word_substitution(self):
        assert wer("the coil table", "the steel table") == pytest_approx(1 / 3)

    def test_extra_words_count(self):
        assert wer("three words here", "four words here now") == pytest_approx(2 / 3)

    def test_empty_reference_nonempty_hypothesis_is_one(self):
        assert wer("", "words") == 1.0


class TestTableStructureAccuracy:
    def test_identical_tables_full_score(self):
        cells = [(r, c) for r in range(3) for c in range(4)]
        result = table_structure_accuracy(cells, cells)
        assert result.adjacency.f1 == 1.0
        assert result.missing_cells == 0 and result.extra_cells == 0

    def test_shifted_column_lowers_f1(self):
        ref = [(0, 0), (0, 1), (1, 0), (1, 1)]
        pred = [(0, 1), (0, 2), (1, 1), (1, 2)]  # everything shifted one column
        result = table_structure_accuracy(ref, pred)
        assert 0.0 < result.adjacency.f1 < 1.0

    def test_empty_prediction_zero_recall(self):
        ref = [(0, 0), (0, 1)]
        result = table_structure_accuracy(ref, [])
        assert result.adjacency.recall == 0.0
        assert result.missing_cells == 2


class TestFieldAndCoilAccuracy:
    def test_field_accuracy_numbers_within_tolerance(self):
        ref = {"THICK": 1.2, "WIDTH": 1250}
        pred = {"THICK": 1.2000001, "WIDTH": 1250}
        assert field_accuracy(ref, pred) == 1.0

    def test_field_accuracy_counts_misses(self):
        ref = {"a": "X", "b": "Y", "c": "Z"}
        pred = {"a": "x", "b": "wrong"}
        assert field_accuracy(ref, pred) == pytest_approx(1 / 3)

    def test_coil_id_normalization(self):
        ref = {"HOT_COIL_NO": "H123-45"}
        pred = {"HOT_COIL_NO": "h12345"}
        assert coil_id_accuracy(ref, pred) == 1.0

    def test_coil_id_digit_difference_fails(self):
        ref = {"HOT_COIL_NO": "H12345"}
        pred = {"HOT_COIL_NO": "H12346"}
        assert coil_id_accuracy(ref, pred) == 0.0


class TestProcessingTime:
    def test_mean_p95_batch(self):
        stats = processing_time([100.0, 200.0, 300.0, 400.0, 500.0])
        assert stats["mean_ms"] == 300.0
        assert stats["p95_ms"] == 500.0  # nearest-rank p95 of 5 items
        assert stats["batch_ms"] == 1500.0

    def test_empty(self):
        assert processing_time([]) == {"mean_ms": 0.0, "p95_ms": 0.0, "batch_ms": 0.0}
