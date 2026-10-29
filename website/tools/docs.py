#!/usr/bin/env python3
"""Build the documentation site: `docs_src/*.md` -> `public/docs/**.html` + a search index.

One layout for every page, so the docs read as one book rather than a pile of pages: the
same header as the rest of the site, a sidebar built from NAV below, a breadcrumb, an
"On this page" list built from the page's own headings, and previous/next links that
follow NAV's order.

    python3 tools/docs.py          # write public/docs
    python3 tools/docs.py --check  # fail if the output is out of date (CI)

Pages are Markdown with a small front matter block:

    ---
    title: Create a dataset version
    summary: One sentence, used on section pages, in search and as the meta description.
    ---

Markdown extras: tables, fenced code, `!!! note "Title"` callouts, and raw HTML (the
diagrams are inline SVG). Every heading gets an id, so headings are linkable.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs_src"
OUTPUT = ROOT / "public" / "docs"

SITE_TITLE = "Granum documentation"
STATUS_LABELS = {"available": "Available", "partial": "Partially included", "planned": "Not yet included"}


@dataclass
class Page:
    slug: str           # "start/install", or "index" for the front page
    title: str
    summary: str = ""
    body: str = ""
    headings: list[tuple[int, str, str]] = field(default_factory=list)  # level, id, text
    status: str = ""

    @property
    def url(self) -> str:
        return "/docs" if self.slug == "index" else f"/docs/{self.slug}"

    @property
    def out_path(self) -> Path:
        return OUTPUT / ("index.html" if self.slug == "index" else f"{self.slug}.html")


@dataclass
class Section:
    key: str
    title: str
    blurb: str
    slugs: list[str]


#: The book's order. Everything in the sidebar, the section pages, the previous/next
#: links and the search index comes from here.
NAV: list[Section] = [
    Section("start", "Start with Granum",
            "Install, understand the workflow, and check which capabilities are included in your build.",
            ["reference/features", "start/install", "start/activate", "start/first-project", "start/the-loop", "start/source"]),
    Section("course", "Guided aerial-data course",
            "Start with a real sample. Every lesson explains the action, its evidence and its limits, with actual screenshots and captioned recordings.",
            ["course/start", "course/setup", "course/data", "course/import", "course/explore",
             "course/baseline", "course/review", "course/train", "course/results", "course/compare",
             "course/handoff", "course/backup", "course/next"]),
    Section("concepts", "Concepts",
            "The ideas the product is built on. Read these once and the rest of the app explains itself.",
            ["concepts/model", "concepts/projects", "concepts/versions", "concepts/dataset-versions",
             "concepts/verification", "concepts/identity", "concepts/runs", "concepts/evidence"]),
    Section("guides", "Bring data in",
            "Import, check and organise datasets while preserving their identity and history.",
            ["guides/import", "guides/pull-from-projects", "guides/projects", "data/formats", "data/tabular", "data/images", "data/video"]),
    Section("explore", "Explore and diagnose",
            "Move from a distribution or model error to the individual samples behind it.",
            ["guides/browse", "explore/workspace", "explore/charts", "explore/calculations", "explore/workflows",
             "explore/embeddings", "explore/trajectories", "explore/duplicates", "explore/health", "explore/evaluation"]),
    Section("improve", "Review and improve",
            "Correct labels, review model suggestions, balance samples, and save reproducible dataset versions.",
            ["guides/review", "guides/edit", "data/boxes", "data/masks", "data/keypoints", "improve/prelabel",
             "improve/sam", "improve/weights", "guides/isolate-remove", "guides/dataset-versions", "guides/augmentation", "improve/export"]),
    Section("measure", "Train and measure",
            "Record experiments, inspect sample behaviour and compare a candidate against a baseline.",
            ["guides/train", "measure/tasks", "guides/runs", "guides/learning", "guides/findings", "guides/compare", "measure/metrics", "measure/recipes"]),
    Section("integrations", "Connect your training code",
            "Use Granum with your model framework and keep predictions linked to the correct source samples.",
            ["integrations/pytorch", "integrations/ultralytics", "integrations/hugging-face", "integrations/lightning",
             "integrations/detectron2", "integrations/supergradients"]),
    Section("python", "Build with Python",
            "Create typed tables, transform samples, collect metrics and extend your own workflow.",
            ["guides/python", "python/tables", "python/schemas", "python/transforms", "python/runs", "python/custom-metrics", "python/storage", "python/api"]),
    Section("operate", "Run your workspace",
            "Configure the service, share access, preserve data and understand deployment boundaries.",
            ["operate/service", "operate/configuration", "operate/shared", "operate/cloud", "operate/remote",
             "guides/operations", "operate/upgrades"]),
    Section("planned", "Not yet included",
            "Reserved guides for planned capabilities. Each section explains its intended scope and the current alternative.",
            ["planned/advanced-analysis", "planned/compute", "planned/enterprise", "planned/spatial", "planned/extensions"]),
    Section("reference", "Reference",
            "Look things up: every screen, every key, every check, every file.",
            ["reference/screens", "reference/shortcuts", "reference/preflight", "reference/models",
             "reference/cli", "reference/rest", "reference/requirements", "reference/files", "reference/limits", "reference/releases", "reference/glossary"]),
    Section("help", "Help",
            "When something is wrong, or you want to know how Granum handles your data.",
            ["help/troubleshooting", "help/faq", "help/privacy"]),
]

FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
HEADING = re.compile(r'<h([23]) id="([^"]+)">(.*?)</h\1>', re.S)
TAGS = re.compile(r"<[^>]+>")


def read_page(slug: str) -> Page:
    path = SOURCE / f"{slug}.md"
    if not path.exists():
        raise SystemExit(f"missing page: {path.relative_to(ROOT)}")
    text = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    match = FRONT_MATTER.match(text)
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip()
        text = text[match.end():]
    renderer = markdown.Markdown(
        extensions=["tables", "fenced_code", "admonition", "attr_list", "toc", "sane_lists", "md_in_html"],
        extension_configs={"toc": {"permalink": False}},
    )
    body = renderer.convert(text)
    headings = [(int(level), ident, TAGS.sub("", inner).strip()) for level, ident, inner in HEADING.findall(body)]
    status = meta.get("status", "")
    if status and status not in STATUS_LABELS:
        raise SystemExit(f"unknown documentation status {status!r}: {slug}")
    return Page(slug=slug, title=meta.get("title", slug), summary=meta.get("summary", ""),
                body=body, headings=headings, status=status)


def status_badge(status: str) -> str:
    if not status:
        return ""
    return f'<span class="doc-status {status}">{STATUS_LABELS[status]}</span>'


def section_of(slug: str) -> Section | None:
    return next((s for s in NAV if slug in s.slugs), None)


def sidebar(current: str) -> str:
    out = ['<nav class="doc-nav" aria-label="Documentation">']
    out.append(f'<a class="doc-nav-home{" on" if current == "index" else ""}" href="/docs">Start here</a>')
    for section in NAV:
        expanded = current in section.slugs or (current == "index" and section.key == "start")
        out.append(f'<details class="doc-nav-group"{" open" if expanded else ""}>'
                   f'<summary class="doc-nav-title">{html.escape(section.title)}</summary><ul>')
        for slug in section.slugs:
            page = PAGES[slug]
            on = " class=\"on\"" if slug == current else ""
            aria = ' aria-current="page"' if slug == current else ""
            badge = status_badge(page.status) if page.status == "planned" else ""
            out.append(f'<li><a href="{page.url}"{on}{aria}>{html.escape(page.title)}{badge}</a></li>')
        out.append("</ul></details>")
    out.append("</nav>")
    return "\n".join(out)


def on_this_page(page: Page) -> str:
    items = [h for h in page.headings if h[0] == 2]
    if len(items) < 2:
        return ""
    links = "".join(f'<li><a href="#{ident}">{html.escape(text)}</a></li>' for _, ident, text in items)
    return f'<aside class="doc-toc" aria-label="On this page"><p>On this page</p><ul>{links}</ul></aside>'


def neighbours(slug: str) -> tuple[Page | None, Page | None]:
    order = [s for section in NAV for s in section.slugs]
    if slug == "index":
        return None, PAGES[order[0]]
    index = order.index(slug)
    return (PAGES[order[index - 1]] if index else PAGES["index"],
            PAGES[order[index + 1]] if index + 1 < len(order) else None)


def breadcrumb(page: Page) -> str:
    section = section_of(page.slug)
    trail = ['<a href="/docs">Documentation</a>']
    if section:
        trail.append(f'<a href="/docs#{section.key}">{html.escape(section.title)}</a>')
    return '<nav class="doc-crumb" aria-label="Breadcrumb">' + '<span aria-hidden="true">/</span>'.join(trail) + "</nav>"


def render(page: Page) -> str:
    previous, following = neighbours(page.slug)
    depth = page.slug.count("/")
    description = page.summary or "Granum documentation."
    steps = []
    if previous:
        steps.append(f'<a class="doc-step prev" href="{previous.url}"><span>Previous</span>{html.escape(previous.title)}</a>')
    if following:
        steps.append(f'<a class="doc-step next" href="{following.url}"><span>Next</span>{html.escape(following.title)}</a>')
    return TEMPLATE.format(
        title=html.escape(f"{page.title} · {SITE_TITLE}" if page.slug != "index" else SITE_TITLE),
        description=html.escape(description),
        url=page.url,
        sidebar=sidebar(page.slug),
        crumb=breadcrumb(page),
        heading=html.escape(page.title),
        summary=f'<p class="doc-summary">{html.escape(page.summary)}</p>' if page.summary else "",
        status=status_badge(page.status),
        toc=on_this_page(page),
        body=page.body,
        steps=f'<div class="doc-steps">{"".join(steps)}</div>' if steps else "",
        depth=depth,
    )


TEMPLATE = """<!doctype html>
<html lang="en" class="no-js">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <meta name="theme-color" content="#ffffff">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:type" content="article">
  <meta property="og:image" content="/assets/og.jpg">
  <link rel="canonical" href="https://granum.app{url}">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/styles.css">
  <link rel="stylesheet" href="/docs/docs.css">
  <script>document.documentElement.classList.remove("no-js");</script>
