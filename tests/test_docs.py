"""Tests for SHA-236: the reference docs stay complete and true to the CLI.

T1 compares the options documented in `docs/cli.md` with the `--help` output of every
command. T2 checks the sections of `docs/heuristics-and-limits.md`, T3 the index, T4 that
`CONTRIBUTING.md` and `DEVELOPMENT.md` give the same commands, and T5 that no relative link
is broken and no `authzlock` invocation in a code block uses a flag the CLI does not have.
T6 proves the T1 checker catches an invented option.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from typer.main import get_command
from typer.testing import CliRunner

from authzlock.cli import app

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
CLI_DOC = DOCS / "cli.md"
HEURISTICS_DOC = DOCS / "heuristics-and-limits.md"
INDEX_DOC = DOCS / "index.md"
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
DEVELOPMENT = REPO_ROOT / "DEVELOPMENT.md"

ROOT = ""  # key of the top-level `authzlock` command in the option maps below
FENCE = re.compile(r"^[ \t]*```([^\n]*)\n(.*?)^[ \t]*```[ \t]*$", re.DOTALL | re.MULTILINE)
INLINE_CODE = re.compile(r"`([^`\n]+)`")
OPTION = re.compile(r"(?<![\w-])(--?[A-Za-z][\w-]*)")
HEADING2 = re.compile(r"^## (.+)$", re.MULTILINE)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
SHELL_INFOS = {"sh", "bash", "shell", "console"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# T1 / T6: CLI options ---------------------------------------------------------------------


def _commands() -> set[str]:
    return set(getattr(get_command(app), "commands", {}))


def help_options() -> dict[str, set[str]]:
    """Option names in the `--help` output of `authzlock` and of each command."""
    runner = CliRunner()
    options: dict[str, set[str]] = {}
    for command in [ROOT, *sorted(_commands())]:
        args = [command, "--help"] if command else ["--help"]
        result = runner.invoke(app, args, env={"COLUMNS": "200", "TERMINAL_WIDTH": "200"})
        assert result.exit_code == 0, result.output
        # Rich colours the help when it detects CI (FORCE_COLOR, GITHUB_ACTIONS); drop the
        # escape codes so option names are matched the same everywhere.
        options[command] = set(OPTION.findall(ANSI.sub("", result.output)))
    return options


def documented_options(text: str) -> dict[str, set[str]]:
    """Option names in the option tables of a `docs/cli.md` text, by command.

    A table counts when its first header cell is `Option`. Tables under `## Global options`
    belong to `authzlock` itself, tables under `## Shared conventions` to every command, and
    tables under `## authzlock <command>` (including its subsections) to that command.
    """
    sections: dict[str, set[str]] = {}
    shared: set[str] = set()
    section: str | None = None
    in_table = False
    for line in text.splitlines():
        heading = re.match(r"^## (.+)$", line)
        if heading:
            title = heading.group(1).strip()
            command = re.fullmatch(r"authzlock (\w+)", title)
            if title == "Global options":
                section = ROOT
            elif title == "Shared conventions":
                section = "*"
            elif command:
                section = command.group(1)
            else:
                section = None
            if section is not None and section != "*":
                sections.setdefault(section, set())
            in_table = False
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not in_table:
            in_table = cells[0] == "Option"
            continue
        if section is None or set(cells[0]) <= {"-", ":"}:
            continue
        found = set(OPTION.findall(cells[0]))
        if section == "*":
            shared |= found
        else:
            sections[section] |= found
    return {name: found | (shared if name != ROOT else set()) for name, found in sections.items()}


def cli_doc_drift(text: str) -> list[str]:
    """Differences between a `docs/cli.md` text and the CLI's `--help`; empty when in sync."""
    actual = help_options()
    documented = documented_options(text)
    problems: list[str] = []
    for command in sorted(set(actual) | set(documented)):
        label = f"authzlock {command}".strip()
        if command not in documented:
            problems.append(f"{label}: not documented")
            continue
        if command not in actual:
            problems.append(f"{label}: documented but not a command")
            continue
        for option in sorted(actual[command] - documented[command]):
            problems.append(f"{label}: {option} is in --help but not documented")
        for option in sorted(documented[command] - actual[command]):
            problems.append(f"{label}: {option} is documented but not in --help")
    return problems


