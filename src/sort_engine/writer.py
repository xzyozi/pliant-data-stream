from collections.abc import Iterator
import csv
from datetime import date, datetime
import sqlite3
from typing import Any

from .interface import WriterProtocol


class CSVWriter(WriterProtocol):
    """結果をCSV（またはTSV）ファイルに出力するライター"""

    def __init__(self, delimiter: str = ",") -> None:
        """
        Args:
            delimiter: 区切り文字（デフォルトはカンマ）
        """
        self.delimiter = delimiter

    def _serialize_row(self, row: list[Any]) -> list[Any]:
        """datetime や date などのオブジェクトを ISO 8601 形式の文字列に変換します。"""
        return [item.isoformat() if isinstance(item, (datetime, date)) else item for item in row]

    def write(self, rows: Iterator[list[Any]], dest_path: str) -> None:
        """データをCSVファイルに書き込みます。"""
        with open(dest_path, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter=self.delimiter)
            for row in rows:
                writer.writerow(self._serialize_row(row))



class SQLiteWriter(WriterProtocol):
    """結果をSQLiteデータベースにインポート・永続化するライター"""

    def __init__(
        self,
        table_name: str = "data_records",
        columns: list[str] | None = None,
        has_header: bool = True,
        batch_size: int = 5000,
        journal_mode: str = "WAL",
        synchronous: str = "NORMAL",
        column_types: dict[str, str] | None = None,
    ) -> None:
        """
        Args:
            table_name: インポート先テーブル名
            columns: カラム名指定。省略時は has_header=True の場合に1行目をヘッダーとして扱います。
            has_header: 渡されるイテレータの1行目がヘッダー行であるか。
            batch_size: バルクインサートを実行する単位行数。
            journal_mode: SQLiteのジャーナルモード（デフォルトは WAL）。
            synchronous: SQLiteの同期モード（デフォルトは NORMAL）。
            column_types: カラム名から型定義文字列へのマッピング辞書。
        """
        self.table_name = table_name
        self.columns = columns
        self.has_header = has_header
        self.batch_size = batch_size
        self.journal_mode = journal_mode
        self.synchronous = synchronous
        self.column_types = column_types

    def _map_to_sqlite_type(self, val: Any) -> str:
        """Pythonのオブジェクト型からSQLiteの型名へマッピングします。"""
        if isinstance(val, int):
            return "INTEGER"
        elif isinstance(val, float):
            return "REAL"
        else:
            return "TEXT"

    def _serialize_row(self, row: list[Any]) -> tuple[Any, ...]:
        """挿入用に、datetime や date などのオブジェクトを文字列（ISO 8601）に変換します。"""
        return tuple(item.isoformat() if isinstance(item, (datetime, date)) else item for item in row)

    def write(self, rows: Iterator[list[Any]], dest_path: str) -> None:
        """SQLiteデータベース（ファイルまたはインメモリ）にデータを永続化します。"""
        conn = sqlite3.connect(dest_path)
        try:
            # バルク挿入の高速化・安全化PRAGMAの適用
            conn.execute(f"PRAGMA synchronous = {self.synchronous};")
            conn.execute(f"PRAGMA journal_mode = {self.journal_mode};")

            # 最初の要素を取得
            try:
                first_row = next(rows)
            except StopIteration:
                # イテレータが空の場合は何もせず終了
                return

            header_cols: list[str] = []
            first_data_row: list[Any] | None = None

            # カラム名の決定
            if self.columns is not None:
                header_cols = self.columns
                if self.has_header:
                    # カラム指定があり、先頭行がヘッダーの場合は読み捨てる
                    try:
                        first_data_row = next(rows)
                    except StopIteration:
                        pass
                else:
                    first_data_row = first_row
            else:
                if self.has_header:
                    header_cols = [str(col) for col in first_row]
                    try:
                        first_data_row = next(rows)
                    except StopIteration:
                        pass
                else:
                    header_cols = [f"col_{i}" for i in range(len(first_row))]
                    first_data_row = first_row

            # 既存テーブルがある場合はスキーマ（カラム数・カラム名）の整合性を検証
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (self.table_name,))
            if cursor.fetchone() is not None:
                cursor.execute(f'PRAGMA table_info("{self.table_name}");')
                existing_cols = cursor.fetchall()
                existing_col_names = [col[1] for col in existing_cols]

                if len(existing_col_names) != len(header_cols):
                    raise ValueError(
                        f"Schema mismatch: Table '{self.table_name}' has {len(existing_col_names)} columns, "
                        f"but input data has {len(header_cols)} columns."
                    )

                existing_col_names_lower = [name.lower() for name in existing_col_names]
                header_cols_lower = [name.lower() for name in header_cols]
                if existing_col_names_lower != header_cols_lower:
                    raise ValueError(
                        f"Schema mismatch: Table '{self.table_name}' column names do not match. "
                        f"Expected: {existing_col_names}, Given: {header_cols}."
                    )

            # ヘッダー行のみでデータが空だった場合
            if first_data_row is None:
                col_defs = ", ".join(f'"{col}" TEXT' for col in header_cols)
                conn.execute(f'CREATE TABLE IF NOT EXISTS "{self.table_name}" ({col_defs});')
                conn.commit()
                return

            # スキーマ（カラム型定義）の決定
            col_defs_list = []
            if self.column_types is not None:
                for col_name in header_cols:
                    col_type = self.column_types.get(col_name, "TEXT")
                    col_defs_list.append(f'"{col_name}" {col_type}')
            else:
                col_types = [self._map_to_sqlite_type(val) for val in first_data_row]
                for col_name, col_type in zip(header_cols, col_types):
                    col_defs_list.append(f'"{col_name}" {col_type}')
            col_defs = ", ".join(col_defs_list)

            # テーブル作成
            conn.execute(f'CREATE TABLE IF NOT EXISTS "{self.table_name}" ({col_defs});')

            # パラメータSQL
            placeholders = ", ".join(["?"] * len(header_cols))
            insert_sql = f'INSERT INTO "{self.table_name}" VALUES ({placeholders});'

            # バッファリングとインサート
            batch = [self._serialize_row(first_data_row)]

            for row in rows:
                batch.append(self._serialize_row(row))
                if len(batch) >= self.batch_size:
                    conn.executemany(insert_sql, batch)
                    batch.clear()

            if batch:
                conn.executemany(insert_sql, batch)

            conn.commit()
        finally:
            conn.close()
