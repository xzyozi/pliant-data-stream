# sort_engine 詳細設計書

本ドキュメントでは、`sort_engine` モジュールの各コンポーネントにおけるクラス、メソッド、内部アルゴリズム、セキュリティ対策、スレッドセーフティ、データ整合性の保証などについて詳細に記述します。

---

## 1. モジュール構成・パッケージ構造

`sort_engine` モジュールは以下のファイル群で構成されています。

```
src/sort_engine/
├── __init__.py         # パッケージエントリーポイント。主要クラスの公開。
├── interface.py        # プロトコル（インターフェース）の定義。
├── engine.py           # パイプライン制御の SortEngine 実装。
├── reader.py           # CSVReader などのデータ入力層の実装。
├── filter.py           # UniqueFilter などのデータ加工・フィルタ層の実装。
├── sorter.py           # ExternalMergeSorter による外部マージソートの実装。
└── writer.py           # CSVWriter, SQLiteWriter などのデータ出力層の実装。
```

---

## 2. インターフェース定義 (`interface.py`)

Python 3.10 の `typing.Protocol` および `@runtime_checkable` を用いて、各層間の疎結合性を担保するプロトコルを定義しています。

### 2.1. `ReaderProtocol`
```python
class ReaderProtocol(Protocol):
    def read(self, file_path: str) -> Iterator[List[Any]]: ...
```
- **責務**: 指定されたファイルパスからデータを読み込み、行データ（リスト）のストリーム（Iterator）として返します。
- **型変換**: 具象クラス側で必要に応じて型推論や型キャストを適用します。

### 2.2. `FilterProtocol`
```python
class FilterProtocol(Protocol):
    def filter(self, rows: Iterator[List[Any]]) -> Iterator[List[Any]]: ...
```
- **責務**: 行データの Iterator を受け取り、フィルタリングや加工を施した新しい Iterator を返します。

### 2.3. `SorterProtocol`
```python
class SorterProtocol(Protocol):
    def sort(self, rows: Iterator[List[Any]], key_func: Callable[[List[Any]], Any], temp_dir: str) -> Iterator[List[Any]]: ...
```
- **責務**: 行データの Iterator を受け取り、`key_func` による比較キー評価値を用いてソートされた新しい Iterator を返します。メモリ制限を超過する場合は `temp_dir` を使用して一時ファイルへの退避を実行します。

### 2.4. `WriterProtocol`
```python
class WriterProtocol(Protocol):
    def write(self, rows: Iterator[List[Any]], dest_path: str) -> None: ...
```
- **責務**: 処理済みのストリーム（Iterator）を指定された出力先 `dest_path` に永続化（出力）します。

---

## 3. コアパイプライン `SortEngine` (`engine.py`)

### 3.1. 概要
`SortEngine` は、データの読み込みから書き出しまでのパイプラインを一貫してジェネレータ（ストリーム）で駆動する実行制御エンジンです。メモリ消費量を一定に抑えながらギガバイト級の大容量データを処理します。

### 3.2. 主要メソッド
- `__init__(self, reader: ReaderProtocol, filters: list[FilterProtocol], sorter: SorterProtocol, writer: WriterProtocol)`
  - 依存関係の注入 (DI) を行い、各コンポーネントを初期化します。
- `execute(self, input_path: str, output_path: str, key_func: Callable[[list[Any]], Any], temp_dir: str, header_restoration: bool = True) -> None`
  - パイプラインを実行します。
  - **ヘッダー復元のロジック (`header_restoration`)**:
    ソート処理（`Sorter`）にヘッダー行が含まれると順序が狂うため、リーダーから取得したデータの先頭（ヘッダー）を退避させ、ソート済みのデータストリームの先頭に再度付加してライターへ渡します。

---

## 4. データ入力層 `CSVReader` (`reader.py`)

### 4.1. 概要
CSV/TSV ファイルの解析と型自動キャスト、およびセキュアなパースを行うリーダーです。

### 4.2. 機能詳細
- **デリミタ自動判定**: ファイルの先頭行のカンマ `,` やタブ `\t` の出現頻度から CSV または TSV を自動で判定します。
- **自動型キャスト**: 文字列値から `int`, `float`, `datetime`, `date` へのキャストを試み、成功した型に自動マッピングします。
- **セキュアパース**: ファイルサイズや入力行に対して不正なエンコーディングがあった場合、適切にフォールバックします。

---

## 5. データフィルタ層 `UniqueFilter` (`filter.py`)

### 5.1. 概要
ストリーム中に含まれる重複データを特定のキーカラムに基いて排除します。

### 5.2. アルゴリズム
- メモリ上で既に処理したユニークキーを保持する `set` を管理します。
- データのストリームを順次処理し、指定されたキーカラム値が `set` に未登録であれば通過させ、登録済みであればスキップ（除外）します。これにより、メモリ効率良くユニークフィルタリングを実行します。

---

## 6. データソート層 `ExternalMergeSorter` (`sorter.py`)

### 6.1. 概要
メモリ消費量を指定された `chunk_size` に抑えながらソートを実行する外部マージソートの実装です。

