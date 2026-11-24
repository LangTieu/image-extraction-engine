"""End-to-end test: the seed dataset validates against the unified schema."""

from pathlib import Path

from benchmark.validate import validate_dataset

SEED = Path(__file__).resolve().parents[1] / "benchmark" / "seed"


class TestSeedDataset:
    def test_seed_dataset_exists(self):
        assert SEED.is_dir(), "run python -m benchmark.tools.generate_seed first"

    def test_seed_dataset_passes_validator(self):
        passed, failed = validate_dataset(SEED)
        assert failed == 0
        # 7 categories x 5 samples in the P0 seed set
        assert passed >= 35