</head>
<body class="doc-body">
  <a class="skip" href="#main">Skip to content</a>
  <header class="site-header doc-header">
    <div class="wrap">
      <a class="brand" href="/" aria-label="Granum home"><img src="/assets/lockup-ink.svg" alt="Granum" width="128" height="32"></a>
      <span class="doc-badge"><a href="/docs">Docs</a></span>
      <nav class="nav" id="nav" aria-label="Main">
        <a href="/#tour">Product</a>
        <a href="/#plans">Pilots</a>
        <a href="/docs/help/faq">FAQ</a>
      </nav>
      <div class="header-actions">
        <button class="doc-search-button" type="button" data-search aria-label="Search documentation">
          <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="9" cy="9" r="5.5"/><path d="m13.5 13.5 3 3"/></svg>
          <span>Search</span><kbd>/</kbd>
        </button>
        <a class="btn primary small" href="/download">Download</a>
        <button class="menu-button" type="button" aria-controls="doc-sidebar" aria-expanded="false" aria-label="Menu" data-sidebar-toggle>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
        </button>
      </div>
    </div>
  </header>

  <div class="doc-shell">
    <div class="doc-sidebar" id="doc-sidebar">
      {sidebar}
    </div>
    <main class="doc-main" id="main">
      <article class="doc-article">
        {crumb}
{status}
        <h1>{heading}</h1>
        {summary}
        {body}
        {steps}
      </article>
      {toc}
    </main>
  </div>

  <footer class="doc-footer">
    <div class="wrap">
    <p>© Granum. Local-first data workflows.</p>
      <p><a href="/">Product</a><a href="/download">Download</a><a href="/privacy">Privacy</a><a href="/docs/help/troubleshooting">Support</a></p>
    </div>
  </footer>

  <div class="doc-search" data-search-panel hidden>
    <div class="doc-search-box" role="dialog" aria-modal="true" aria-label="Search documentation">
    <input type="search" aria-label="Search documentation" aria-controls="doc-search-results" placeholder="Search the documentation" autocomplete="off" spellcheck="false" data-search-input>
    <ul id="doc-search-results" aria-label="Search results" aria-live="polite" data-search-results></ul>
      <p class="doc-search-hint"><kbd>↑</kbd><kbd>↓</kbd> to move · <kbd>Enter</kbd> to open · <kbd>Esc</kbd> to close</p>
    </div>
  </div>

  <script src="/docs/docs.js" defer></script>
