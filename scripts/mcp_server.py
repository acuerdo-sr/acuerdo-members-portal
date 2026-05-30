"""MCP server for the ACUERDO members portal.

Run with:
    python scripts/mcp_server.py

The server uses STDIO, so do not write logs to stdout from this module.
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PAGES = SRC / "pages"
DATA = SRC / "data"
DIST = ROOT / "dist"

mcp = FastMCP("acuerdo-members-portal")

DATA_FILES = {
    "calendar": "calendar.json",
    "forms": "forms.json",
    "jimukumiai": "jimukumiai.json",
    "joseikin": "joseikin.json",
    "lawrev": "lawrev.json",
    "news": "news.json",
    "subsidies": "subsidies.json",
}

TEXT_SUFFIXES = {".html", ".json", ".md", ".txt", ".css", ".js"}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_json(name: str) -> Any:
    filename = DATA_FILES.get(name, name)
    if not filename.endswith(".json"):
        filename = f"{filename}.json"
    path = DATA / filename
    if not path.exists() or path.name not in DATA_FILES.values():
        raise ToolError(f"Unknown data file: {name}")
    return json.loads(_read_text(path))


def _page_path(slug: str) -> Path:
    normalized = slug.strip().strip("/")
    if normalized in {"", "home", "index"}:
        return PAGES / "index.html"

    candidate = (PAGES / normalized / "index.html").resolve()
    pages_root = PAGES.resolve()
    if not candidate.is_relative_to(pages_root):
        raise ToolError(f"Invalid page slug: {slug}")
    if not candidate.exists():
        raise ToolError(f"Unknown page slug: {slug}")
    return candidate


def _strip_markup(value: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _compact_json(value: Any, max_chars: int = 20000) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... truncated ..."


def _safe_snippet(text: str, query: str, window: int = 90) -> str:
    normalized = _strip_markup(text)
    if not query:
        return normalized[: window * 2]
    lower = normalized.lower()
    pos = lower.find(query.lower())
    if pos < 0:
        return normalized[: window * 2]
    start = max(0, pos - window)
    end = min(len(normalized), pos + len(query) + window)
    prefix = "..." if start else ""
    suffix = "..." if end < len(normalized) else ""
    return prefix + normalized[start:end] + suffix


def _run_project_command(args: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-12000:],
        "stderr": completed.stderr[-12000:],
    }


def _iter_pages() -> list[dict[str, str]]:
    pages: list[dict[str, str]] = []
    for path in sorted(PAGES.rglob("index.html")):
        rel_dir = path.parent.relative_to(PAGES)
        slug = "" if str(rel_dir) == "." else rel_dir.as_posix()
        text = _read_text(path)
        title_match = re.search(r"title:\s*(.+)", text)
        pages.append(
            {
                "slug": slug or "home",
                "path": path.relative_to(ROOT).as_posix(),
                "title": title_match.group(1).strip() if title_match else slug or "home",
            }
        )
    return pages


def _iter_forms() -> list[dict[str, Any]]:
    data = _load_json("forms")
    rows: list[dict[str, Any]] = []
    for category_key, category in data.get("categories", {}).items():
        category_label = category.get("label", category_key)
        for item in category.get("items", []):
            rows.append(
                {
                    "category": category_key,
                    "category_label": category_label,
                    "subcategory": None,
                    "subcategory_label": None,
                    **item,
                }
            )
        for sub_key, subcategory in category.get("subcategories", {}).items():
            sub_label = subcategory.get("label", sub_key)
            for item in subcategory.get("items", []):
                rows.append(
                    {
                        "category": category_key,
                        "category_label": category_label,
                        "subcategory": sub_key,
                        "subcategory_label": sub_label,
                        **item,
                    }
                )
    return rows


def _matches_query(row: dict[str, Any], query: str) -> bool:
    haystack = json.dumps(row, ensure_ascii=False).lower()
    return query.lower() in haystack


@mcp.resource("portal://summary", mime_type="application/json")
def portal_summary() -> str:
    """Return a compact project summary."""
    return _compact_json(
        {
            "name": "ACUERDO members portal",
            "root": str(ROOT),
            "pages": _iter_pages(),
            "data_files": list(DATA_FILES.values()),
            "dist_exists": DIST.exists(),
        }
    )


@mcp.resource("portal://data/{name}", mime_type="application/json")
def portal_data(name: str) -> str:
    """Read a JSON data file from src/data."""
    return _compact_json(_load_json(name))


@mcp.resource("portal://page/{slug}", mime_type="text/html")
def portal_page(slug: str) -> str:
    """Read a source page from src/pages."""
    return _read_text(_page_path(slug))


@mcp.tool()
def list_pages() -> list[dict[str, str]]:
    """List source pages that can be read with read_page or portal://page/{slug}."""
    return _iter_pages()