def test_t1_cli_docs_match_help_output() -> None:
    actual = help_options()
    assert set(actual) == {ROOT, "update", "check", "diff"}, sorted(actual)
    assert {"--settings", "--lockfile", "--quiet", "-q", "--help"} <= actual["check"]
    assert {"--base", "--format", "--fail-on"} <= actual["diff"]
    assert actual[ROOT] == {"--version", "--help"}

    assert cli_doc_drift(_read(CLI_DOC)) == []


def test_t6_checker_detects_a_fake_flag(tmp_path: Path) -> None:
    text = _read(CLI_DOC)
    anchor = "| `--fail-on any\\|loosened` |"
    assert text.count(anchor) == 1, "the diff option table has no --fail-on row"
    fake = "| `--colour WHEN` | `auto` | Colour the output. |\n"
    copy = tmp_path / "cli.md"
    copy.write_text(text.replace(anchor, fake + anchor), encoding="utf-8")

    assert cli_doc_drift(_read(copy)) == [
        "authzlock diff: --colour is documented but not in --help"
    ]

    # Removing an option from the docs is drift too.
    without = _read(copy).replace(fake, "").replace("| `--quiet`, `-q` |", "| |")
    assert cli_doc_drift(without) == [
        f"authzlock {command}: {option} is in --help but not documented"
        for command in ("check", "diff", "update")
        for option in ("--quiet", "-q")
    ]


# T2 ---------------------------------------------------------------------------------------

HEURISTIC_SECTIONS = [
    "`dynamic`",
    "The object-scoped flag",
    "Decorator detection",
    "Composed permissions",
    "What `check` does not prove",
]


def _sections(text: str) -> dict[str, str]:
    """Level-2 headings of `text` mapped to the body up to the next level-2 heading."""
    parts = HEADING2.split(FENCE.sub("", text))
    return {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts), 2)}


def test_t2_heuristics_page_has_five_sections() -> None:
    assert HEURISTICS_DOC.is_file(), "docs/heuristics-and-limits.md is missing"
    sections = _sections(_read(HEURISTICS_DOC))

    for title in HEURISTIC_SECTIONS:
        assert title in sections, f"no '## {title}' section; found {list(sections)}"
        assert sections[title], f"section '## {title}' is empty"


# T3 / T5: links ---------------------------------------------------------------------------


def _slug(heading: str) -> str:
    """The anchor GitHub gives a heading."""
    text = heading.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    text = FENCE.sub("", _read(path))
    return {_slug(h) for h in re.findall(r"^#{1,6} (.+)$", text, re.MULTILINE)}


def relative_links(path: Path) -> list[str]:
    """Targets of the markdown links in `path` that are not URLs, outside code."""
    text = INLINE_CODE.sub("", FENCE.sub("", _read(path)))
    return [t for t in LINK.findall(text) if not re.match(r"^[a-z][a-z0-9+.-]*:", t)]


def broken_links(path: Path, root: Path = REPO_ROOT) -> list[str]:
    """Relative links in `path` whose file or heading anchor does not exist."""
    problems: list[str] = []
    for target in relative_links(path):
        file_part, _, anchor = target.partition("#")
        resolved = (path.parent / file_part).resolve() if file_part else path
        name = path.relative_to(root)
        if not resolved.exists():
            problems.append(f"{name}: {target} does not exist")
        elif anchor and resolved.suffix == ".md" and anchor not in _anchors(resolved):
            problems.append(f"{name}: {target} has no heading #{anchor}")
    return problems


def test_t3_index_links_every_page_and_links_resolve() -> None:
    assert INDEX_DOC.is_file(), "docs/index.md is missing"
    linked = {(DOCS / target.partition("#")[0]).resolve() for target in relative_links(INDEX_DOC)}
    pages = {p.resolve() for p in DOCS.glob("*.md")} - {INDEX_DOC.resolve()}

    assert pages, "docs/ has no pages"
    missing = sorted(p.name for p in pages - linked)
    assert missing == [], f"docs/index.md does not link: {missing}"
    assert broken_links(INDEX_DOC) == []


def doc_pages() -> list[Path]:
    """Every documentation page whose links and code blocks are checked."""
    top = [REPO_ROOT / name for name in ("README.md", "CONTRIBUTING.md", "DEVELOPMENT.md")]
    return [*sorted(DOCS.glob("*.md")), *top, REPO_ROOT / "tests" / "fixtures" / "README.md"]


