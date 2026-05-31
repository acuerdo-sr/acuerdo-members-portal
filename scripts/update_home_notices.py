"""MyKomon/PSRからトップページ用のお知らせJSONを更新する。

使い方:
    python scripts/update_home_notices.py

.env に MYKOMON_ID / MYKOMON_PASSWORD がある場合はMyKomonへログインして
PSRページのURLを探す。見つからない場合は PSR_TOPICS_URL を取得元にする。
既存JSONに同じURLのお知らせがある場合、トップ表示用の言い換え文は保持する。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "src" / "data" / "home_notices.json"
MYKOMON_HOME_URL = "https://www.mykomon.com/app/homeSr"
MYKOMON_LOGIN_URL = "https://www.mykomon.com/MyKomon/login.do"
DEFAULT_PSR_URL = "https://www.psrn.jp/?transactionid=2e633e95368f07dd5080458f9cd82fd3e24bd47e"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
)

TAG_COLORS = ["navy", "sky", "gold", "violet", "wine", "gray"]


def strip_tags(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def load_existing() -> dict[str, dict]:
    if not DATA_PATH.exists():
        return {}
    try:
        items = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {item.get("url") or item.get("source_title") or item.get("id"): item for item in items}


def extract_hidden_inputs(html: str) -> dict[str, str]:
    form_match = re.search(r"<form[\s\S]*?</form>", html, flags=re.I)
    form_html = form_match.group(0) if form_match else html
    payload: dict[str, str] = {}
    for input_html in re.findall(r"<input[^>]+>", form_html, flags=re.I):
        name_match = re.search(r'name=["\']?([^"\' >]+)', input_html, flags=re.I)
        if not name_match:
            continue
        value_match = re.search(r'value=["\']([^"\']*)', input_html, flags=re.I)
        payload[name_match.group(1)] = value_match.group(1) if value_match else ""
    return payload


def login_mykomon(client: httpx.Client) -> str | None:
    login_id = os.getenv("MYKOMON_ID") or os.getenv("MYKOMON_LOGINNAME")
    password = os.getenv("MYKOMON_PASSWORD") or os.getenv("MYKOMON_PASS")
    if not login_id or not password:
        return None

    login_page = client.get(MYKOMON_HOME_URL)
    payload = extract_hidden_inputs(login_page.text)
    payload.update(
        {
            "loginname": login_id,
            "pass": password,
            "action": "login",
            "browserFlag": "1",
            "screenWidth": "1366",
            "screenHeight": "768",
            "userAgent": USER_AGENT,
            "platform": "Win32",
            "language": "ja-JP",
            "onLine": "true",
        }
    )
    client.post(MYKOMON_LOGIN_URL, data=payload)
    home = client.get(MYKOMON_HOME_URL)
    if "MyKomon ログイン" in home.text:
        raise RuntimeError("MyKomonへのログインに失敗しました。ID/PASSを確認してください。")

    psr_match = re.search(r'https?://www\.psrn\.jp/[^"\']+', home.text)
    if psr_match:
        return unescape(psr_match.group(0))
    return None


def make_id(href: str, title: str) -> str:
    m = re.search(r"(?:id|transactionid)=([A-Za-z0-9_-]+)", href)
    if m:
        return f"psr-{m.group(1).lower()}"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", href or title).strip("-").lower()
    return f"psr-{slug[:48] or 'notice'}"


def compact_category(category: str, title: str, source_type: str) -> str:
    category = category.strip()
    if "会社のリーフレット" in title:
        return "会社のリーフレット"
    if re.search(r"所得税|法人税|税制|税額控除", title):
        return "税制"
    if re.search(r"有効求人倍率|完全失業率|外国人雇用|雇用啓発", title):
        return "雇用"
    if re.search(r"女性の健康|フェムテック|健康課題", title):
        return "健康経営"
    if re.search(r"労働市場|人材戦略|人材育成", title):
        return "労働市場"
    if re.search(r"雇調金|雇用調整助成金", title):
        return "雇調金"
    if re.search(r"熱中症|安全衛生|死傷者", title):
        return "安全衛生"
    if re.search(r"年金|戸籍|振り仮名|社会保険", title):
        return "社会保険"
    if re.search(r"春闘|賃上げ|賃金", title):
        return "賃上げ"
    if category == "行政資料・リーフレット":
        return "行政資料"
    if category == "改正・審議・パブコメ":
        return "法改正"
    if not category:
        return "リーフレット" if source_type == "リーフレット" else "ニュース"
    return category[:14]


def classify_source(main_category: str, sub_category: str, title: str, href: str) -> str:
    haystack = f"{main_category} {sub_category} {title} {href}"
    if "リーフレット" in haystack or "/dl/leaflet" in href:
        return "リーフレット"
    return "ニュース"


def soften_title(title: str, source_type: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    if "法人税関係法令" in title:
        return "法人税関係法令の改正概要が公表されました"
    if "給付付き税額控除" in title:
        return "給付付き税額控除の検討状況が示されました"
    if "春闘" in title and "賃上げ" in title:
        return "春闘の賃上げ集計が公表されました"
    if "戸籍" in title and "年金" in title:
        return "氏名の振り仮名に関する年金手続きの案内です"
    replacements = [
        (r"を公表（(.+?)）$", "が公表されました"),
        (r"を公表$", "が公表されました"),
        (r"アップしました！?$", "を掲載しました"),
        (r"について$", "を確認できます"),
    ]
    for pattern, repl in replacements:
        new_title = re.sub(pattern, repl, title)
        if new_title != title:
            return new_title
    if source_type == "リーフレット" and "リーフレット" not in title:
        return f"{title}の資料が出ています"
    return title


def default_summary(source_type: str, category: str, title: str) -> str:
    if source_type == "リーフレット":
        return (
            f"{category}に関する資料・案内が公開されています。"
            "社内周知や実務対応の確認にご活用ください。"
        )
    return (
        f"{category}に関する新しい情報です。"
        "自社の手続きや労務管理に関係しそうな項目を確認しておきましょう。"
    )


def default_body(source_type: str, category: str) -> str:
    if source_type == "リーフレット":
        return (
            f"<p>{category}に関するリーフレットや行政資料の案内です。</p>"
            "<p>従業員への説明、社内周知、実務対応の確認に必要な範囲でご活用ください。</p>"
        )
    return (
        f"<p>{category}に関する新しい情報が公表されています。</p>"
        "<p>対応が必要かどうか、まずは概要をご確認ください。判断に迷う場合は担当者へご相談ください。</p>"
    )


def parse_psr_entries(html: str, base_url: str) -> list[dict]:
    entries: list[dict] = []
    blocks = re.findall(r"<li>\s*<p class=\"entry_head\">([\s\S]*?)</li>", html)
    for block in blocks:
        link = re.search(r'<a\s+href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', block, flags=re.I)
        if not link:
            continue
        href = urljoin(base_url, unescape(link.group(1)))
        title = strip_tags(link.group(2))
        head = strip_tags(block)
        date_match = re.search(r"(\d{4})/(\d{2})/(\d{2})", head)
        if not date_match:
            continue
        date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
        before_title = head.split(title, 1)[0]
        parts = before_title.split()
        main_category = parts[2] if len(parts) >= 3 else ""
        sub_category = " ".join(parts[3:]).strip()
        source_type = classify_source(main_category, sub_category, title, href)
        if main_category not in {"トピックス", "PSR更新情報"} and source_type != "リーフレット":
            continue
        category = compact_category(sub_category or main_category, title, source_type)
        entries.append(
            {
                "id": make_id(href, title),
                "date": date,
                "source_type": source_type,
                "category": category,
                "source_title": title,
                "title": soften_title(title, source_type),
                "summary": default_summary(source_type, category, title),
                "body_html": default_body(source_type, category),
                "url": href,
                "url_label": "リーフレットを見る" if source_type == "リーフレット" else "元記事を見る",
            }
        )
    return entries


def merge_existing(generated: list[dict], existing: dict[str, dict]) -> list[dict]:
    merged: list[dict] = []
    for idx, item in enumerate(generated):
        previous = existing.get(item.get("url")) or existing.get(item.get("source_title")) or existing.get(item.get("id"))
        if previous:
            for key in ("id", "title", "summary", "body_html", "url_label", "tag_color"):
                if previous.get(key):
                    if key == "title" and previous.get("title") == previous.get("source_title"):
                        continue
                    item[key] = previous[key]
        item.setdefault("tag_color", TAG_COLORS[idx % len(TAG_COLORS)])
        merged.append(item)
    return merged


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=int(os.getenv("HOME_NOTICES_LIMIT", "10")))
    args = parser.parse_args()

    source_url = os.getenv("PSR_TOPICS_URL") or DEFAULT_PSR_URL
    existing = load_existing()

    with httpx.Client(follow_redirects=True, timeout=25, headers={"User-Agent": USER_AGENT}) as client:
        try:
            logged_in_psr_url = login_mykomon(client)
            if logged_in_psr_url:
                source_url = logged_in_psr_url
        except RuntimeError as exc:
            print(f"[warn] {exc}", file=sys.stderr)

        response = client.get(source_url)
        response.raise_for_status()
        entries = parse_psr_entries(response.text, source_url)

    if not entries:
        raise RuntimeError("PSRページからお知らせを取得できませんでした。")

    notices = merge_existing(entries[: args.limit], existing)
    DATA_PATH.write_text(json.dumps(notices, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[done] {len(notices)}件を {DATA_PATH.relative_to(ROOT)} に保存しました。")
    print(f"[source] {source_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
