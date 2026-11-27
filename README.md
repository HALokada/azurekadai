# 激熱ドパガキ掲示板

ドーパミンを求める高校生のための交流掲示板です。いいねの代わりに「🧠 ドーパミン」を送ると、音が鳴って画面に演出が出ます。

- サイト：https://azurekadai03-frd3a5bfhqb6fzg8.eastasia-01.azurewebsites.net/
- 作者：IH12A233 03 岡田健吾

## 機能
| 機能 | 内容 |
| --- | --- |
| メインページ | 「フォロワー投稿」「おすすめ投稿（ドーパミンが多い順）」を切り替え |
| 投稿 | 右下の ＋ ボタンでポップアップ。タイトル・内容・画像／動画／音楽 |
| ドーパミン | 押すと効果音と演出。連打すると音が高くなる。もう一度押すと取り消し |
| マイページ | 自分の投稿一覧（削除できる）、ドーパミンした投稿一覧 |
| ユーザーページ | ほかの人の投稿一覧、フォロー |
| 投稿の演出 | 投稿すると紙吹雪と「ドーパミン投下完了💉」 |
| ランキング | 今日の投稿／全期間の投稿／ドーパミン王（もらった合計）。上位 3 位に 👑🥈🥉 |
| ガチャ | 1 日 1 回。アイコン枠とドーパミンボタンの色が当たる（N〜UR の 5 段階）。コレクションから装備できる |

## 使っているもの
- Python 3.12 / Flask
- Azure App Service（Linux）
- Azure Table Storage：ユーザー・投稿・ドーパミン・フォロー
- Azure Blob Storage：画像・動画・音楽（`media` コンテナ）

## Azure の設定
App Service →「設定」→「環境変数」→「アプリ設定」に次の 2 つを入れる（値はコードに書かない）。

| 名前 | 値 |
| --- | --- |
| `AZURE_STORAGE_CONNECTION_STRING` | ストレージアカウントの接続文字列 |
| `SECRET_KEY` | ランダムな長い文字列（ログイン状態の暗号化に使う） |

App Service →「設定」→「構成」→「スタートアップ コマンド」：

```
gunicorn --bind=0.0.0.0 --timeout 600 app:app
```

デプロイは App Service の「デプロイ センター」で GitHub のこのリポジトリ（main ブランチ）をつなぐ。

## パソコンで動かす
接続文字列を入れなければ、データは `local_data` フォルダに保存される（テスト用）。

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

http://localhost:5000 を開く。