@mcp.tool()
def list_data_files() -> list[dict[str, str]]:
    """List JSON data files that can be read with read_data or portal://data/{name}."""
    return [
        {"name": name, "path": f"src/data/{filename}"}
        for name, filename in DATA_FILES.items()
    ]


@mcp.tool()
def read_page(slug: str) -> str:
    """Read a source page HTML by slug, for example 'forms' or 'home'."""
    return _read_text(_page_path(slug))


@mcp.tool()
def read_data(name: str) -> Any:
    """Read a JSON data file by logical name, for example 'forms' or 'joseikin'."""
    return _load_json(name)


@mcp.tool()
def list_forms(category: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """List downloadable form templates, optionally filtered by category key or label."""
    rows = _iter_forms()
    if category:
        key = category.lower()
        rows = [
            row
            for row in rows
            if key in str(row.get("category", "")).lower()
            or key in str(row.get("category_label", "")).lower()
            or key in str(row.get("subcategory", "")).lower()
            or key in str(row.get("subcategory_label", "")).lower()
        ]
    return rows[: max(1, min(limit, 300))]


@mcp.tool()
def search_forms(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search downloadable forms by name, purpose, category, or description."""
    if not query.strip():
        raise ToolError("query is required")
    rows = [row for row in _iter_forms() if _matches_query(row, query)]
    return rows[: max(1, min(limit, 50))]


@mcp.tool()
def search_subsidies(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search the joseikin quick-reference subsidy data."""
    if not query.strip():
        raise ToolError("query is required")
    rows = []
    for item in _load_json("joseikin"):
        searchable = {
            "id": item.get("i"),
            "category": item.get("cat_label"),
            "what": item.get("w"),
            "name": item.get("n"),
            "amount": item.get("m"),
            "detail": _strip_markup(item.get("detail_html", "")),
        }
        if _matches_query(searchable, query):
            rows.append(searchable)
    return rows[: max(1, min(limit, 50))]


@mcp.tool()
def search_portal(query: str, dataset: str = "all", limit: int = 10) -> list[dict[str, Any]]:
    """Search pages and JSON data for a keyword."""
    if not query.strip():
        raise ToolError("query is required")

    dataset = dataset.lower()
    allowed = {"all", "pages", "data"}
    if dataset not in allowed:
        raise ToolError(f"dataset must be one of: {', '.join(sorted(allowed))}")

    results: list[dict[str, Any]] = []
    if dataset in {"all", "pages"}:
        for page in _iter_pages():
            text = _read_text(ROOT / page["path"])
            if query.lower() in _strip_markup(text).lower():
                results.append(
                    {
                        "type": "page",
                        "name": page["slug"],
                        "path": page["path"],
                        "title": page["title"],
                        "snippet": _safe_snippet(text, query),
                    }
                )

    if dataset in {"all", "data"}:
        for name, filename in DATA_FILES.items():
            text = _compact_json(_load_json(name), max_chars=200000)
            if query.lower() in _strip_markup(text).lower():
                results.append(
                    {
                        "type": "data",
                        "name": name,
                        "path": f"src/data/{filename}",
                        "snippet": _safe_snippet(text, query),
                    }
                )

    return results[: max(1, min(limit, 50))]


@mcp.tool()
def build_site(base_href: str = "/") -> dict[str, Any]:
    """Build the static site into dist/ by running scripts/build.py."""
    if not base_href:
        base_href = "/"
    return _run_project_command(["scripts/build.py", "--base-href", base_href])


@mcp.tool()
def fetch_notion_placeholders() -> dict[str, Any]:
    """Run the current Notion fetch script, which creates missing placeholder pages."""
    return _run_project_command(["scripts/fetch_notion.py"])


if __name__ == "__main__":
    mcp.run(transport="stdio")
