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
OFFICE_LETTER_SRC = ROOT / "事務所通信"
OFFICE_LETTER_DIST_REL = "assets/pdf/office-letter"

META_RE = re.compile(r"\{#\s*meta:\s*(.+?)#\}", re.S)
OFFICE_LETTER_RE = re.compile(r"^\[(\d{4})年(\d{1,2})月号\]\s*事務所通信(?:\s*(医療|介護))?\.pdf$")


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
    "__FAQ_DATA__":       "faq.json",
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


def _fmt_date_slash(s: str) -> str:
    if not s:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if not m:
        return s
    return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"


def _fmt_file_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f}MB"
    return f"{size / 1024:.0f}KB"


def collect_office_letters() -> list[dict]:
    if not OFFICE_LETTER_SRC.exists():
        return []

    kinds = {
        "": ("general", "通常版", "人事労務の最新トピックを顧問先様向けに読みやすくまとめた通常版です。", 0),
        "医療": ("medical", "医療版", "医療機関向けの労務管理・制度改正トピックをまとめた事務所通信です。", 1),
        "介護": ("care", "介護版", "介護事業所向けの人事労務・運営に関わる情報をまとめた事務所通信です。", 2),
    }
    items: list[dict] = []
    for path in OFFICE_LETTER_SRC.glob("*.pdf"):
        m = OFFICE_LETTER_RE.match(path.name)
        if not m:
            continue
        year = int(m.group(1))
        month = int(m.group(2))
        raw_kind = m.group(3) or ""
        kind, kind_label, description, order = kinds[raw_kind]
        file_name = f"office-letter-{year}-{month:02d}-{kind}.pdf"
        items.append(
            {
                "year": year,
                "month": month,
                "month_key": f"{year}-{month:02d}",
                "month_label": f"{year}年{month}月号",
                "kind": kind,
                "kind_label": kind_label,
                "description": description,
                "order": order,
                "source_path": path,
                "file_name": file_name,
                "href": f"{OFFICE_LETTER_DIST_REL}/{file_name}",
                "size": _fmt_file_size(path.stat().st_size),
            }
        )
    return sorted(items, key=lambda r: (-r["year"], -r["month"], r["order"]))


def copy_office_letter_pdfs(items: list[dict]) -> None:
    if not items:
        return
    target_dir = DIST / OFFICE_LETTER_DIST_REL
    target_dir.mkdir(parents=True, exist_ok=True)
    for item in items:
        shutil.copy2(item["source_path"], target_dir / item["file_name"])
    print(f"[copy] 事務所通信/ -> {target_dir.relative_to(ROOT)}/")


def _notice_date_label(r: dict) -> str:
    return r.get("source_date") or _fmt_date_slash(r.get("date") or "")


def _notice_source_class(source_type: str) -> str:
    return "leaflet" if "リーフレット" in source_type else "news"


def _notice_detail_href(r: dict) -> str:
    notice_id = r.get("id") or "notice"
    return f"notices/{notice_id}/"


def _notice_icon(source_type: str) -> str:
    return "▧" if "リーフレット" in source_type else "▤"


def _notice_search_text(r: dict) -> str:
    return " ".join(
        str(r.get(key) or "")
        for key in ("source_type", "category", "title", "summary", "source_title")
    )


