import os
import sqlite3
import tempfile
from datetime import date, datetime
import pytest
from sort_engine import CSVWriter, SQLiteWriter


# ---------------------------------------------------------------------------
# CSVWriter のテスト
# ---------------------------------------------------------------------------


def test_csv_writer() -> None:
    """CSVWriter が正常に出力先にデータを書き出せるか検証"""
    data = [
        ["ID", "Name", "Score"],
        [1, "Alice", 92.5],
        [2, "Bob", 88.0],
    ]

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as temp_file:
        temp_file_path = temp_file.name

    try:
        writer = CSVWriter(delimiter=",")
        writer.write(iter(data), temp_file_path)

        with open(temp_file_path, mode="r", encoding="utf-8") as f:
            lines = f.read().splitlines()

        assert len(lines) == 3
        assert lines[0] == "ID,Name,Score"
        assert lines[1] == "1,Alice,92.5"
        assert lines[2] == "2,Bob,88.0"
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)


# ---------------------------------------------------------------------------
# SQLiteWriter のテスト
# ---------------------------------------------------------------------------


def test_sqlite_writer_in_memory_has_header() -> None:
    """インメモリ SQLite でのヘッダーあり書き込みと型推論の検証"""
    data = [
        ["ID", "Score", "Name", "Date"],
        [1, 92.5, "Alice", date(2026, 6, 1)],
        [2, 88.0, "Bob", date(2026, 6, 2)],
    ]

    # インメモリ DB に接続するための準備として、同一コネクションを使い回す
    # sqlite3.connect(":memory:") は接続ごとに新規の空DBになるため、
    # SQLiteWriter.write が閉じた後は検証できない。
    # このため一時ファイル形式でインメモリ風にテストするか、あるいは
    # 一時ファイルベースのテストで検証します。

    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as temp_db:
        temp_db_path = temp_db.name

    try:
        writer = SQLiteWriter(table_name="test_table", has_header=True)
        writer.write(iter(data), temp_db_path)

        # データベースを再オープンして検証
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()

        # スキーマ構造の確認
        cursor.execute("PRAGMA table_info(test_table);")
        columns = cursor.fetchall()
        # columns format: (cid, name, type, notnull, dflt_value, pk)
        assert len(columns) == 4
        assert columns[0][1] == "ID"
        assert columns[0][2] == "INTEGER"
        assert columns[1][1] == "Score"
        assert columns[1][2] == "REAL"
        assert columns[2][1] == "Name"
        assert columns[2][2] == "TEXT"
        assert columns[3][1] == "Date"
        assert columns[3][2] == "TEXT"

        # データの確認
        cursor.execute("SELECT * FROM test_table;")
        rows = cursor.fetchall()
        assert len(rows) == 2
        # date オブジェクトは isoformat 文字列で入っていること
        assert rows[0] == (1, 92.5, "Alice", "2026-06-01")
        assert rows[1] == (2, 88.0, "Bob", "2026-06-02")

        conn.close()
    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)


def test_sqlite_writer_no_header() -> None:
    """ヘッダーなし指定の場合の自動カラム名生成とインサート検証"""
    data = [
        [10, "Alice"],
        [20, "Bob"],
    ]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as temp_db:
        temp_db_path = temp_db.name

    try:
        writer = SQLiteWriter(table_name="test_table_no_header", has_header=False)
        writer.write(iter(data), temp_db_path)

        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()

        # スキーマの確認 (自動生成された col_0, col_1 であること)
        cursor.execute("PRAGMA table_info(test_table_no_header);")
        columns = cursor.fetchall()
        assert len(columns) == 2
        assert columns[0][1] == "col_0"
        assert columns[0][2] == "INTEGER"
        assert columns[1][1] == "col_1"
        assert columns[1][2] == "TEXT"

        # データの確認 (1行目からインサートされていること)
        cursor.execute("SELECT * FROM test_table_no_header;")
        rows = cursor.fetchall()
        assert len(rows) == 2
        assert rows[0] == (10, "Alice")
        assert rows[1] == (20, "Bob")

        conn.close()
    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)


def test_sqlite_writer_explicit_columns() -> None:
    """columns 指定が明示された場合のテーブル生成検証"""
    data = [
        ["IgnoreHeaderCol1", "IgnoreHeaderCol2"],
        [1, "Alice"],
        [2, "Bob"],
    ]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as temp_db:
        temp_db_path = temp_db.name

    try:
        # columns 指定あり、かつ has_header=True なので、先頭行は読み捨てる
        writer = SQLiteWriter(
            table_name="explicit_table",
            columns=["MyID", "MyName"],
            has_header=True
        )
        writer.write(iter(data), temp_db_path)

        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(explicit_table);")
        columns = cursor.fetchall()
        assert len(columns) == 2
        assert columns[0][1] == "MyID"
        assert columns[1][1] == "MyName"

        cursor.execute("SELECT * FROM explicit_table;")
        rows = cursor.fetchall()
        assert len(rows) == 2
        assert rows[0] == (1, "Alice")

        conn.close()
    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)


def test_sqlite_writer_empty_data() -> None:
    """イテレータが空の場合に何も作成されず終了することの検証"""
    data = []

    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as temp_db:
        temp_db_path = temp_db.name

    try:
        writer = SQLiteWriter(table_name="empty_table")
        # 例外を起こさずに正常終了すること
        writer.write(iter(data), temp_db_path)

        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        # テーブルが作成されていないこと
        assert len(tables) == 0
        conn.close()
    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)


def test_sqlite_writer_pragma_settings() -> None:
    """PRAGMA設定が正しくデータベースに適用されることを検証"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as temp_db:
        temp_db_path = temp_db.name

    try:
        # カスタムPRAGMAを指定
        writer = SQLiteWriter(
            table_name="test_pragma",
            has_header=False,
            journal_mode="DELETE",
            synchronous="FULL"
        )
        data = [[1, "test"]]
        writer.write(iter(data), temp_db_path)

        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()

        # journal_mode は DELETE になるはず
        cursor.execute("PRAGMA journal_mode;")
        journal_mode = cursor.fetchone()[0]
        assert journal_mode.upper() == "DELETE"

        # synchronous は FULL (2) になるはず
        cursor.execute("PRAGMA synchronous;")
        sync = cursor.fetchone()[0]
        assert sync == 2  # 2 = FULL

        conn.close()
    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)

