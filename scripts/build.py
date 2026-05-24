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


def main(base_href: str = "/") -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    # assets コピー
    shutil.copytree(ASSETS, DIST / "assets")
    print(f"[copy] assets/ -> dist/assets/")

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
        content = inject_data(content)

        # Jinja の構文（{{ ... }}）がpages内に無いことを前提に、content はそのまま安全に渡す
        rendered = base_tpl.render(
            title=meta.get("title", "顧問先ポータル"),
            description=meta.get("description", ""),
            body_class=meta.get("body_class", "aq-is-page") + " " + ("data-page-" + meta.get("data_page", "")),
            content=content,
            base_href=base_href,
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
