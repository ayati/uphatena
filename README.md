# uphatena

タイムスタンプ付きメモファイル（`memo.txt`）から、はてなブログへ日記を投稿する Python3 スクリプトです。

## 機能

- `memo.txt` を読み込み、指定日付のエントリを抽出してはてなブログへ投稿
- `-` または `+` 付きタイムスタンプの行（非公開エントリ）は投稿しない
- 同じ日付の記事が既に存在する場合は上書き更新（何日前の記事でも重複しない）
- `--dry-run` オプションで投稿内容をターミナルに表示して確認可能
- cron による自動投稿と手動投稿の両方に対応

## 必要環境

- Python 3.7+
- `requests` ライブラリ

```bash
pip install requests
```

## セットアップ

スクリプトと同じディレクトリに設定ファイル `foruphatena.txt` を作成します（`.gitignore` 済み）。

```ini
HATENA_ID  = your_hatena_id
BLOG_ID    = your_id.hatenablog.com
API_KEY    = your_atompub_api_key
DIARY_FILE = /path/to/memo.txt
```

- API キーは [はてなブログの詳細設定](https://blog.hatena.ne.jp/-/config/detail) の「AtomPub」欄で確認できます。
- `DIARY_FILE` はフルパス推奨（相対パスは実行時のカレントディレクトリ基準になります）。
- ブログの記法設定を「Markdown記法」にしてください。

## memo.txt のフォーマット

1行1エントリ、形式は `YYYY/MM/DD HH:MM:SS 本文` です。

```
2026/04/12 14:30:40 公開エントリ
2026/04/12 -09:00:00 非公開エントリ（時刻の前に - または + を付けると投稿されない）
2026/04/12 +08:00:00 こちらも非公開
空行や行頭が日付でない行はすべて無視されます
```

- ファイルは新しいエントリを先頭に追記する運用を想定しています（降順）
- ブログへの投稿も時刻降順（新しい順）になります

## 使い方

```bash
# 当日分を投稿（cron用）— foruphatena.txt はスクリプトと同じディレクトリを自動参照
python3 uphatena.py

# 特定日を手動投稿
python3 uphatena.py --date 2026-04-11

# 投稿内容を確認するだけ（APIを呼ばない）
python3 uphatena.py --dry-run
python3 uphatena.py --date 2026-04-11 --dry-run

# 設定ファイルを明示する場合
python3 uphatena.py --config /path/to/foruphatena.txt
```

### 投稿される記事のフォーマット

タイトルは `YYYY-MM-DD`、本文は時刻降順（新しい順）の Markdown になります。

```markdown
#### 14:30:40
公開エントリA

#### 11:20:00
公開エントリB
```

### 再投稿について

同じ日付を再実行すると既存記事を上書き更新します。記事の `updated` フィールドを常に対象日付に固定しているため、数ヶ月前の記事でも確実に検出でき、重複投稿は発生しません。

## cron での自動投稿

```cron
55 23 * * * python3 /home/yourname/uphatena/uphatena.py >> /home/yourname/uphatena/uphatena.log 2>&1
```

毎日23:55に当日分を投稿します。

## ライセンス

MIT