### 6.2. 処理フローとアルゴリズム
1. **チャンク分割と一時ソート (Spill)**:
   - 入力ストリームを `chunk_size` 行ごとにメモリ上に読み込み、ソート（インメモリソート）します。
   - ソート済みチャンクを一時ファイルにシリアライズ（pickle）して退避させます。
2. **多段マージ (Cascading Merge)**:
   - システムのファイル記述子制限（OS制限）を回避するため、同時オープンファイル数が `max_open_files` を超える場合は、段階的に部分マージを行い中間一時ファイルに退避させます。
3. **K-Wayマージ**:
   - `heapq.merge` を用いて、最終的な一時ファイル群から値をストリームとしてマージしながら出力します。

### 6.3. 安全性と堅牢性設計
- **SafeComparableKey (型混在対応)**:
  - SQLiteやCSVから読み込まれた値に `None`, `int`, `str` などの異なる型が混在する場合、通常の比較演算子は `TypeError` でクラッシュします。
  - `SafeComparableKey` ラッパークラスにより、型が異なる場合は「型名の文字列」で、型名が同じで比較不能な場合は「文字列表現」で比較する安全なフォールバックを実装しています。
- **タイブレークシーケンス番号 (seq)**:
  - 評価値（ソートキー）が同値の場合に、行データ（リスト）自体の比較に落ちてクラッシュするのを防ぐため、内部でインクリメントされる一意のシーケンス番号（`seq`）をタプルに付与してソートします。
- **ファイル保護とクリーンアップ**:
  - 一時ファイルのパーミッションには `os.open` の `0o600` を適用し、所有者のみに読み書きを制限します。
  - `atexit` フックおよびインスタンス内ロックにより、例外によるクラッシュやスレッド並列実行時でも未削除の一時ファイルを確実に消去します。

---

## 7. データ出力層 `writer.py`

### 7.1. CSVWriter
- 任意のデリミタを用いた CSV/TSV への書き出し。
- `_serialize_row` メソッドにより、`datetime`/`date` オブジェクトを ISO 8601 文字列（`isoformat()`）へ変換してから出力します（戻り値は `tuple[Any, ...]` で SQLiteWriter と対称化）。

### 7.2. SQLiteWriter

#### 構成クラス・メソッドと役割分担
肥大化を避けるため、各処理が単一責任の原則に従ってメソッド分割されています。

1. **`write(self, rows: Iterator[list[Any]], dest_path: str) -> None`**
   - コネクションの生成、PRAGMAの設定、および例外発生時の `conn.close()` 制御を行います。全体のパイプラインを実行制御します。
2. **`_resolve_columns_and_data(self, first_row: list[Any], rows: Iterator[list[Any]]) -> tuple[list[str], list[Any] | None]`**
   - 先頭行 (`first_row`) とイテレータから、最終的に適用するカラムヘッダーリスト (`header_cols`) と、最初のデータ行 (`first_data_row`) を割り出します。
3. **`_validate_existing_schema(self, conn: sqlite3.Connection, escaped_table_name: str, header_cols: list[str]) -> bool`**
   - 同名のテーブルが既に存在するかを検証します。存在する場合は `PRAGMA table_info` を用いて、カラム数およびカラム名（大文字小文字を除く）が入力データと整合するかをチェックし、不一致なら日本語の `ValueError` を送出します。テーブルが存在すれば `True`、新規作成が必要なら `False` を返します。
4. **`_determine_schema(self, header_cols: list[str], first_data_row: list[Any] | None) -> str`**
   - `column_types` が指定されている場合はそれを採用し、ない場合は `first_data_row` のデータ値の型（`int` -> `INTEGER` 等）から動的に推論して `col_defs` の文字列を作成します。
5. **`_insert_rows(self, conn: sqlite3.Connection, escaped_table_name: str, header_cols: list[str], first_data_row: list[Any], rows: Iterator[list[Any]]) -> None`**
   - トランザクション内で `executemany` とバッファリングを行い、`batch_size`（デフォルト 5000 行）ごとにバルク挿入を行います。

#### 堅牢性とパフォーマンスチューニング
- **SQLインジェクション対策とサニタイズ**:
  - `journal_mode` と `synchronous` に無効な値や悪意ある文字列が注入されるのを防ぐため、コンストラクタで許可リスト（Whitelist）を用いてパラメータを厳密に検証します。
  - `_escape_identifier` により、テーブル名やカラム名に `"` (ダブルクォート) が含まれている場合でも `""` に適切にエスケープし、構文破壊を防ぎます。
- **既存テーブル追記時のバイパス**:
  - 追記先のテーブルが既に存在する場合、不要な型推論（スキーマ決定）および `CREATE TABLE` の呼び出しを完全にバイパスして直接インサート処理に移行します。また、空データでの追記時はテーブル作成自体をスキップして即時に終了します。
- **トランザクション管理**:
  - コネクションオブジェクトのコンテキストマネージャ（`with conn:`）を使用し、例外発生時には自動ロールバック、正常終了時には自動コミットされるよう安全に管理されています。
- **デフォルトPRAGMA設定**:
  - 安全性と高速性のバランスを取るため、デフォルトで `journal_mode = "WAL"` および `synchronous = "NORMAL"` を適用しています。
