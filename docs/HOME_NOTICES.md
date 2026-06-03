# トップページ「最新のお知らせ」の更新方法

トップページ右上の「最新のお知らせ」は `src/data/home_notices.json` から自動生成されます。

## かんたん更新（おすすめ）

リポジトリ直下の **`お知らせ更新.bat`** をダブルクリックすると、次を自動で行います。

1. 既存JSONの最新日付以降の差分だけを取得して追記（古い記事と手直し済みの文面は保持）
2. `python scripts/build.py` でビルド
3. お知らせに変更があれば commit して `origin/main` へ push（数分後に公開）

`.env` に `MYKOMON_ID` / `MYKOMON_PASSWORD` が入っていることが前提です。

## 手動での更新手順

1. `.env` に `MYKOMON_ID` と `MYKOMON_PASSWORD` を入れる
2. `python scripts/update_home_notices.py` を実行する（全件再取得）。差分だけなら `--incremental` を付ける
3. 必要に応じて `src/data/home_notices.json` の `title`、`summary`、`body_html` を整える
4. `python scripts/build.py` で表示を確認する
5. `main` に push すると GitHub Pages へ反映される

### `--incremental`（差分だけ取得）

`python scripts/update_home_notices.py --incremental` は、既存JSONの最新日付を `--since` として使い、まだ無い新着だけを既存リストへ足します。全件を取り直さないので速く、`お知らせ更新.bat` もこのモードを使っています。

MyKomonへログインできない場合も、`PSR_TOPICS_URL` の公開ページから取得を試みます。
同じURLのお知らせが既にある場合、手で整えた `title`、`summary`、`body_html` は保持されます。
標準では今年の1月1日以降を全件取得します。期間を変える場合は、たとえば `python scripts/update_home_notices.py --since 2026-04-01` のように指定します。

## 主な項目

| 項目 | 用途 |
|---|---|
| `date` | 表示日。`YYYY-MM-DD` 形式 |
| `source_type` | `ニュース` または `リーフレット` |
| `category` | 税制改正、雇用動向、安全衛生などの小分類 |
| `source_title` | 元記事の表題。管理用で、トップページには表示しません |
| `title` | トップページに出す表題。元記事より少しやわらかい表現にします |
| `summary` | クリック直後に見せる短い説明 |
| `body_html` | もう少し詳しい説明。`<p>...</p>` の形で書けます |
| `url` | 元記事やリーフレットへのリンク |
| `url_label` | リンクボタンの文言 |

## 表示のルール

- 日付の新しい順で表示されます。
- 行をクリックすると説明が同じスクロール枠の中で開きます。
- トップページには最新30件を表示し、「すべて見る」から `/notices/` の全件一覧を開けます。
- `source_type` が `リーフレット` の場合、ラベル色が変わります。
- `tag_color` は `navy`、`wine`、`gold`、`sky`、`violet`、`gray` が使えます。
