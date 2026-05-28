"""ACUERDO 顧問先ポータル ビルドスクリプト

src/pages/ 以下の各HTMLを Jinja2 でレイアウト適用しつつ dist/ に書き出す。
assets/ はそのまま dist/assets/ にコピー。

各ページの先頭に Jinja コメントとして meta を書く:

    {# meta:
    title: 助成金早見表
    body_class: aq-is-josei
    data_page: joseikin-list
    #}

実行:
    python scripts/build.py [--base-href /]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
ASSETS = ROOT / "assets"
DIST = ROOT / "dist"

META_RE = re.compile(r"\{#\s*meta:\s*(.+?)#\}", re.S)


def parse_meta(text: str) -> tuple[dict[str, str], str]:
    """先頭の {# meta: ... #} を抜き出して {key: value} 化。残りを返す。"""
    m = META_RE.match(text.lstrip())
    meta: dict[str, str] = {}
    if not m:
        return meta, text
    block = m.group(1)
    for line in block.strip().splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()
    # 元テキストから meta コメントを除去
    body = text[m.end():] if text.lstrip().startswith("{#") else text
    return meta, body.lstrip()


DATA_PLACEHOLDERS = {
    "__JOSEI_DATA__":     "joseikin.json",
    "__FORMS_DATA__":     "forms.json",
    "__LAWREV_DATA__":    "lawrev.json",
    "__SUBSIDIES_DATA__": "subsidies.json",
    "__JIMUKUMIAI_DATA__":"jimukumiai.json",
    "__CALENDAR_DATA__":  "calendar.json",
    "__NEWS_DATA__":      "news.json",
}


def inject_data(html: str) -> str:
    """各種 __XXX_DATA__ プレースホルダを対応するJSONで差し替える。"""
    for placeholder, filename in DATA_PLACEHOLDERS.items():
        if placeholder not in html:
            continue
        data_path = SRC / "data" / filename
        if not data_path.exists():
            continue
        data = data_path.read_text(encoding="utf-8").strip()
        html = html.replace(placeholder, data)
    return html


def _esc(s) -> str:
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _fmt_date_ja(s: str) -> str:
    if not s:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if not m:
        return s
    return f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日"


def render_news(html: str) -> str:
    """お知らせカード/タブをビルド時に静的HTMLとして埋め込む(ブラウザ拡張等でJSが
    妨げられてもカードが必ず表示されるようにするため)。"""
    if "__NEWS_CARDS_HTML__" not in html and "__NEWS_TABS_HTML__" not in html:
        return html
    data_path = SRC / "data" / "news.json"
    if not data_path.exists():
        return html
    items = json.loads(data_path.read_text(encoding="utf-8"))
    items_sorted = sorted(items, key=lambda r: r.get("date", ""), reverse=True)

    # タブ(カテゴリ)
    cats: list[str] = []
    for r in items_sorted:
        c = r.get("category")
        if c and c not in cats:
            cats.append(c)
    tabs_html = '<button class="is-active" data-cat="all" type="button">すべて</button>'
    for c in cats:
        tabs_html += f'<button data-cat="{_esc(c)}" type="button">{_esc(c)}</button>'

    # カード
    cards_html = ""
    for r in items_sorted:
        link_html = ""
        if r.get("url"):
            link_html = (
                f'<a class="aq-news-link" href="{_esc(r["url"])}" target="_blank" rel="noopener">'
                f'{_esc(r.get("url_label") or "ページを開く")} ›</a>'
            )
        cards_html += (
            f'<article class="aq-news-card aq-tag-{_esc(r.get("tag_color") or "navy")}" data-cat="{_esc(r.get("category") or "")}">'
            f'<header class="aq-news-card-head">'
            f'<span class="aq-news-icon">{_esc(r.get("icon") or "📌")}</span>'
            f'<div class="aq-news-meta">'
            f'<time class="aq-news-date">{_esc(_fmt_date_ja(r.get("date") or ""))}</time>'
            f'<span class="aq-news-cat">{_esc(r.get("category") or "")}</span>'
            f"</div>"
            f"</header>"
            f'<h2 class="aq-news-title">{_esc(r.get("title") or "")}</h2>'
            + (f'<p class="aq-news-lead">{_esc(r["lead"])}</p>' if r.get("lead") else "")
            + f'<div class="aq-news-body">{r.get("body_html") or ""}</div>'
            + link_html
            + "</article>"
        )

    html = html.replace("__NEWS_TABS_HTML__", tabs_html)
    html = html.replace("__NEWS_CARDS_HTML__", cards_html)
    return html


def main(base_href: str = "/") -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    # assets コピー
    shutil.copytree(ASSETS, DIST / "assets")
    print(f"[copy] assets/ -> dist/assets/")

    # キャッシュバスター: site.css の mtime + 短いハッシュをビルドバージョンとして使う
    import hashlib
    css_path = ASSETS / "css" / "site.css"
    js_path = ASSETS / "js" / "site.js"
    parts: list[str] = []
    for p in (css_path, js_path):
        if p.exists():
            parts.append(hashlib.md5(p.read_bytes()).hexdigest()[:8])
    build_version = "".join(parts) or "1"

    env = Environment(
        loader=FileSystemLoader(str(SRC)),
        autoescape=False,  # ページ本文は信頼ソース。Jinja で {{ content|safe }} 経由
        keep_trailing_newline=True,
    )

    base_tpl = env.get_template("_layout/base.html")
    pages_root = SRC / "pages"
    count = 0

    for path in sorted(pages_root.rglob("*.html")):
        rel = path.relative_to(pages_root)
        raw = path.read_text(encoding="utf-8")
        meta, content = parse_meta(raw)
        content = render_news(content)
        content = inject_data(content)

        # Jinja の構文（{{ ... }}）がpages内に無いことを前提に、content はそのまま安全に渡す
        rendered = base_tpl.render(
            title=meta.get("title", "顧問先ポータル"),
            description=meta.get("description", ""),
            body_class=meta.get("body_class", "aq-is-page") + " " + ("data-page-" + meta.get("data_page", "")),
            content=content,
            base_href=base_href,
            build_version=build_version,
        )
        # data-page 属性を body にもセット（site.js が active hover に使う）
        data_page = meta.get("data_page", "")
        if data_page:
            rendered = rendered.replace(
                f'<body class="{meta.get("body_class","aq-is-page")} data-page-{data_page}"',
                f'<body class="{meta.get("body_class","aq-is-page")}" data-page="{data_page}"',
            )

        out_path = DIST / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
        print(f"[render] {rel} -> {out_path.relative_to(ROOT)}")
        count += 1

    # CNAME（カスタムドメイン用、空ファイルでも作っておく）
    cname = ROOT / "CNAME"
    if cname.exists():
        shutil.copy(cname, DIST / "CNAME")

    # .nojekyll（GitHub Pages のJekyll処理を無効化、_layout 等の _ 始まりも公開可能に）
    (DIST / ".nojekyll").write_text("", encoding="utf-8")

    print(f"\n[done] {count} pages built -> {DIST}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-href", default="/", help="HTML <base href>（GitHub Pages のサブパス用）")
    args = ap.parse_args()
    sys.exit(main(args.base_href))