INVOCATION = re.compile(r"\bauthzlock[ \t]+(.*)")
SEPARATORS = re.compile(r"\s(?:&&|\|\||\||;)\s|\s#")
HOOK_ARGS = re.compile(r"id:\s*authzlock-(check|update)\s*\n\s*args:\s*(\[[^\n]*\])")


def unknown_flags(text: str, options: dict[str, set[str]]) -> list[str]:
    """`authzlock` invocations in the code of `text` that use a flag the CLI lacks.

    Code is every fenced block and inline code span. An invocation runs from `authzlock`
    to the end of the line or the next `&&`, `|`, `;` or comment. Hook `args` in a
    pre-commit YAML snippet count as an invocation of the hook's command.
    """
    fenced = [body for _, body in FENCE.findall(text)]
    code = "\n".join(fenced + INLINE_CODE.findall(FENCE.sub("", text)))
    problems: list[str] = []
    invocations: list[tuple[str, list[str]]] = []
    for line in code.splitlines():
        match = INVOCATION.search(line)
        if not match:
            continue
        words = SEPARATORS.split(" " + match.group(1))[0].split()
        command = words[0] if words and words[0] in options else ROOT
        invocations.append((command, words))
    for body in fenced:
        for command, args in HOOK_ARGS.findall(body):
            invocations.append((command, [str(a) for a in yaml.safe_load(args)]))
    for command, words in invocations:
        for word in words:
            flag = word.split("=", 1)[0].strip("\"',")
            if OPTION.fullmatch(flag) and flag not in options[command]:
                problems.append(f"authzlock {command} {flag}".replace("  ", " "))
    return problems


def test_t5_no_broken_links_or_unknown_flags() -> None:
    options = help_options()
    pages = doc_pages()
    assert {p.name for p in pages} >= {"cli.md", "index.md", "README.md", "CONTRIBUTING.md"}

    broken = [problem for page in pages for problem in broken_links(page)]
    assert broken == []
    unknown = {
        f"{page.relative_to(REPO_ROOT)}: {problem}"
        for page in pages
        for problem in unknown_flags(_read(page), options)
    }
    assert unknown == set()


def test_t5_checkers_catch_a_broken_link_and_an_unknown_flag(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    (tmp_path / "other.md").write_text("# Other\n\n## Real heading\n", encoding="utf-8")
    page.write_text(
        "See [other](other.md#real-heading), [gone](gone.md), [bad](other.md#nope) and "
        "[site](https://example.com).\n\n"
        "```sh\nauthzlock check --strict && git log --oneline\n```\n\n"
        "Run `python -m authzlock diff --base HEAD --colour=auto`.\n\n"
        '```yaml\n      - id: authzlock-update\n        args: ["--dry-run"]\n```\n',
        encoding="utf-8",
    )
    assert broken_links(page, root=tmp_path) == [
        "page.md: gone.md does not exist",
        "page.md: other.md#nope has no heading #nope",
    ]
    assert unknown_flags(_read(page), help_options()) == [
        "authzlock check --strict",
        "authzlock diff --colour",
        "authzlock update --dry-run",
    ]


# T4 ---------------------------------------------------------------------------------------


def shell_commands(text: str) -> set[str]:
    """The commands in the shell code blocks of `text`, one per logical line."""
    commands: set[str] = set()
    for info, body in FENCE.findall(text):
        if info.strip().split(" ")[0] not in SHELL_INFOS:
            continue
        joined = re.sub(r"\\\n\s*", " ", body)
        for line in joined.splitlines():
            line = line.strip().removeprefix("$ ").strip()
            if line and not line.startswith("#"):
                commands.add(" ".join(line.split()))
    return commands


def test_t4_contributing_commands_equal_development_md() -> None:
    assert CONTRIBUTING.is_file(), "CONTRIBUTING.md is missing"
    development = shell_commands(_read(DEVELOPMENT))
    contributing = shell_commands(_read(CONTRIBUTING))

    assert "nox" in development and "pytest" in development, sorted(development)
    assert contributing == development, (
        f"only in CONTRIBUTING.md: {sorted(contributing - development)}; "
        f"only in DEVELOPMENT.md: {sorted(development - contributing)}"
    )
