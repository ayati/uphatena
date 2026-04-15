# uphatena

タイムスタンプ付きメモファイル（`memo.txt`）から、はてなブログへ日記を自動投稿する Python3 スクリプトです。

## 機能

- `memo.txt` を読み込み、指定日付のエントリを抽出してはてなブログへ投稿
- 1エントリが複数行にわたる場合も、まとめて1つの時間ブロックとして投稿
- `-` または `+` 付きタイムスタンプの行（非公開エントリ）は、続き行も含めて投稿しない
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

| キー | 説明 |
|------|------|
| `HATENA_ID` | はてなID |
| `BLOG_ID` | ブログのドメイン（例: `foo.hatenablog.com`） |
| `API_KEY` | AtomPub APIキー（[はてなブログ詳細設定](https://blog.hatena.ne.jp/-/config/detail) の「AtomPub」欄） |
| `DIARY_FILE` | `memo.txt` のフルパス |

> **ブログの記法設定を「Markdown記法」にしてください。**  
> `--config` オプションで設定ファイルのパスを明示することもできます。

## memo.txt のフォーマット

`YYYY/MM/DD` または `YYYY-MM-DD` で始まる行がエントリのヘッダ行です。区切り文字は `/` と `-` のどちらでも使えます（同一ファイル内で混在可）。  
ヘッダ行に続く、**日付で始まらない行はすべてそのエントリの続き行**として扱われます。

```
YYYY/MM/DD HH:MM:SS 1行目の本文    ← スラッシュ区切り
YYYY-MM-DD HH:MM:SS 1行目の本文    ← ハイフン区切り（同等）
2行目（続き）
3行目（続き）
YYYY/MM/DD -HH:MM:SS 非公開エントリ（時刻の前に - または + を付ける）
この行も非公開扱いで投稿されない
YYYY/MM/DD +HH:MM:SS こちらも非公開
空行や日付なし行は、エントリ開始前に現れた場合は無視される
```

| パターン | 説明 |
|----------|------|
| `YYYY/MM/DD HH:MM:SS 本文` | 公開エントリ（スラッシュ区切り） |
| `YYYY-MM-DD HH:MM:SS 本文` | 公開エントリ（ハイフン区切り） |
| `YYYY/MM/DD -HH:MM:SS …` | 非公開（時刻の前が `-`）— 続き行ごと投稿しない |
| `YYYY/MM/DD +HH:MM:SS …` | 非公開（時刻の前が `+`）— 続き行ごと投稿しない |
| 日付で始まらない行 | 直前の公開ヘッダ行の続き行 |

- ファイルは新しいエントリを先頭に追記する運用を想定しています（降順）
- ブログへの投稿も時刻降順（新しい順）になります
- 各エントリ末尾の空行は投稿前に除去されます

## 使い方

```bash
# 当日分を投稿（cron用）
python3 uphatena.py

# 特定日を手動投稿
python3 uphatena.py --date 2026-04-11

# 投稿内容を確認するだけ（APIを呼ばない）
python3 uphatena.py --dry-run
python3 uphatena.py --date 2026-04-11 --dry-run

# 設定ファイルを明示する場合
python3 uphatena.py --config /path/to/foruphatena.txt
```

設定ファイルのデフォルトパスはスクリプトと同じディレクトリの `foruphatena.txt` です（実行時のカレントディレクトリには依存しません）。

## 投稿される記事のフォーマット

タイトルは `YYYY-MM-DD`、本文は時刻降順（新しい順）の Markdown になります。  
複数行のエントリは、ヘッダ直下に続けて出力されます。

**memo.txt の例：**

```
2026/04/14 15:00:00 午後のメモ
補足の1行目
補足の2行目
2026/04/14 09:00:00 朝のメモ
```

**投稿される本文：**

```markdown
#### 15:00:00
午後のメモ
補足の1行目
補足の2行目

#### 09:00:00
朝のメモ
```

## 再投稿について

同じ日付を再実行すると既存記事を上書き更新します。  
記事の `updated` フィールドを常に対象日付の末尾（`23:59:59+09:00`）に固定しているため、何ヶ月前の記事でも確実に検出でき、重複投稿は発生しません。

## cron での自動投稿

```cron
55 23 * * * python3 /home/yourname/uphatena/uphatena.py >> /home/yourname/uphatena/uphatena.log 2>&1
```

毎日23:55に当日分を投稿します。

## ライセンス

MIT