</body>
</html>
"""


def front_page() -> Page:
    """The docs home: what the book is, and every section with its pages."""
    page = read_page("index")
    cards = ['<div class="doc-sections">']
    for section in NAV:
        links = "".join(
            f'<li><a href="{PAGES[s].url}">{html.escape(PAGES[s].title)}</a>{status_badge(PAGES[s].status) if PAGES[s].status == "planned" else ""}'
            f'<span>{html.escape(PAGES[s].summary)}</span></li>' for s in section.slugs)
        cards.append(
            f'<section class="doc-section">'
            f'<h2 id="{section.key}">{html.escape(section.title)}</h2>'
            f'<p class="doc-section-blurb">{html.escape(section.blurb)}</p>'
            f'<ul>{links}</ul></section>')
    cards.append("</div>")
    page.body += "\n".join(cards)
    # The section headings are added after rendering, so the page's own list of headings
    # (its "On this page") is taken again here.
    page.headings = [(int(level), ident, TAGS.sub("", inner).strip())
                     for level, ident, inner in HEADING.findall(page.body)]
    return page


def search_index() -> list[dict[str, object]]:
    out = []
    for slug, page in PAGES.items():
        section = section_of(slug)
        text = TAGS.sub(" ", page.body)
        text = html.unescape(re.sub(r"\s+", " ", text)).strip()
        out.append({
            "title": page.title,
            "url": page.url,
            "section": section.title if section else "Start here",
            "summary": page.summary,
            "status": STATUS_LABELS.get(page.status, ""),
            "headings": [h[2] for h in page.headings],
            # Long lessons include troubleshooting and recovery guidance near the end.
            # Index the whole article, not just its introductory paragraphs.
            "text": text,
        })
    return out


PAGES: dict[str, Page] = {}


def feature_inventory() -> list[dict[str, str]]:
    return json.loads((ROOT / "docs_features.json").read_text(encoding="utf-8"))["features"]


def feature_page() -> Page:
    page = read_page("reference/features")
    features = feature_inventory()
    for area in dict.fromkeys(item["area"] for item in features):
        ident = re.sub(r"[^a-z0-9]+", "-", area.lower()).strip("-")
        page.body += f'<h2 id="{ident}">{html.escape(area)}</h2>'
        page.body += '<table><thead><tr><th>Capability</th><th>Status</th><th>Scope</th></tr></thead><tbody>'
        for item in (f for f in features if f["area"] == area):
            page.body += (f'<tr><td><a href="{html.escape(item["doc"])}">{html.escape(item["title"])}</a></td>'
                          f'<td>{status_badge(item["status"])}</td><td>{html.escape(item["scope"])}</td></tr>')
        page.body += '</tbody></table>'
        page.headings.append((2, ident, area))
    return page


def build() -> list[tuple[Path, str]]:
    PAGES.clear()
    PAGES["index"] = Page(slug="index", title="Granum documentation",
                          summary="How to get your computer-vision data into shape, and what every screen is for.")
    for section in NAV:
        for slug in section.slugs:
            PAGES[slug] = read_page(slug)
    PAGES["reference/features"] = feature_page()
    PAGES["index"] = front_page()

    written = [(page.out_path, render(page)) for page in PAGES.values()]
    written.append((OUTPUT / "search.json", json.dumps(search_index(), separators=(",", ":"))))
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="only report whether the output is up to date")
    args = parser.parse_args()

    files = build()
    stale = [path for path, text in files if not path.exists() or path.read_text(encoding="utf-8") != text]
    if args.check:
        for path in stale:
            print(f"out of date: {path.relative_to(ROOT)}")
        print("docs are up to date" if not stale else f"{len(stale)} file(s) need rebuilding: python3 tools/docs.py")
        return 1 if stale else 0

    for path, text in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    # Pages that no longer exist in NAV should not stay on the site.
    kept = {path for path, _ in files} | {OUTPUT / "docs.css", OUTPUT / "docs.js"}
    for path in OUTPUT.rglob("*"):
        if path.is_file() and path not in kept:
            path.unlink()
    for path in sorted(OUTPUT.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            shutil.rmtree(path)
    print(f"wrote {len(files)} files to {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
