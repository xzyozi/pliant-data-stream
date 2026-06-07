import os
import tempfile
from datetime import date, datetime
import pytest
from sort_engine import CSVReader, auto_cast_value


# ---------------------------------------------------------------------------
# auto_cast_value のユニットテスト
# ---------------------------------------------------------------------------


def test_auto_cast_value_timestamp_enabled() -> None:
    """enable_timestamp_cast=True の場合、10桁/13桁数値をdatetimeに変換する"""
    # 秒ベース (10桁)
    assert isinstance(auto_cast_value("1717751200", enable_timestamp_cast=True), datetime)
    assert auto_cast_value("1717751200", enable_timestamp_cast=True) == datetime.fromtimestamp(1717751200)
    # ミリ秒ベース (13桁)
    assert isinstance(auto_cast_value("1717751200000", enable_timestamp_cast=True), datetime)
    assert auto_cast_value("1717751200000", enable_timestamp_cast=True) == datetime.fromtimestamp(1717751200)
    # 小数点付き秒ベース
    assert isinstance(auto_cast_value("1717751200.5", enable_timestamp_cast=True), datetime)
    assert auto_cast_value("1717751200.5", enable_timestamp_cast=True) == datetime.fromtimestamp(1717751200.5)


def test_auto_cast_value_timestamp_disabled() -> None:
    """enable_timestamp_cast=False を明示した場合、10桁数値は int/float に留まる"""
    # 10桁の数値はタイムスタンプではなくintとして返る
    result = auto_cast_value("1717751200", enable_timestamp_cast=False)
    assert isinstance(result, int)
    assert result == 1717751200

    # 13桁の数値もintとして返る
    result_ms = auto_cast_value("1717751200000", enable_timestamp_cast=False)
    assert isinstance(result_ms, int)
    assert result_ms == 1717751200000

    # 小数点付きはfloat
    result_float = auto_cast_value("1717751200.5", enable_timestamp_cast=False)
    assert isinstance(result_float, float)
    assert result_float == 1717751200.5


def test_auto_cast_value_int() -> None:
    assert auto_cast_value("123") == 123
    assert auto_cast_value("-456") == -456


def test_auto_cast_value_float() -> None:
    assert auto_cast_value("12.34") == 12.34
    assert auto_cast_value("-0.001") == -0.001


def test_auto_cast_value_datetime() -> None:
    assert isinstance(auto_cast_value("2026-06-07 12:00:00"), datetime)
    assert auto_cast_value("2026-06-07 15:30:00") == datetime(2026, 6, 7, 15, 30, 0)


def test_auto_cast_value_date() -> None:
    assert isinstance(auto_cast_value("2026-06-07"), date)
    assert auto_cast_value("2026-06-07") == date(2026, 6, 7)
    assert auto_cast_value("2026/06/07") == date(2026, 6, 7)


def test_auto_cast_value_str_fallback() -> None:
    assert auto_cast_value("Hello") == "Hello"
    assert auto_cast_value("  ") == ""  # 空文字列（トリミング適用）
    assert auto_cast_value("") == ""


# ---------------------------------------------------------------------------
# CSVReader のデリミタ自動判定テスト
# ---------------------------------------------------------------------------


def test_csv_reader_auto_detect_csv() -> None:
    content = "ID,Name,Role\n1,Alice,Manager\n2,Bob,Developer"
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8") as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        reader = CSVReader(auto_cast=False)  # delimiter=None (自動判定)
        rows = list(reader.read(temp_file_path))

        assert reader.header == ["ID", "Name", "Role"]
        assert len(rows) == 2
        assert rows[0] == ["1", "Alice", "Manager"]
        assert rows[1] == ["2", "Bob", "Developer"]
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

        assert reader.header == ["ID", "Name", "Role"]
        assert len(rows) == 2
        assert rows[0] == ["1", "Alice", "Manager"]
        assert rows[1] == ["2", "Bob", "Developer"]
    finally:
        os.remove(temp_file_path)


# ---------------------------------------------------------------------------
# セキュアパーステスト（改行・カンマ・エスケープクォート）
# ---------------------------------------------------------------------------


