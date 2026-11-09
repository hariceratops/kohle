"""Layer 3 — no regression without a currency unit (issues 107, 124). Design §14."""

from tests.pre_feature_baseline import BASELINE, run_script


def test_every_command_matches_the_107_baseline(session_factory) -> None:
    assert run_script(session_factory) == BASELINE.read_text()


def test_eur_only_tables_are_byte_identical(session_factory) -> None:
    output = run_script(session_factory)

    tables: dict[str, str] = {}
    for block in output.split("\n$ "):
        command, _, body = block.removeprefix("$ ").partition("\n")
        tables.setdefault(command, body)
    for command in ("net-worth", "positions", "balance Depot", "realised"):
        body = tables[command]
        assert "[exit 0]" in body, command
        assert "quoted in" not in body, command
        assert "in EUR" not in body and "currency" not in body.split("\n")[1], command

    positions = tables["positions"]
    assert "130.50" in positions and "130.5 " not in positions
