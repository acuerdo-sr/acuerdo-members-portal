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

# 取り込まないお知らせカテゴリ（会社のリーフレット / PSR更新情報）
EXCLUDED_IMPORT_CATEGORIES = {"会社のリーフレット", "psr更新情報"}
_EXCLUDED_IMPORT_KEYS = {"".join(c.split()).casefold() for c in EXCLUDED_IMPORT_CATEGORIES}

# PSRサイト自体の宣伝・商品・使い方ページ（事務所通信の案内 / 小冊子・ツール販売 等）は
# 顧問先向けの労務ニュースではないので取り込まない。
# ※ /update/ = 「PSR更新情報」= PSR運営側のお知らせ（商品販売・発送停止・ツール告知 等）。
#   正規の労務ニュースは /topics/ から取得するため、/update/ は丸ごと除外する。
# ※ /dl/leaflet 等（政府の正規リーフレット判定に使用）は除外しないこと。
EXCLUDED_URL_SUBSTRINGS = (
    "/update/",
    "/office_letter",
    "/info_letter",
    "/service",
    "/tool",
    "/pamph",
    "/shop",
    "/cart",
    "/manual",
    "/guide/",
)

# 事務所からの内部発信（在宅勤務・臨時休業案内等の自社お知らせ）を判別する文面マーカー。
OFFICE_NOTICE_MARKERS = ("平素は格別", "ご高配を賜り", "誠に勝手ながら")

# --- AI適切性判定（Gemini） -------------------------------------------------
# URL除外ルールをすり抜けた記事を、顧問先向けの労務ニュースとして適切か最終チェックする。
# GEMINI_API_KEY が未設定、またはAPI障害・応答不正のときは「掲載する」に倒す（取込を止めない）。
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

AI_SCREEN_PROMPT = """\
あなたは社会保険労務士事務所の編集担当です。以下の記事を、顧問先企業向けの
「労務ニュース」として自社ポータルに掲載すべきか判定してください。

【掲載する(YES)】法改正、行政の発表・通達、助成金や補助金の制度情報、労働保険・社会保険の
手続き、統計や調査結果など、顧問先企業の労務管理や手続きに関係する情報。

【掲載しない(NO)】情報提供元(PSR)など外部サービスの商品販売・キャンペーン・セミナー勧誘・
ツールやサービスの宣伝・サイトの使い方案内・発送や休業などの事務連絡。
社労士事務所向けであって顧問先企業向けでない内容。

【税金の扱い】当事務所は社会保険労務士事務所のため、税務そのものは取り扱いません。
・除外(NO): 税制改正の解説、所得税・法人税・消費税の制度改正、税額控除、確定申告など、
　税理士の領域にあたる内容。
・掲載(YES): 税金に触れていても、給与計算・年末調整の実務、源泉徴収事務、
　「年収の壁」など社会保険の適用と結びつく内容は、顧問先の労務実務に必要なので掲載。

判断に迷う場合は掲載(YES)にしてください。

タイトル: {title}
本文: {body}

掲載すべきなら YES、掲載すべきでないなら NO とだけ出力してください。"""


class _AIAuthError(RuntimeError):
    """APIキーが無効・権限不足。リトライしても無駄なので判定自体を打ち切る。"""