def render_news(html: str) -> str:
    """お知らせカード/タブをビルド時に静的HTMLとして埋め込む(ブラウザ拡張等でJSが
    妨げられてもカードが必ず表示されるようにするため)。"""
    if (
        "__NEWS_CARDS_HTML__" not in html
        and "__NEWS_TABS_HTML__" not in html
        and "__NEWS_COUNT__" not in html
        and "__NEWS_LATEST_DATE__" not in html
    ):
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
                f'<a class="aq-news-link" href="{_esc(r["url"])}" target="_blank" rel="noopener" '
                f'aria-label="{_esc(r.get("title") or "")}の特設ページへ移動">'
                f'<span>特設ページへ移動</span>'
                f'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17 17 7"/><path d="M9 7h8v8"/></svg>'
                f"</a>"
            )
        cards_html += (
            f'<article class="aq-news-card aq-tag-{_esc(r.get("tag_color") or "navy")}" data-cat="{_esc(r.get("category") or "")}">'
            f'<div class="aq-news-card-top">'
            f'<span class="aq-news-icon" aria-hidden="true">{_esc(r.get("icon") or "📌")}</span>'
            f'<div class="aq-news-meta">'
            f'<span class="aq-news-cat">{_esc(r.get("category") or "")}</span>'
            f'<time class="aq-news-date" datetime="{_esc(r.get("date") or "")}">{_esc(_fmt_date_ja(r.get("date") or ""))}</time>'
            f"</div>"
            f"</div>"
            f'<h2 class="aq-news-title">{_esc(r.get("title") or "")}</h2>'
            + (f'<p class="aq-news-lead">{_esc(r["lead"])}</p>' if r.get("lead") else "")
            + (
                f'<details class="aq-news-detail"><summary>本文を確認する</summary>'
                f'<div class="aq-news-body">{r.get("body_html") or ""}</div></details>'
                if r.get("body_html")
                else ""
            )
            + link_html
            + "</article>"
        )

    html = html.replace("__NEWS_TABS_HTML__", tabs_html)
    html = html.replace("__NEWS_CARDS_HTML__", cards_html)
    html = html.replace("__NEWS_COUNT__", str(len(items_sorted)))
    latest_date = _fmt_date_slash(items_sorted[0].get("date") or "") if items_sorted else "-"
    html = html.replace("__NEWS_LATEST_DATE__", latest_date)
    return html


# 表示・取込から除外するお知らせカテゴリ（会社のリーフレット / PSR更新情報）
EXCLUDED_NOTICE_CATEGORIES = {"会社のリーフレット", "psr更新情報"}


def _notice_cat_key(value) -> str:
    return "".join(str(value or "").split()).casefold()


_EXCLUDED_NOTICE_KEYS = {_notice_cat_key(c) for c in EXCLUDED_NOTICE_CATEGORIES}

# 事務所からの内部発信（在宅勤務・臨時休業・営業案内等の自社お知らせ）を判別する文面マーカー。
# PSRの労務ニュースは三人称の記事体だが、自社発信は「平素は格別のご高配を賜り…」等の
# 一人称の挨拶・締め文を含むため、これで判別して表示・取込から除外する。
OFFICE_NOTICE_MARKERS = ("平素は格別", "ご高配を賜り", "誠に勝手ながら")


def _is_office_internal(item: dict) -> bool:
    text = " ".join(
        str(item.get(k) or "")
        for k in ("title", "summary", "body_html", "source_body_html", "source_title")
    )
    return any(marker in text for marker in OFFICE_NOTICE_MARKERS)


def _is_public_notice(item: dict) -> bool:
    if _notice_cat_key(item.get("category")) in _EXCLUDED_NOTICE_KEYS:
        return False
    if _is_office_internal(item):
        return False
    return True


def render_home_notices(html: str) -> str:
    """トップページの最新のお知らせをJSONから生成する。"""
    if "__HOME_NOTICES_HTML__" not in html:
        return html
    data_path = SRC / "data" / "home_notices.json"
    if not data_path.exists():
        return html.replace("__HOME_NOTICES_HTML__", "")

    items = [r for r in json.loads(data_path.read_text(encoding="utf-8")) if _is_public_notice(r)]
    items_sorted = sorted(items, key=lambda r: r.get("date", ""), reverse=True)
    rows_html = ""

    for r in items_sorted[:30]:
        source_type = r.get("source_type") or "ニュース"
        source_class = _notice_source_class(source_type)
        tag_color = r.get("tag_color") or "navy"
        detail_href = _notice_detail_href(r)

        rows_html += (
            f'<a class="aq-home-news-item aq-home-news-{_esc(source_class)}" id="{_esc(r.get("id") or "")}" href="{_esc(detail_href)}">'
            f'<span class="aq-home-news-type">{_esc(source_type)}</span>'
            f'<span class="aq-tag {_esc(tag_color)}">{_esc(r.get("category") or "")}</span>'
            f'<time datetime="{_esc(r.get("date") or "")}">{_esc(_notice_date_label(r))}</time>'
            f'<span class="aq-home-news-title">{_esc(r.get("title") or "")}</span>'
            f'<span class="aq-news-arr">›</span>'
            f"</a>"
        )

    return html.replace("__HOME_NOTICES_HTML__", rows_html)


