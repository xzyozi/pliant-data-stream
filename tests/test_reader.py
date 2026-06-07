import os
import tempfile
from datetime import date, datetime
import pytest
from sort_engine import CSVReader, auto_cast_value


def test_auto_cast_value() -> None:
    # 整数 (int) の推論
    assert auto_cast_value("123") == 123
    assert auto_cast_value("-456") == -456

    # 浮動小数点数 (float) の推論
    assert auto_cast_value("12.34") == 12.34
    assert auto_cast_value("-0.001") == -0.001

    # 日時 (datetime) の推論
    assert isinstance(auto_cast_value("2026-06-07 12:00:00"), datetime)
    assert auto_cast_value("2026-06-07 15:30:00") == datetime(2026, 6, 7, 15, 30, 0)

    # 日付 (date) の推論
    assert isinstance(auto_cast_value("2026-06-07"), date)
    assert auto_cast_value("2026-06-07") == date(2026, 6, 7)
    assert auto_cast_value("2026/06/07") == date(2026, 6, 7)

    # 文字列 (str) へのフォールバック
    assert auto_cast_value("Hello") == "Hello"
    assert auto_cast_value("  ") == "  "
    assert auto_cast_value("") == ""


def test_csv_reader_auto_detect_csv() -> None:
    content = "ID,Name,Role\n1,Alice,Manager\n2,Bob,Developer"
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8") as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        reader = CSVReader(auto_cast=False)  # delimiter=None (自動判定)
        rows = list(reader.read(temp_file_path))

        assert len(rows) == 3
        assert rows[0] == ["ID", "Name", "Role"]
        assert rows[1] == ["1", "Alice", "Manager"]
        assert rows[2] == ["2", "Bob", "Developer"]
    finally:
        os.remove(temp_file_path)


def test_csv_reader_auto_detect_tsv() -> None:
    content = "ID\tName\tRole\n1\tAlice\tManager\n2\tBob\tDeveloper"
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".tsv", encoding="utf-8") as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        reader = CSVReader(auto_cast=False)  # delimiter=None (自動判定)
        rows = list(reader.read(temp_file_path))

        assert len(rows) == 3
        assert rows[0] == ["ID", "Name", "Role"]
        assert rows[1] == ["1", "Alice", "Manager"]
        assert rows[2] == ["2", "Bob", "Developer"]
    finally:
        os.remove(temp_file_path)


def test_csv_reader_secure_parse() -> None:
    content = (
        "ID,Name,Description\n"
        '1,Alice,"Line1\nLine2"\n'
        '2,Bob,"This is , a comma"\n'
        '3,Charlie,"He said, ""Hello World!"""\n'
        '4,David,"Mixed: , \n and ""quotes"""\n'
    )
    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".csv", encoding="utf-8", newline=""
    ) as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        reader = CSVReader(delimiter=",", auto_cast=False)
        rows = list(reader.read(temp_file_path))

        assert len(rows) == 5

        for idx, row in enumerate(rows):
            assert len(row) == 3, f"Row {idx} has invalid column count: {row}"

        assert rows[0] == ["ID", "Name", "Description"]
        assert rows[1] == ["1", "Alice", "Line1\nLine2"]
        assert rows[2] == ["2", "Bob", "This is , a comma"]
        assert rows[3] == ["3", "Charlie", 'He said, "Hello World!"']
        assert rows[4] == ["4", "David", 'Mixed: , \n and "quotes"']
    finally:
        os.remove(temp_file_path)


def test_csv_reader_auto_cast_integration() -> None:
    # 最初の2行（infer_rows=2）で型判定を行い、以降の行をそれに沿ってキャストする
    content = (
        "ID,Score,Date,Name\n"
        "1,92.5,2026-06-01,Alice\n"
        "2,88.0,2026-06-02,Bob\n"
        "3,95.1,2026-06-03,Charlie\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8", newline="") as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        reader = CSVReader(auto_cast=True, infer_rows=2)
        rows = list(reader.read(temp_file_path))

        assert len(rows) == 4
        # ヘッダーは文字列のまま
        assert rows[0] == ["ID", "Score", "Date", "Name"]
        # 各カラムが正しくキャストされていること
        # col0: int, col1: float, col2: date, col3: str
        assert rows[1] == [1, 92.5, date(2026, 6, 1), "Alice"]
        assert rows[2] == [2, 88.0, date(2026, 6, 2), "Bob"]
        assert rows[3] == [3, 95.1, date(2026, 6, 3), "Charlie"]
    finally:
        os.remove(temp_file_path)


def test_csv_reader_empty_file() -> None:
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8") as temp_file:
        temp_file_path = temp_file.name

    try:
        reader = CSVReader()
        with pytest.raises(ValueError, match="Empty file"):
            list(reader.read(temp_file_path))
    finally:
        os.remove(temp_file_path)


def test_csv_reader_column_mismatch() -> None:
    # 3行目で列数が不一致となるCSV
    content = "ID,Name\n1,Alice\n2,Bob,Developer\n"
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8", newline="") as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        reader = CSVReader()
        with pytest.raises(ValueError, match="Column count mismatch at line 3"):
            list(reader.read(temp_file_path))
    finally:
        os.remove(temp_file_path)


def test_csv_reader_invalid_encoding() -> None:
    # Shift-JISエンコーディングで書き込む
    content = "ID,Name\n1,アリス\n"
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="shift-jis", newline="") as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        reader = CSVReader()
        # UTF-8想定で開くため、デコードエラー（または判定エラー）が起きることを確認
        with pytest.raises(UnicodeDecodeError):
            list(reader.read(temp_file_path))
    finally:
        os.remove(temp_file_path)


def test_csv_reader_cast_failure() -> None:
    # 最初の行から col0 は int と推論されるが、3行目で "Invalid" という文字列が来てキャストに失敗する
    content = "ID,Name\n1,Alice\n2,Bob\nInvalid,Charlie\n"
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8", newline="") as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        reader = CSVReader(auto_cast=True, infer_rows=2)
        with pytest.raises(ValueError, match="Type cast error at line 4"):
            list(reader.read(temp_file_path))
    finally:
        os.remove(temp_file_path)