def _ai_screen_verdict(title: str, body: str, api_key: str) -> bool | None:
    """記事1件を判定する。True=掲載, False=除外, None=判定不能。"""
    prompt = AI_SCREEN_PROMPT.format(title=title, body=strip_tags(body)[:1500])
    try:
        response = httpx.post(
            GEMINI_ENDPOINT.format(model=GEMINI_MODEL),
            headers={"x-goog-api-key": api_key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                # YES/NOだけ欲しいので思考(thinking)はオフ。オンだと思考トークンが
                # maxOutputTokens を食い潰し、本文が空のまま MAX_TOKENS で返る。
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": 16,
                    "thinkingConfig": {"thinkingBudget": 0},
                },
            },
            timeout=30,
        )
        if response.status_code in (400, 401, 403):
            # キーが無効/権限不足。以降の記事も必ず同じ結果になるので中断させる。
            detail = ""
            try:
                detail = response.json().get("error", {}).get("message", "")
            except Exception:
                pass
            raise _AIAuthError(detail or f"HTTP {response.status_code}")
        response.raise_for_status()
        candidate = response.json()["candidates"][0]
        parts = candidate.get("content", {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip().upper()
        if not text:
            raise ValueError(f"応答が空です (finishReason={candidate.get('finishReason')})")
    except _AIAuthError:
        raise
    except Exception as exc:  # ネットワーク/一時的なAPIエラー/応答形式変更
        print(f"[warn] AI判定に失敗しました（掲載扱いにします）: {title} ({exc})", file=sys.stderr)
        return None
    if "NO" in text:
        return False
    if "YES" in text:
        return True
    print(f"[warn] AI判定の応答を解釈できません（掲載扱い）: {title} -> {text!r}", file=sys.stderr)
    return None


def ai_screen_entries(entries: list[dict]) -> list[dict]:
    """新着記事をAI判定にかけ、不適切と判定されたものを除外して返す。"""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[skip] GEMINI_API_KEY 未設定のためAI判定をスキップします。")
        return entries
    if not entries:
        return entries

    kept: list[dict] = []
    for index, item in enumerate(entries):
        title = item.get("source_title") or item.get("title") or ""
        body = item.get("source_body_html") or item.get("body_html") or ""
        try:
            verdict = _ai_screen_verdict(title, body, api_key)
        except _AIAuthError as exc:
            print(
                f"[warn] GEMINI_API_KEY が無効なためAI判定を中止します（全件そのまま掲載）: {exc}\n"
                "       → https://aistudio.google.com/apikey でキーを再発行し .env を更新してください。",
                file=sys.stderr,
            )
            return kept + list(entries[index:])
        if verdict is False:
            print(f"[ai-skip] 顧問先向けでないと判定: {title}")
            continue
        kept.append(item)
    if len(kept) != len(entries):
        print(f"[ai] {len(entries) - len(kept)}件をAI判定で除外しました。")
    return kept


def _is_office_internal(item: dict) -> bool:
    text = " ".join(
        str(item.get(k) or "")
        for k in ("title", "summary", "body_html", "source_body_html", "source_title")
    )
    return any(marker in text for marker in OFFICE_NOTICE_MARKERS)


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


def load_existing_list() -> list[dict]:
    if not DATA_PATH.exists():
        return []
    try:
        items = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return items if isinstance(items, list) else []


def item_key(item: dict) -> str | None:
    return item.get("url") or item.get("source_title") or item.get("id")


def load_existing(existing_list: list[dict] | None = None) -> dict[str, dict]:
    items = existing_list if existing_list is not None else load_existing_list()
    return {item_key(item): item for item in items}


def latest_existing_date(existing_list: list[dict]) -> str | None:
    dates = [item.get("date") for item in existing_list if item.get("date")]
    return max(dates) if dates else None


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
        if any(sub in href for sub in EXCLUDED_URL_SUBSTRINGS):
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
        if main_category and main_category not in {"トピックス"} and source_type != "リーフレット":
            continue
        category = compact_category(sub_category or main_category, title, source_type)
        if "".join(category.split()).casefold() in _EXCLUDED_IMPORT_KEYS:
            continue
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


def collect_entries(client: httpx.Client, source_url: str, since: str, max_pages: int) -> list[dict]:
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
    # /update/（PSR更新情報）はPSR運営側のお知らせ（商品販売・発送停止・ツール告知 等）で
    # 顧問先向けの労務ニュースではないため巡回しない。念のためURL除外でも二重に弾いている。
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
    targets = [item for item in entries if item.get("url")]
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
            for key in ("id", "title", "summary", "body_html", "tag_color"):
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
    parser.add_argument(
        "--incremental",
        action="store_true",
        default=os.getenv("HOME_NOTICES_INCREMENTAL") == "1",
        help="既存JSONの最新日付以降の差分だけを取得して追記します（古い記事は保持）。",
    )
    args = parser.parse_args()

    existing_list = load_existing_list()
    existing = load_existing(existing_list)

    # 増分モード: 既存の最新日付を since にして、新着分だけを既存へ足す。
    if args.incremental:
        newest = latest_existing_date(existing_list)
        if newest:
            args.since = newest
            print(f"[incremental] 既存の最新日付 {newest} 以降の差分を取得します。")
        else:
            print("[incremental] 既存データが無いため全件取得します。")

    try:
        datetime.strptime(args.since, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("--since は YYYY-MM-DD 形式で指定してください。") from exc

    source_url = os.getenv("PSR_TOPICS_URL") or DEFAULT_PSR_URL

    with httpx.Client(follow_redirects=True, timeout=25, headers={"User-Agent": USER_AGENT}) as client:
        try:
            logged_in_psr_url = login_mykomon(client)
            if logged_in_psr_url:
                source_url = logged_in_psr_url
        except RuntimeError as exc:
            print(f"[warn] {exc}", file=sys.stderr)

        entries = collect_entries(client, source_url, args.since, args.max_pages)
        selected = entries[: args.limit] if args.limit > 0 else entries

    if not entries:
        raise RuntimeError("PSRページからお知らせを取得できませんでした。")

    # 増分モードでは既存に無い新着だけを対象にする（古い記事や手直し済み文面は保持）。
    if args.incremental:
        new_entries = [item for item in selected if item_key(item) not in existing]
        if not new_entries:
            print("[incremental] 新着のお知らせはありませんでした。既存データを維持します。")
            print(f"[since] {args.since}")
            print(f"[source] {source_url}")
            return 0
        if not args.skip_details:
            hydrate_source_bodies(new_entries)
        before = len(new_entries)
        new_entries = [item for item in new_entries if not _is_office_internal(item)]
        skipped = before - len(new_entries)
        if skipped:
            print(f"[skip] 事務所発信のお知らせ {skipped}件を除外しました。")
        new_entries = ai_screen_entries(new_entries)
        for idx, item in enumerate(new_entries):
            item.setdefault("tag_color", TAG_COLORS[idx % len(TAG_COLORS)])
        combined = new_entries + existing_list
        notices = sorted(combined, key=lambda r: r.get("date", ""), reverse=True)
        DATA_PATH.write_text(json.dumps(notices, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[done] 新着 {len(new_entries)}件を追加し、合計 {len(notices)}件を {DATA_PATH.relative_to(ROOT)} に保存しました。")
        print(f"[since] {args.since}")
        print(f"[source] {source_url}")
        return 0

    if not args.skip_details:
        hydrate_source_bodies(selected)

    # 事務所からの内部発信（在宅勤務・臨時休業案内等の自社お知らせ）は取り込まない。
    before = len(selected)
    selected = [item for item in selected if not _is_office_internal(item)]
    skipped = before - len(selected)
    if skipped:
        print(f"[skip] 事務所発信のお知らせ {skipped}件を除外しました。")

    # AI判定は既存JSONに無い記事だけに絞る（既存分の再判定はAPI無駄打ちになるため）。
    fresh = [item for item in selected if item_key(item) not in existing]
    dropped = {id(item) for item in fresh} - {id(item) for item in ai_screen_entries(fresh)}
    if dropped:
        selected = [item for item in selected if id(item) not in dropped]

    notices = merge_existing(selected, existing)
    DATA_PATH.write_text(json.dumps(notices, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[done] {len(notices)}件を {DATA_PATH.relative_to(ROOT)} に保存しました。")
    print(f"[since] {args.since}")
    print(f"[source] {source_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