def test_csv_reader_secure_parse() -> None:
    content = (
        "ID,Name,Description\n"
        '1,Alice,"Line1\nLine2"\n'
        '2,Bob,"This is , a comma"\n'
        '3,Charlie,"He said, ""Hello World!""\"\n'
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

        assert reader.header == ["ID", "Name", "Description"]
        assert len(rows) == 4

        for idx, row in enumerate(rows):
            assert len(row) == 3, f"Row {idx} has invalid column count: {row}"

        assert rows[0] == ["1", "Alice", "Line1\nLine2"]
        assert rows[1] == ["2", "Bob", "This is , a comma"]
        assert rows[2] == ["3", "Charlie", 'He said, "Hello World!"']
        assert rows[3] == ["4", "David", 'Mixed: , \n and "quotes"']
    finally:
        os.remove(temp_file_path)


# ---------------------------------------------------------------------------
# 型推論の統合テスト
# ---------------------------------------------------------------------------


def test_csv_reader_auto_cast_integration() -> None:
    """enable_timestamp_cast=True を明示した場合、タイムスタンプがdatetimeに変換される"""
    content = (
        "ID,Score,Date,TimestampSec,TimestampMs,Name\n"
        "1,92.5,2026-06-01,1717751200,1717751200000,Alice\n"
        "2,88.0,2026-06-02,1717751260,1717751260000,Bob\n"
        "3,95.1,2026-06-03,1717751320,1717751320000,Charlie\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8", newline="") as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        reader = CSVReader(auto_cast=True, infer_rows=2, enable_timestamp_cast=True)
        rows = list(reader.read(temp_file_path))

        assert reader.header == ["ID", "Score", "Date", "TimestampSec", "TimestampMs", "Name"]
        assert len(rows) == 3
        # 各カラムが正しくキャストされていること（ヘッダー行はrowsに含まれない）
        assert rows[0] == [
            1,
            92.5,
            date(2026, 6, 1),
            datetime.fromtimestamp(1717751200),
            datetime.fromtimestamp(1717751200),
            "Alice",
        ]
        assert rows[1] == [
            2,
            88.0,
            date(2026, 6, 2),
            datetime.fromtimestamp(1717751260),
            datetime.fromtimestamp(1717751260),
            "Bob",
        ]
        assert rows[2] == [
            3,
            95.1,
            date(2026, 6, 3),
            datetime.fromtimestamp(1717751320),
            datetime.fromtimestamp(1717751320),
            "Charlie",
        ]
    finally:
        os.remove(temp_file_path)


def test_csv_reader_auto_cast_timestamp_disabled_by_default() -> None:
    """enable_timestamp_cast=False (デフォルト) では10桁数値はintのまま保持される"""
    content = (
        "ID,BusinessID,Name\n"
        "1,1500000000,Alice\n"
        "2,1600000000,Bob\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8", newline="") as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        # デフォルト (enable_timestamp_cast=False)
        reader = CSVReader(has_header=True, auto_cast=True, infer_rows=2)
        rows = list(reader.read(temp_file_path))

        assert reader.header == ["ID", "BusinessID", "Name"]
        assert len(rows) == 2
        # BusinessID は datetime ではなく int のままであること
        assert isinstance(rows[0][1], int)
        assert rows[0][1] == 1500000000
    finally:
        os.remove(temp_file_path)


def test_csv_reader_mixed_date_datetime_infers_datetime() -> None:
    """date と datetime が同一カラムに混在する場合、datetime に推論されること"""
    content = (
        "ID,Timestamp\n"
        "1,2026-06-01\n"
        "2,2026-06-02 12:00:00\n"
        "3,2026-06-03\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8", newline="") as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        reader = CSVReader(has_header=True, auto_cast=True, infer_rows=3)
        rows = list(reader.read(temp_file_path))

        assert reader.header == ["ID", "Timestamp"]
        assert len(rows) == 3
        # すべて datetime オブジェクトになっているはず
        assert isinstance(rows[0][1], datetime)
        assert isinstance(rows[1][1], datetime)
        assert isinstance(rows[2][1], datetime)
        assert rows[0][1] == datetime(2026, 6, 1, 0, 0, 0)
        assert rows[1][1] == datetime(2026, 6, 2, 12, 0, 0)
        assert rows[2][1] == datetime(2026, 6, 3, 0, 0, 0)
    finally:
        os.remove(temp_file_path)


# ---------------------------------------------------------------------------
# 異常系テスト
# ---------------------------------------------------------------------------


def test_csv_reader_empty_file() -> None:
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8") as temp_file:
        temp_file_path = temp_file.name

    try:
        reader = CSVReader()
        with pytest.raises(ValueError, match="ファイルが空です"):
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
        with pytest.raises(ValueError, match="列数が一致しません"):
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
        reader = CSVReader(has_header=True, auto_cast=True, infer_rows=2)
        with pytest.raises(ValueError, match="型キャストエラーが発生しました"):
            list(reader.read(temp_file_path))
    finally:
        os.remove(temp_file_path)


# ---------------------------------------------------------------------------
# ヘッダー判定テスト
# ---------------------------------------------------------------------------


def test_csv_reader_no_header() -> None:
    # ヘッダーなし（has_header=False）の動作テスト
    content = (
        "1,92.5,2026-06-01\n"
        "2,88.0,2026-06-02\n"
        "3,95.1,2026-06-03\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8", newline="") as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        reader = CSVReader(has_header=False, auto_cast=True, infer_rows=2)
        rows = list(reader.read(temp_file_path))

        assert reader.header is None
        assert len(rows) == 3
        assert rows[0] == [1, 92.5, date(2026, 6, 1)]
        assert rows[1] == [2, 88.0, date(2026, 6, 2)]
        assert rows[2] == [3, 95.1, date(2026, 6, 3)]
    finally:
        os.remove(temp_file_path)


def test_csv_reader_auto_detect_has_header() -> None:
    # ヘッダーありデータの自動検知テスト
    content_with_header = "ID,Score,Date\n1,92.5,2026-06-01\n2,88.0,2026-06-02\n"
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8", newline="") as temp_file:
        temp_file.write(content_with_header)
        temp_file_path_h = temp_file.name

    try:
        reader = CSVReader(has_header=None)  # 自動判定
        rows = list(reader.read(temp_file_path_h))

        assert reader.header == ["ID", "Score", "Date"]
        assert len(rows) == 2
        assert rows[0] == [1, 92.5, date(2026, 6, 1)]
        assert rows[1] == [2, 88.0, date(2026, 6, 2)]
    finally:
        os.remove(temp_file_path_h)
