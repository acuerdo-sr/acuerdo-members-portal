# トップページ「最新のお知らせ」の更新方法

トップページ右上の「最新のお知らせ」は `src/data/home_notices.json` から自動生成されます。

## 更新手順

1. `.env` に `MYKOMON_ID` と `MYKOMON_PASSWORD` を入れる
2. `python scripts/update_home_notices.py` を実行する
3. 必要に応じて `src/data/home_notices.json` の `title`、`summary`、`body_html` を整える
4. `python scripts/build.py` で表示を確認する
5. `main` に push すると GitHub Pages へ反映される

MyKomonへログインできない場合も、`PSR_TOPICS_URL` の公開ページから取得を試みます。
同じURLのお知らせが既にある場合、手で整えた `title`、`summary`、`body_html` は保持されます。

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
- `source_type` が `リーフレット` の場合、ラベル色が変わります。
- `tag_color` は `navy`、`wine`、`gold`、`sky`、`violet`、`gray` が使えます。
