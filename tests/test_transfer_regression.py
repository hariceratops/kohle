"""Layer 3 — no regression without a transfer rule (issues 126, 136). Design §18.6."""

from tests.transfer_baseline import BASELINE, run_script


def test_every_command_matches_the_pre_feature_transfer_baseline(session_factory) -> None:
    assert run_script(session_factory) == BASELINE.read_text()