def render_home_recommendations(html: str) -> str:
    """トップページのおすすめ情報をnews.jsonから生成する。"""
    if "__HOME_RECOMMENDATIONS_HTML__" not in html:
        return html
    data_path = SRC / "data" / "news.json"
    if not data_path.exists():
        return html.replace("__HOME_RECOMMENDATIONS_HTML__", "")

    items = json.loads(data_path.read_text(encoding="utf-8"))
    items_sorted = sorted(items, key=lambda r: r.get("date", ""), reverse=True)
    cards_html = ""

    for r in items_sorted:
        url = r.get("url")
        if not url:
            continue
        tag_color = r.get("tag_color") or "navy"
        category = r.get("category") or "おすすめ"
        title = r.get("title") or ""
        lead = r.get("lead") or ""

        cards_html += (
            f'<a class="aq-recommend-card aq-tag-{_esc(tag_color)}" '
            f'href="{_esc(url)}" target="_blank" rel="noopener" '
            f'aria-label="{_esc(title)}の特設ページへ移動">'
            f'<span class="aq-recommend-meta">'
            f'<span class="aq-recommend-tag {_esc(tag_color)}">{_esc(category)}</span>'
            f'<time datetime="{_esc(r.get("date") or "")}">{_esc(_fmt_date_slash(r.get("date") or ""))}</time>'
            f"</span>"
            f'<span class="aq-recommend-icon" aria-hidden="true">{_esc(r.get("icon") or "↗")}</span>'
            f"<strong>{_esc(title)}</strong>"
            + (f"<p>{_esc(lead)}</p>" if lead else "")
            + '<span class="aq-recommend-link">特設ページへ移動 '
            + '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17 17 7"/><path d="M9 7h8v8"/></svg>'
            + "</span>"
            + "</a>"
        )

    return html.replace("__HOME_RECOMMENDATIONS_HTML__", cards_html)


def render_office_letters(html: str) -> str:
    if "__OFFICE_LETTER_ARCHIVE_HTML__" not in html:
        return html

    items = collect_office_letters()
    if not items:
        empty_html = '<div class="aq-office-empty">現在公開中の事務所通信はありません。</div>'
        return (
            html.replace("__OFFICE_LETTER_ARCHIVE_HTML__", empty_html)
            .replace("__OFFICE_LETTER_COUNT__", "0")
            .replace("__OFFICE_LETTER_MONTH_COUNT__", "0")
            .replace("__OFFICE_LETTER_LATEST__", "-")
        )

    months = []
    for item in items:
        if item["month_key"] not in months:
            months.append(item["month_key"])

    archive_html = ""
    for month_key in months:
        month_items = [item for item in items if item["month_key"] == month_key]
        month_label = month_items[0]["month_label"]
        cards_html = ""
        for item in month_items:
            title = f'{item["month_label"]} 事務所通信 {item["kind_label"]}'
            cards_html += (
                f'<article class="aq-office-card aq-office-{_esc(item["kind"])}" data-kind="{_esc(item["kind"])}">'
                f'<div class="aq-office-card-top">'
                f'<span class="aq-office-kind">{_esc(item["kind_label"])}</span>'
                f'<span class="aq-office-size">{_esc(item["size"])}</span>'
                f"</div>"
                f"<h3>{_esc(title)}</h3>"
                f"<p>{_esc(item['description'])}</p>"
                f'<div class="aq-office-actions">'
                f'<a class="aq-office-btn primary" href="{_esc(item["href"])}" target="_blank" rel="noopener">'
                f'PDFを開く <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17 17 7"/><path d="M9 7h8v8"/></svg></a>'
                f'<a class="aq-office-btn secondary" href="{_esc(item["href"])}" download>'
                f'ダウンロード <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg></a>'
                f"</div>"
                f"</article>"
            )

        archive_html += (
            f'<section class="aq-office-month">'
            f'<div class="aq-office-month-head">'
            f"<h2>{_esc(month_label)}</h2>"
            f"<span>{len(month_items)}件</span>"
            f"</div>"
            f'<div class="aq-office-cards">{cards_html}</div>'
            f"</section>"
        )

    latest = items[0]["month_label"]
    return (
        html.replace("__OFFICE_LETTER_ARCHIVE_HTML__", archive_html)
        .replace("__OFFICE_LETTER_COUNT__", str(len(items)))
        .replace("__OFFICE_LETTER_MONTH_COUNT__", str(len(months)))
        .replace("__OFFICE_LETTER_LATEST__", latest)
    )


