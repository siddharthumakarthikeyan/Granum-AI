"""The documentation site: built output matches its source, and nothing links into a void.

Docs are generated (`tools/docs.py`) and the output is committed, because Vercel serves
`public/` as it is. These tests are what keeps the two in step.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
sys.path.insert(0, str(ROOT / "tools"))

docs = pytest.importorskip("docs", reason="tools/docs.py needs the markdown package")

HREF = re.compile(r'href="([^"]+)"')
ID = re.compile(r'id="([^"]+)"')


@pytest.fixture(scope="module")
def built() -> list[tuple[Path, str]]:
    return docs.build()


def test_every_page_in_the_nav_has_a_source(built):
    for section in docs.NAV:
        for slug in section.slugs:
            assert (ROOT / "docs_src" / f"{slug}.md").is_file(), slug


def test_every_page_has_a_title_and_a_summary(built):
    for slug, page in docs.PAGES.items():
        assert page.title and page.title != slug, f"{slug} has no title"
        assert page.summary, f"{slug} has no summary"
        assert len(page.summary) < 160, f"{slug}: summary is too long for a meta description"


def test_no_page_is_still_a_stub(built):
    for slug, page in docs.PAGES.items():
        assert "Coming next." not in page.body, f"{slug} is still a placeholder"
        assert len(page.body) > 1200, f"{slug} is suspiciously short"


def test_the_committed_output_is_up_to_date(built):
    stale = [path.relative_to(ROOT) for path, text in built
             if not path.exists() or path.read_text(encoding="utf-8") != text]
    assert not stale, f"run python3 tools/docs.py: {stale}"


def _local_targets() -> dict[str, set[str]]:
    """Every servable path of the site, with the element ids on it (Vercel's cleanUrls)."""
    targets: dict[str, set[str]] = {}
    for path in PUBLIC.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(PUBLIC).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore") if path.suffix == ".html" else ""
        ids = set(ID.findall(text))
        targets[f"/{relative}"] = ids
        if path.suffix == ".html":
            targets[f"/{relative[:-len('.html')]}"] = ids          # /docs/start/install
            if path.name == "index.html":
                targets[f"/{relative[:-len('/index.html')]}"] = ids  # /docs
    targets["/"] = targets.get("/index", set())
    return targets


def test_every_internal_link_and_anchor_resolves():
    targets = _local_targets()
    broken: list[str] = []
    for path in sorted(PUBLIC.rglob("*.html")):
        page = f"/{path.relative_to(PUBLIC).as_posix()}"
        for href in HREF.findall(path.read_text(encoding="utf-8")):
            if href.startswith(("http://", "https://", "mailto:")):
                continue
            if href.startswith("#"):
                if href[1:] not in targets[page]:
                    broken.append(f"{page} -> {href} (no such local anchor)")
                continue
            target, _, fragment = href.partition("#")
            target = (target.split("?")[0] or "/").rstrip("/") or "/"
            if target not in targets:
                broken.append(f"{page} -> {href} (no such page)")
            elif fragment and fragment not in targets[target]:
                broken.append(f"{page} -> {href} (no such anchor)")
    assert not broken, "\n".join(broken)


def test_search_index_covers_every_page(built):
    index = docs.search_index()
    assert {row["url"] for row in index} == {page.url for page in docs.PAGES.values()}
    assert all(row["text"] for row in index)
