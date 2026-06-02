"""MyKomon/PSRからトップページ用のお知らせJSONを更新する。

使い方:
    python scripts/update_home_notices.py

.env に MYKOMON_ID / MYKOMON_PASSWORD がある場合はMyKomonへログインして
PSRページのURLを探す。見つからない場合は PSR_TOPICS_URL を取得元にする。
標準では今年の1月1日以降のお知らせを取得する。
既存JSONに同じURLのお知らせがある場合、トップ表示用の言い換え文は保持する。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from html import escape, unescape
from pathlib import Path
from urllib.parse import urljoin

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "src" / "data" / "home_notices.json"
MYKOMON_HOME_URL = "https://www.mykomon.com/app/homeSr"
MYKOMON_LOGIN_URL = "https://www.mykomon.com/MyKomon/login.do"
MYKOMON_NEWS_LIST_URL = "https://www.mykomon.com/contents/listSr.do?srCategoryCode=04"
DEFAULT_PSR_URL = "https://www.psrn.jp/?transactionid=2e633e95368f07dd5080458f9cd82fd3e24bd47e"
PSR_TOPICS_LIST_URL = "https://www.psrn.jp/topics/"
PSR_UPDATE_LIST_URL = "https://www.psrn.jp/update/"
DEFAULT_SINCE = f"{date.today().year}-01-01"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
)

TAG_COLORS = ["navy", "sky", "gold", "violet", "wine", "gray"]
BLOCK_TAGS = ("div", "section", "article", "main")


def strip_tags(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def extract_balanced_element(html: str, start: int, tag: str) -> str:
    pattern = re.compile(rf"</?{tag}\b[^>]*>", flags=re.I)
    depth = 0
    for match in pattern.finditer(html, start):
        token = match.group(0)
        if token.startswith("</"):
            depth -= 1
            if depth == 0:
                return html[start:match.end()]
        elif not token.endswith("/>"):
            depth += 1
    return ""


def inner_html(element_html: str) -> str:
    match = re.match(r"<([a-z0-9]+)\b[^>]*>([\s\S]*)</\1>\s*$", element_html.strip(), flags=re.I)
    return match.group(2) if match else element_html


def find_element_by_class(html: str, class_name: str, tags: tuple[str, ...] = BLOCK_TAGS) -> str:
    for tag in tags:
        for match in re.finditer(rf"<{tag}\b[^>]*>", html, flags=re.I):
            attrs = match.group(0)
            class_match = re.search(r'class=["\']([^"\']+)["\']', attrs, flags=re.I)
            if not class_match:
                continue
            classes = set(class_match.group(1).split())
            if class_name not in classes:
                continue
            element_html = extract_balanced_element(html, match.start(), tag)
            if element_html:
                return inner_html(element_html)
    return ""


def trim_psr_wrapper_paragraph(html: str) -> str:
    html = html.strip()
    if re.match(r"^<p\b[^>]*>\s*<(?:p|ul|ol)\b", html, flags=re.I):
        html = re.sub(r"^<p\b[^>]*>\s*", "", html, count=1, flags=re.I)
        html = re.sub(r"(</(?:p|ul|ol)>\s*)</p>\s*$", r"\1", html, flags=re.I)
    return html


def clean_source_html(raw_html: str, base_url: str) -> str:
    html = re.sub(r"<!--[\s\S]*?-->", "", raw_html)
    html = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", html, flags=re.I)
    html = re.sub(r"<img\b[^>]*>", "", html, flags=re.I)
    html = trim_psr_wrapper_paragraph(html)

    def clean_anchor(match: re.Match) -> str:
        attrs = match.group(1)
        href_match = re.search(r'href=["\']([^"\']+)["\']', attrs, flags=re.I)
        text = strip_tags(match.group(2))
        if not href_match:
            return escape(text)
        href = unescape(href_match.group(1)).strip()
        if not href or href == "#":
            return escape(text)
        abs_href = urljoin(base_url, href)
        label = text or abs_href
        return (
            f'<a href="{escape(abs_href, quote=True)}" target="_blank" rel="noopener">'
            f"{escape(label)}</a>"
        )

    html = re.sub(r"<a\b([^>]*)>([\s\S]*?)</a>", clean_anchor, html, flags=re.I)
    html = re.sub(r"<br\b[^>]*>", "<br>", html, flags=re.I)

    allowed = {"p", "br", "ul", "ol", "li", "strong", "b", "em", "a"}

    def clean_tag(match: re.Match) -> str:
        slash = match.group(1)
        tag = match.group(2).lower()
        if tag not in allowed:
            return "\n" if tag in {"div", "section", "article", "table", "tbody", "tr", "td", "th"} else ""
        if tag == "a":
            return match.group(0)
        if tag == "br":
            return "<br>"
        return f"<{slash}{tag}>"

    html = re.sub(r"<(/?)([a-z0-9]+)\b[^>]*>", clean_tag, html, flags=re.I)
    html = re.sub(r"\s+\n", "\n", html)
    html = re.sub(r"\n\s+", "\n", html)
    html = re.sub(r"(?:\s*<br>\s*){3,}", "<br><br>", html)
    html = re.sub(r"<p>\s*</p>", "", html, flags=re.I)
    return html.strip()


def source_url_paragraph(url: str) -> str:
    if not url:
        return ""
    url = escape(url, quote=True)
    return f'<p><a href="{url}" target="_blank" rel="noopener">{url}</a></p>'


def extract_source_body_html(html: str, base_url: str) -> str:
    entry_body = find_element_by_class(html, "entry_body", tags=("section", "div", "article"))
    if entry_body:
        body_html = clean_source_html(entry_body, base_url)
        if body_html and "href=" not in body_html:
            body_html += source_url_paragraph(base_url)
        return body_html

    contents = find_element_by_class(html, "contents", tags=("div", "section", "article"))
    if not contents:
        return source_url_paragraph(base_url)

    paragraphs = re.findall(r"<p\b[^>]*>[\s\S]*?</p>", contents, flags=re.I)
    cleaned: list[str] = []
    for paragraph in paragraphs:
        text = strip_tags(paragraph)
        if not text or text == " ":
            continue
        cleaned_paragraph = clean_source_html(paragraph, base_url)
        if cleaned_paragraph:
            cleaned.append(cleaned_paragraph)
        if len(cleaned) >= 4:
            break
    body_html = "".join(cleaned)
    if base_url and base_url not in body_html:
        body_html += source_url_paragraph(base_url)
    return body_html.strip()


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


def has_mykomon_credentials() -> bool:
    login_id = os.getenv("MYKOMON_ID") or os.getenv("MYKOMON_LOGINNAME")
    password = os.getenv("MYKOMON_PASSWORD") or os.getenv("MYKOMON_PASS")
    return bool(login_id and password)


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


def make_mykomon_id(href: str, date_value: str) -> str:
    code_match = re.search(r"srContentsCode=([A-Za-z0-9_-]+)", href)
    code = code_match.group(1).lower() if code_match else re.sub(r"[^a-zA-Z0-9]+", "-", href).strip("-")[:32]
    return f"mykomon-{date_value.replace('-', '')}-{code or 'notice'}"


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


def entry_blocks(html: str) -> list[str]:
    blocks = re.findall(r"<li>\s*<p class=\"entry_head\">([\s\S]*?)</li>", html)
    blocks += re.findall(r"<article class=\"entry\">([\s\S]*?)</article>", html)
    return blocks


def parse_psr_entries(html: str, base_url: str) -> list[dict]:
    entries: list[dict] = []
    for block in entry_blocks(html):
        links = re.findall(r'<a\s+href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', block, flags=re.I)
        link = next((item for item in reversed(links) if "?tag=" not in item[0]), None)
        if not link:
            continue
        href = urljoin(base_url, unescape(link[0]))
        if "/feature/" in href:
            continue
        title = strip_tags(link[1])
        head = strip_tags(block)
        date_match = re.search(r"(\d{4})/(\d{2})/(\d{2})", head)
        if not date_match:
            continue
        source_date = date_match.group(0)
        date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
        before_title = head.split(title, 1)[0]
        parts = before_title.split()
        main_category = parts[2] if len(parts) >= 3 else ""
        sub_category = " ".join(parts[3:]).strip()
        source_type = classify_source(main_category, sub_category, title, href)
        if main_category and main_category not in {"トピックス", "PSR更新情報"} and source_type != "リーフレット":
            continue
        category = compact_category(sub_category or main_category, title, source_type)
        entries.append(
            {
                "id": make_id(href, title),
                "date": date,
                "source_date": source_date,
                "source_type": source_type,
                "category": category,
                "source_title": title,
                "title": soften_title(title, source_type),
                "summary": default_summary(source_type, category, title),
                "body_html": default_body(source_type, category),
                "url": href,
            }
        )
    return entries


def parse_mykomon_entries(html: str, base_url: str) -> list[dict]:
    entries: list[dict] = []
    for row_html in re.findall(r"<tr\b[^>]*>([\s\S]*?)</tr>", html, flags=re.I):
        if "srContentsCode=" not in row_html:
            continue
        link_match = re.search(
            r'<a\s+href=["\']?([^"\'\s>]+)["\']?[^>]*>([\s\S]*?)</a>',
            row_html,
            flags=re.I,
        )
        date_match = re.search(r"(\d{4})/(\d{2})/(\d{2})", row_html)
        if not link_match or not date_match:
            continue
        href = link_match.group(1)
        title_html = link_match.group(2)
        year, month, day = date_match.groups()
        title = strip_tags(title_html)
        if not title:
            continue
        url = urljoin(base_url, unescape(href))
        date_value = f"{year}-{month}-{day}"
        source_date = f"{year}/{month}/{day}"
        entries.append(
            {
                "id": make_mykomon_id(url, date_value),
                "date": date_value,
                "source_date": source_date,
                "source_type": "ニュース",
                "category": "my顧問 人事労務ニュース",
                "source_title": title,
                "title": title,
                "summary": "MyKomonの人事労務ニュースから追加しました。詳細はリンク先でご確認ください。",
                "body_html": (
                    "<p>MyKomonの人事労務ニュースから追加した情報です。</p>"
                    "<p>自社の労務管理や従業員対応に関係しそうな内容は、担当者間で共有してください。</p>"
                ),
                "url": url,
                "source": "MyKomon",
                "tag_color": "navy",
            }
        )
    return entries


def fetch_mykomon_entries(client: httpx.Client, since: str, seen: set[str]) -> list[dict]:
    response = client.get(MYKOMON_NEWS_LIST_URL)
    response.raise_for_status()
    html = response.content.decode("cp932", errors="replace")
    entries: list[dict] = []
    for item in parse_mykomon_entries(html, str(response.url)):
        key = item.get("url") or item.get("source_title") or item.get("id")
        if not key or key in seen:
            continue
        seen.add(key)
        if (item.get("date") or "") >= since:
            entries.append(item)
    return entries


def fetch_series(
    client: httpx.Client,
    url: str,
    since: str,
    max_pages: int,
    seen: set[str],
) -> list[dict]:
    entries: list[dict] = []
    for page in range(1, max_pages + 1):
        page_url = url if page == 1 else f"{url}?p={page}"
        response = client.get(page_url)
        response.raise_for_status()
        page_entries = parse_psr_entries(response.text, page_url)
        if not page_entries:
            break

        oldest = page_entries[-1].get("date") or ""
        for item in page_entries:
            key = item.get("url") or item.get("source_title") or item.get("id")
            if not key or key in seen:
                continue
            seen.add(key)
            if (item.get("date") or "") >= since:
                entries.append(item)

        if oldest and oldest < since:
            break
    return entries


def collect_entries(
    client: httpx.Client,
    source_url: str,
    since: str,
    max_pages: int,
    include_mykomon: bool = False,
) -> list[dict]:
    seen: set[str] = set()
    entries: list[dict] = []

    # MyKomonから遷移したトップURL、または指定されたPSRトップURLを先に見る。
    response = client.get(source_url)
    response.raise_for_status()
    for item in parse_psr_entries(response.text, source_url):
        key = item.get("url") or item.get("source_title") or item.get("id")
        if key and key not in seen:
            seen.add(key)
            if (item.get("date") or "") >= since:
                entries.append(item)

    entries.extend(fetch_series(client, PSR_TOPICS_LIST_URL, since, max_pages, seen))
    entries.extend(fetch_series(client, PSR_UPDATE_LIST_URL, since, max_pages, seen))
    if include_mykomon:
        entries.extend(fetch_mykomon_entries(client, since, seen))
    return sorted(entries, key=lambda r: r.get("date", ""), reverse=True)


def fetch_source_body(source_url: str) -> tuple[str, str, str | None]:
    try:
        response = httpx.get(
            source_url,
            follow_redirects=True,
            timeout=25,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return source_url, "", str(exc)
    return source_url, extract_source_body_html(response.text, str(response.url)), None


def hydrate_source_bodies(entries: list[dict]) -> None:
    targets = [item for item in entries if item.get("url") and item.get("source") != "MyKomon"]
    if not targets:
        return

    workers = int(os.getenv("HOME_NOTICES_DETAIL_WORKERS", "8") or 8)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(fetch_source_body, item["url"]): item for item in targets}
        for index, future in enumerate(as_completed(futures), start=1):
            item = futures[future]
            source_url, body_html, error = future.result()
            if error:
                print(f"[warn] 詳細本文を取得できませんでした: {source_url} ({error})", file=sys.stderr)
                continue
            if body_html:
                item["source_body_html"] = body_html
            if index % 50 == 0:
                print(f"[detail] {index}件の本文を確認しました。")


def merge_existing(generated: list[dict], existing: dict[str, dict]) -> list[dict]:
    merged: list[dict] = []
    for idx, item in enumerate(generated):
        previous = existing.get(item.get("url")) or existing.get(item.get("source_title")) or existing.get(item.get("id"))
        if previous:
            for key in ("id", "title", "summary", "body_html", "source_body_html", "tag_color"):
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
    parser.add_argument("--since", default=os.getenv("HOME_NOTICES_SINCE") or DEFAULT_SINCE)
    parser.add_argument("--limit", type=int, default=int(os.getenv("HOME_NOTICES_LIMIT", "0") or 0))
    parser.add_argument("--max-pages", type=int, default=int(os.getenv("HOME_NOTICES_MAX_PAGES", "20") or 20))
    parser.add_argument(
        "--skip-details",
        action="store_true",
        default=os.getenv("HOME_NOTICES_SKIP_DETAILS") == "1",
        help="一覧だけ更新し、各詳細ページの本文取得を省略します。",
    )
    args = parser.parse_args()
    try:
        datetime.strptime(args.since, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("--since は YYYY-MM-DD 形式で指定してください。") from exc

    source_url = os.getenv("PSR_TOPICS_URL") or DEFAULT_PSR_URL
    existing = load_existing()

    with httpx.Client(follow_redirects=True, timeout=25, headers={"User-Agent": USER_AGENT}) as client:
        mykomon_logged_in = False
        try:
            if has_mykomon_credentials():
                logged_in_psr_url = login_mykomon(client)
                mykomon_logged_in = True
                if logged_in_psr_url:
                    source_url = logged_in_psr_url
        except RuntimeError as exc:
            print(f"[warn] {exc}", file=sys.stderr)

        entries = collect_entries(client, source_url, args.since, args.max_pages, mykomon_logged_in)
        selected = entries[: args.limit] if args.limit > 0 else entries
    if not args.skip_details:
        hydrate_source_bodies(selected)

    if not entries:
        raise RuntimeError("PSRページからお知らせを取得できませんでした。")

    notices = merge_existing(selected, existing)
    DATA_PATH.write_text(json.dumps(notices, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[done] {len(notices)}件を {DATA_PATH.relative_to(ROOT)} に保存しました。")
    print(f"[since] {args.since}")
    print(f"[source] {source_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
