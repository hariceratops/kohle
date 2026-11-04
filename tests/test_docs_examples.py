"""Documentation examples are tests: a `console` block that drifts fails the suite (design §4)."""

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner

from kohle.app.cli.cli import cli
from tests import docs_examples
from tests.docs_examples import (
    DOCS_TODAY,
    INIT_TOML,
    Example,
    collect,
    parse_page,
    run_example,
)

ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES, _PROBLEMS = collect(ROOT)


@pytest.fixture(scope="session")
def template_ledger(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One `init`-made ledger, copied per example; a session fixture cannot use `monkeypatch`."""
    base = tmp_path_factory.mktemp("docs-template")
    ledger = base / "kohle.db"
    config = base / "config"
    (config / "kohle").mkdir(parents=True)
    (config / "kohle" / "init.toml").write_text(INIT_TOML)
    env = {"KOHLE_DB": str(ledger), "XDG_CONFIG_HOME": str(config), "HOME": str(base)}
    result = CliRunner().invoke(cli, ["init"], env=env, prog_name="kohle-cli")
    assert result.exit_code == 0, result.output
    return ledger


@pytest.fixture
def run_in_scratch_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pin_today: Callable[[date], None],
    template_ledger: Path,
) -> Callable[[Example], str | None]:
    def run(example: Example) -> str | None:
        home = tmp_path / "home"
        docs_examples.prepare_home(
            home, example, template_ledger, ROOT / "docs" / "examples", monkeypatch
        )
        pin_today(DOCS_TODAY)
        return run_example(example, home)

    return run


def _id(example: Example) -> str:
    return f"{example.page}:{example.line}"


@pytest.mark.parametrize("example", _EXAMPLES, ids=_id)
def test_docs_example(example: Example, run_in_scratch_home) -> None:
    failure = run_in_scratch_home(example)
    if failure is not None:
        pytest.fail(failure, pytrace=False)


def test_there_is_at_least_one_checked_example() -> None:
    assert _EXAMPLES


def test_docs_pages_are_well_formed() -> None:
    assert not _PROBLEMS, "\n".join(_PROBLEMS)


def test_a_wrong_block_fails_naming_its_page_and_block(run_in_scratch_home) -> None:
    page = (
        "# Sample\n"
        "\n"
        "```console\n"
        "$ kohle-cli list-accounts\n"
        "account    type    iban\n"
        "---------  ------  ------\n"
        "People     asset   -\n"
        "$ kohle-cli add-account Checking --type asset\n"
        "Added account Savings (asset) with id 2\n"
        "```\n"
    )
    examples, problems = parse_page("docs/sample.md", page)
    assert problems == []
    assert len(examples) == 1

    failure = run_in_scratch_home(examples[0])

    assert failure is not None
    assert "docs/sample.md:8" in failure
    assert "Added account Savings" in failure
    assert "Added account Checking" in failure


def test_a_right_block_passes(run_in_scratch_home) -> None:
    page = "```console\n$ kohle-cli list-importer-plugins\nkohle-deutsche-bank\nkohle-simple-broker\n```\n"
    examples, _ = parse_page("docs/sample.md", page)
    assert run_in_scratch_home(examples[0]) is None


def test_unmarked_blocks_are_not_run() -> None:
    page = "```sh\nuv sync\n```\n\n```toml\n[ledger]\npath = \"x\"\n```\n"
    assert parse_page("docs/sample.md", page) == ([], [])


def test_invocation_outside_a_console_block_is_a_problem() -> None:
    page = "```sh\n$ kohle-cli init\n```\n"
    _, problems = parse_page("docs/sample.md", page)
    assert len(problems) == 1
    assert "docs/sample.md:2" in problems[0]


def test_illustration_fence_may_show_invocations() -> None:
    page = "<!-- docs: illustration -->\n```sh\n$ kohle-cli init\n```\n"
    assert parse_page("docs/sample.md", page) == ([], [])


def test_unknown_option_and_unknown_uses_are_problems() -> None:
    page = "<!-- docs: bogus -->\n```console\n$ kohle-cli init\n```\n"
    assert parse_page("docs/sample.md", page)[1]
    page = "<!-- docs: uses missing.toml -->\n```console\n$ kohle-cli init\n```\n"
    assert parse_page("docs/sample.md", page)[1]


def test_unsupported_commands_are_problems() -> None:
    for line in ("$ ls", "$ kohle-cli list-accounts | head", "$ kohle-cli init > out"):
        _, problems = parse_page("docs/sample.md", f"```console\n{line}\nx\n```\n")
        assert problems, line


def test_file_fence_feeds_uses_and_continuations_join() -> None:
    page = (
        "<!-- docs: file ~/.config/kohle/init.toml -->\n"
        "```toml\nstate = \"BY\"\n```\n\n"
        "<!-- docs: first-run uses ~/.config/kohle/init.toml -->\n"
        "```console\n$ kohle-cli add-account A \\\n    --type asset\nout\n```\n"
    )
    (example,), problems = parse_page("docs/sample.md", page)
    assert problems == []
    assert example.first_run
    assert example.files == {".config/kohle/init.toml": 'state = "BY"\n'}
    assert example.commands[0].text == "kohle-cli add-account A --type asset"
    assert example.commands[0].expected == ["out"]


def test_readme_is_scanned_alongside_the_docs_pages(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text("```console\n$ kohle-cli list-importer-plugins\nx\n```\n")
    (tmp_path / "README.md").write_text(
        "```console\n$ kohle-cli list-importer-plugins\nx\n```\n\n```bash\n$ kohle-cli init\n```\n"
    )

    examples, problems = collect(tmp_path)

    assert sorted(example.page for example in examples) == ["README.md", "docs/page.md"]
    assert len(problems) == 1
    assert problems[0].startswith("README.md:")


def test_the_shipped_readme_has_a_checked_example() -> None:
    assert any(example.page == "README.md" for example in _EXAMPLES)