def render_notice_archive(html: str) -> str:
    """MyKomon/PSR由来のお知らせ一覧ページをJSONから生成する。"""
    if (
        "__NOTICE_LIST_HTML__" not in html
        and "__NOTICE_COUNT__" not in html
        and "__NOTICE_CATEGORY_OPTIONS__" not in html
    ):
        return html
    data_path = SRC / "data" / "home_notices.json"
    if not data_path.exists():
        return (
            html.replace("__NOTICE_LIST_HTML__", "")
            .replace("__NOTICE_COUNT__", "0")
            .replace("__NOTICE_CATEGORY_OPTIONS__", "")
        )

    items = [r for r in json.loads(data_path.read_text(encoding="utf-8")) if _is_public_notice(r)]
    items_sorted = sorted(items, key=lambda r: r.get("date", ""), reverse=True)
    list_html = ""
    categories: list[str] = []

    for r in items_sorted:
        source_type = r.get("source_type") or "ニュース"
        source_class = _notice_source_class(source_type)
        detail_href = _notice_detail_href(r)
        category = r.get("category") or ""
        if category and category not in categories:
            categories.append(category)

        list_html += (
            f'<a class="aq-notice-card aq-notice-is-{_esc(source_class)}" id="{_esc(r.get("id") or "")}" '
            f'href="{_esc(detail_href)}" data-notice-card data-type="{_esc(source_type)}" '
            f'data-category="{_esc(category)}" data-search="{_esc(_notice_search_text(r))}">'
            f'<span class="aq-notice-card-icon" aria-hidden="true">{_esc(_notice_icon(source_type))}</span>'
            f'<span class="aq-notice-card-main">'
            f'<span class="aq-notice-card-tags">'
            f'<span class="aq-notice-type">{_esc(source_type)}</span>'
            f'<span class="aq-notice-cat">{_esc(category)}</span>'
            f'<time datetime="{_esc(r.get("date") or "")}">{_esc(_notice_date_label(r))}</time>'
            f"</span>"
            f'<strong class="aq-notice-title">{_esc(r.get("title") or "")}</strong>'
            + (f'<span class="aq-notice-lead">{_esc(r.get("summary"))}</span>' if r.get("summary") else "")
            + f"</span>"
            f'<span class="aq-notice-arr">›</span>'
            f"</a>"
        )

    category_options = ""
    for category in categories:
        category_options += f'<option value="{_esc(category)}">{_esc(category)}</option>'

    html = html.replace("__NOTICE_LIST_HTML__", list_html)
    html = html.replace("__NOTICE_COUNT__", str(len(items_sorted)))
    html = html.replace("__NOTICE_CATEGORY_OPTIONS__", category_options)
    return html


def _notice_detail_extra_paragraphs(r: dict) -> str:
    source_type = r.get("source_type") or "ニュース"
    category = r.get("category") or "実務"
    if "リーフレット" in source_type:
        return (
            f"<p>この案内は、{category}に関する制度説明や社内周知、担当者間の共有に使いやすい情報です。"
            "該当する従業員や手続きがある場合は、内容を確認したうえで、社内で案内が必要かどうかを検討してください。</p>"
            "<p>パンフレット・リーフレット類は、制度の概要や注意点を短く整理していることが多いため、"
            "実際の対応では対象者、提出期限、必要書類、社内への周知方法をあわせて確認しておくと安心です。</p>"
        )
    return (
        f"<p>このニュースは、{category}に関する制度改正、行政発表、実務上の注意点につながる可能性がある情報です。"
        "自社の労務管理、給与計算、社会保険手続き、社内規程に影響がないかを確認してください。</p>"
        "<p>すぐに対応が必要な内容でなくても、今後の手続き準備や社内説明に関係する場合があります。"
        "担当部署で共有し、必要に応じてスケジュールや運用ルールの見直しを進めてください。</p>"
    )


def _notice_detail_points(r: dict) -> list[tuple[str, str]]:
    category = r.get("category") or "実務"
    if "リーフレット" in (r.get("source_type") or ""):
        return [
            ("対象者・対象業務", f"{category}に関係する従業員、部署、手続きが自社にあるか確認します。"),
            ("社内周知", "従業員や管理者へ案内すべき内容がある場合は、共有方法とタイミングを決めます。"),
            ("必要書類・期限", "申請、届出、説明資料などが必要な場合に備え、期限と準備物を確認します。"),
        ]
    return [
        ("自社への影響", f"{category}に関する変更や公表内容が、自社の手続き・規程・給与計算に関係するか確認します。"),
        ("対応時期", "すぐ対応する内容か、今後の準備として把握しておく内容かを切り分けます。"),
        ("担当者への共有", "必要に応じて経営者、人事労務担当者、給与担当者へ共有し、対応方針を整理します。"),
    ]


