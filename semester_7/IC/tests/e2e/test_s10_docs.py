"""S10: the documents the project is handed in with (README, report, demo script)."""

import re
from pathlib import Path

import pytest

from .helpers import loki_query, prom_query, tempo_search, wait_until

REPO = Path(__file__).resolve().parents[2]
REPORT = REPO / "docs" / "REPORT.md"
DEMO = REPO / "docs" / "DEMO.md"
README = REPO / "README.md"
SCREENSHOTS = REPO / "docs" / "screenshots"

BLOCK = re.compile(r"```(promql|logql|traceql)\n(.*?)```", re.S)
REPO_PATH = re.compile(
    r"`((?:services|tests|observability|db|gateway|scripts|docs)/[^`\s]*"
    r"|Makefile|docker-compose(?:\.dev)?\.yml|pyproject\.toml|\.env\.example)`"
)
SCREENSHOT = re.compile(r"screenshots/(\d\d-[a-z-]+\.png)")
README_SECTIONS = [
    "Архітектура",
    "Що потрібно",
    "Швидкий старт",
    "Облікові записи",
    "Адреси",
    "Сценарії",
    "Команди",
    "Тестування",
    "Структура репозиторію",
    "Режим розробки",
    "Усунення проблем",
]
REPORT_SECTIONS = [
    "Мета роботи і завдання",
    "Архітектура системи",
    "Реалізація",
    "Дослідження аномалій",
    "Тестування",
    "Висновки",
    "Додаток",
]


def _queries() -> list[tuple[str, str, str]]:
    found = []
    for path in (REPORT, DEMO):
        for language, body in BLOCK.findall(path.read_text(encoding="utf-8")):
            found.append((path.name, language, body.strip()))
    return found


@pytest.mark.parametrize(("document", "language", "query"), _queries())
def test_s10_ac4_every_query_in_the_documents_runs(document, language, query):
    if language == "promql":
        wait_until(lambda: prom_query(query), timeout=60, interval=2, desc=f"{document}: {query}")
    elif language == "logql":
        loki_query(query, since_s=900)
    else:
        tempo_search(query, since_s=900)


def test_s10_ac4_paths_in_the_report_exist():
    text = REPORT.read_text(encoding="utf-8")
    missing = [path for path in REPO_PATH.findall(text) if not (REPO / path).exists()]
    assert not missing


def test_s10_ac4_every_screenshot_is_listed():
    listed = set(SCREENSHOT.findall((SCREENSHOTS / "README.md").read_text(encoding="utf-8")))
    listed |= set(re.findall(r"`(\d\d-[a-z-]+\.png)`", (SCREENSHOTS / "README.md").read_text()))
    used = set(SCREENSHOT.findall(REPORT.read_text(encoding="utf-8")))
    assert len(used) == 13
    assert used <= listed, used - listed


def test_s10_ac1_ac2_documents_have_their_sections():
    readme = README.read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", readme, re.M)
    assert headings == README_SECTIONS
    report = REPORT.read_text(encoding="utf-8")
    titles = [re.sub(r"^\d+\.\s*", "", h) for h in re.findall(r"^## (.+)$", report, re.M)]
    assert titles == REPORT_SECTIONS
    assert len(re.findall(r"^### 3\.\d\. ", report, re.M)) == 10
    assert len(re.findall(r"^### 4\.\d\. ", report, re.M)) == 4


def test_s10_ac2_no_placeholders_left_but_the_title_block():
    for path in (README, REPORT, DEMO):
        text = path.read_text(encoding="utf-8")
        # "T[O]DO" keeps this file out of the S10-AC7 grep for leftover notes.
        assert not re.search(r"\b(T[O]DO|TBD|lorem)\b|\{\{", text, re.I), path.name
