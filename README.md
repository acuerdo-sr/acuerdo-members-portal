# ACUERDO 顧問先ポータル (GitHub Pages 版)

アクエルド社会保険労務士法人の顧問先向け情報ポータル。Notion をコンテンツソースとし、ビルド時に静的HTMLを生成して GitHub Pages で配信。

## 構成

- **ホーム / 助成金早見表**: 静的HTML（`src/pages/` の手書きテンプレート）
- **FAQ / 書式 / 各種カレンダー等**: Notion から自動取得 → HTML 生成
- **デプロイ**: `main` への push と日次 cron で GitHub Actions が再ビルド → GitHub Pages へ自動公開

## ローカル開発

```bash
# 初期セットアップ
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# .env に NOTION_TOKEN を記入

# ビルド
python scripts/build.py

# プレビュー
python -m http.server -d dist 8000
# http://localhost:8000/
```

## ディレクトリ構成

```
acuerdo-members-portal/
├── .github/workflows/   # GitHub Actions
├── assets/
│   ├── css/site.css     # 全ページ共通スタイル
│   ├── js/site.js       # 共通スクリプト（ナビ・ハンバーガー・早見表フィルタ）
│   └── img/
├── src/
│   ├── _layout/         # レイアウトテンプレート（chrome）
│   ├── pages/           # 静的ページソース
│   └── data/            # 助成金早見表データ等
├── scripts/
│   ├── build.py             # メインビルド
│   ├── fetch_notion.py      # Notion API クライアント
│   └── render_blocks.py     # Notionブロック → HTML
├── dist/                 # ビルド成果物（gitignored）
└── requirements.txt
```

## Notion ページ ID

- トップ（参照のみ）: `34f7a82f-ba9a-8014-ac3d-d4eae441a24f`
- 助成金ページ(A): `3697a82f-ba9a-8137-9f2a-eb28d3244e35`
- 助成金早見表(B): `3687a82f-ba9a-8144-ade0-c81178fafa77`（Notionは編集用、表示は静的）
- 法改正カレンダー DB: `3587a82f-ba9a-814f-9e63-d3c749a71779`
- 補助金カレンダー DB: `3587a82f-ba9a-81e4-aebc-ed272b08f783`
- 事務組合カレンダー DB: `3587a82f-ba9a-814e-81ea-c211d978f839`

## URL構造

| URL | コンテンツソース |
|---|---|
| `/` | 静的（src/pages/index.html） |
| `/joseikin/` | Notion `3697a82f...` |
| `/joseikin-list/` | 静的（src/pages/joseikin-list.html）+ JSON |
| `/faq/` | Notion（FAQ DB） |
| `/forms/` | Notion（書式ページ） |
| `/lawrev/` | Notion（法改正カレンダー DB） |
| `/calendar/` | Notion（年間カレンダー） |
| `/contact/` | Notion（お問い合わせ） |