def render_notice_detail_content(r: dict) -> str:
    source_type = r.get("source_type") or "ニュース"
    source_class = _notice_source_class(source_type)
    has_source_body = bool(r.get("source_body_html"))
    body_html = r.get("source_body_html") or r.get("body_html") or ""
    if not body_html and r.get("summary"):
        body_html = f"<p>{_esc(r.get('summary'))}</p>"
    if not has_source_body:
        body_html += _notice_detail_extra_paragraphs(r)
    points_html = "".join(
        f'<div class="aq-nd-point"><strong>{_esc(title)}</strong><p>{_esc(text)}</p></div>'
        for title, text in _notice_detail_points(r)
    )
    points_section = ""
    if not has_source_body:
        points_section = (
            f'<section class="aq-nd-points">'
            f'<div class="aq-nd-eyebrow">CHECK POINTS</div>'
            f'<h2>実務で確認するポイント</h2>'
            f'<div class="aq-nd-point-grid">{points_html}</div>'
            f"</section>"
        )
    lead_html = ""
    if r.get("summary") and not has_source_body:
        lead_html = f'<p class="aq-nd-lead">{_esc(r.get("summary"))}</p>'

    return (
        f'<div id="aq-notice-detail-wrap" class="aq-subpage-wrap aq-nd-wrap aq-nd-is-{_esc(source_class)}">'
        f'<main class="aq-nd-main">'
        f'<section class="aq-nd-hero">'
        f'<a class="aq-nd-back" href="notices/">ニュース一覧へ戻る</a>'
        f'<div class="aq-nd-meta">'
        f'<span class="aq-nd-type">{_esc(source_type)}</span>'
        f'<span class="aq-nd-cat">{_esc(r.get("category") or "")}</span>'
        f'<time datetime="{_esc(r.get("date") or "")}">{_esc(_notice_date_label(r))}</time>'
        f"</div>"
        f'<h1>{_esc(r.get("title") or "")}</h1>'
        + lead_html
        + f"</section>"
        f'<section class="aq-nd-section">'
        f'<div class="aq-nd-eyebrow">DETAIL</div>'
        f'<h2>確認しておきたい内容</h2>'
        f'<article class="aq-nd-article">{body_html}</article>'
        f"</section>"
        + points_section
        + f'<section class="aq-nd-cta">'
        f'<div>'
        f'<div class="aq-nd-eyebrow">CONSULTATION</div>'
        f'<h2>自社への影響が気になる場合</h2>'
        f'<p>対応が必要かどうか、判断に迷う場合はアクエルド担当者へご相談ください。</p>'
        f"</div>"
        f'<a href="contact/">相談する</a>'
        f"</section>"
        f"</main></div>"
    )


def render_notice_detail_pages(base_tpl, build_version: str, base_href: str) -> int:
    data_path = SRC / "data" / "home_notices.json"
    if not data_path.exists():
        return 0
    items = json.loads(data_path.read_text(encoding="utf-8"))
    count = 0
    for r in items:
        notice_id = r.get("id")
        if not notice_id:
            continue
        content = render_notice_detail_content(r)
        rendered = base_tpl.render(
            title=r.get("title") or "ニュース詳細",
            description=r.get("summary") or "",
            body_class="aq-is-notice-detail data-page-notices",
            content=content,
            base_href=base_href,
            build_version=build_version,
        )
        rendered = rendered.replace(
            '<body class="aq-is-notice-detail data-page-notices"',
            '<body class="aq-is-notice-detail" data-page="notices"',
        )
        out_path = DIST / "notices" / notice_id / "index.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
        print(f"[render] notices\\{notice_id}\\index.html -> {out_path.relative_to(ROOT)}")
        count += 1
    return count


def main(base_href: str = "/") -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    # assets コピー
    shutil.copytree(ASSETS, DIST / "assets")
    print(f"[copy] assets/ -> dist/assets/")
    office_letter_items = collect_office_letters()
    copy_office_letter_pdfs(office_letter_items)

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
        content = render_notice_archive(content)
        content = render_home_notices(content)
        content = render_home_recommendations(content)
        content = render_news(content)
        content = render_office_letters(content)
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

    count += render_notice_detail_pages(base_tpl, build_version, base_href)

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
