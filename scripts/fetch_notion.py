"""Notion APIから各ページ・DBの内容を取得し、src/pages/ 配下にHTMLとして書き出す。

【Phase 3 で実装予定】現状はスタブで、対象ページのリストとプレースホルダの生成のみ。

実行:
    python scripts/fetch_notion.py
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")

# (slug, title, notion_page_or_db_id, kind)
TARGETS = [
    ("joseikin",   "助成金ページ",            "3697a82f-ba9a-8137-9f2a-eb28d3244e35", "page"),
    ("faq",        "よくある質問",            None, "page"),
    ("forms",      "お役立ち書式",            None, "page"),
    ("calendar",   "労務年間カレンダー",      None, "page"),
    ("lawrev",     "法改正カレンダー",        "3587a82f-ba9a-814f-9e63-d3c749a71779", "database"),
    ("jimukumiai", "事務組合カレンダー",      "3587a82f-ba9a-814e-81ea-c211d978f839", "database"),
    ("subsidies",  "補助金カレンダー",        "3587a82f-ba9a-81e4-aebc-ed272b08f783", "database"),
    ("news",       "最新情報・コラム",        None, "page"),
    ("contact",    "お問い合わせ",            None, "page"),
]


PLACEHOLDER_TPL = """{{# meta:
title: {title}
body_class: aq-is-page
data_page: {slug}
#}}

<main class="aq-portal-body aq-notion-body">
  <section class="aq-panel">
    <h1>{title}</h1>
    <p>このページは準備中です。Notion API 連携完了後、自動で内容が取り込まれます。</p>
    <p style="color: var(--aq-text-sub); font-size: 13px;">Notion ID: <code>{notion_id}</code> / 種別: {kind}</p>
  </section>
</main>
"""


def main() -> int:
    pages_dir = ROOT / "src" / "pages"
    for slug, title, notion_id, kind in TARGETS:
        out_dir = pages_dir / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "index.html"
        if out_file.exists():
            print(f"[skip] {slug}: 既存ファイルあり")
            continue
        out_file.write_text(
            PLACEHOLDER_TPL.format(
                slug=slug,
                title=title,
                notion_id=notion_id or "(未設定)",
                kind=kind,
            ),
            encoding="utf-8",
        )
        print(f"[stub] {slug}: 作成")

    if not NOTION_TOKEN:
        print("\n[info] NOTION_TOKEN 未設定。Phase 3 で実装する Notion API 取込はスキップ。")
    else:
        print("\n[info] NOTION_TOKEN 検出。Phase 3 実装後、ここから API 取込が走ります。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
