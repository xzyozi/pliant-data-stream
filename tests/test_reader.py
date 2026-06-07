import os
import tempfile
from datetime import datetime
from sort_engine import CSVReader, auto_cast_value


def test_auto_cast_value() -> None:
    # 整数 (int) の推論
    assert auto_cast_value("123") == 123
    assert auto_cast_value("-456") == -456
    
    # 浮動小数点数 (float) の推論
    assert auto_cast_value("12.34") == 12.34
    assert auto_cast_value("-0.001") == -0.001
    
    # 日付/日時 (datetime) の推論
    assert isinstance(auto_cast_value("2026-06-07"), datetime)
    assert auto_cast_value("2026-06-07") == datetime(2026, 6, 7)
    assert auto_cast_value("2026/06/07 15:30:00") == datetime(2026, 6, 7, 15, 30, 0)
    
    # 文字列 (str) へのフォールバック
    assert auto_cast_value("Hello") == "Hello"
    assert auto_cast_value("  ") == "  "
    assert auto_cast_value("") == ""


def test_csv_reader_auto_detect_csv() -> None:
    # CSV形式の一時ファイルを作成
    content = "ID,Name,Role\n1,Alice,Manager\n2,Bob,Developer"
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8") as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        reader = CSVReader()  # delimiter=None (自動判定)
        rows = list(reader.read(temp_file_path))
        
        assert len(rows) == 3
        assert rows[0] == ["ID", "Name", "Role"]
        assert rows[1] == ["1", "Alice", "Manager"]
        assert rows[2] == ["2", "Bob", "Developer"]
    finally:
        os.remove(temp_file_path)


def test_csv_reader_auto_detect_tsv() -> None:
    # TSV形式の一時ファイルを作成
    content = "ID\tName\tRole\n1\tAlice\tManager\n2\tBob\tDeveloper"
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".tsv", encoding="utf-8") as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        reader = CSVReader()  # delimiter=None (自動判定)
        rows = list(reader.read(temp_file_path))
        
        assert len(rows) == 3
        assert rows[0] == ["ID", "Name", "Role"]
        assert rows[1] == ["1", "Alice", "Manager"]
        assert rows[2] == ["2", "Bob", "Developer"]
    finally:
        os.remove(temp_file_path)


def test_csv_reader_secure_parse() -> None:
    # 改行、デリミタ（カンマ）、エスケープされたダブルクォーテーション（""）を含む複雑なCSV
    content = (
        'ID,Name,Description\n'
        '1,Alice,"Line1\nLine2"\n'                      # 改行を含む行
        '2,Bob,"This is , a comma"\n'                   # デリミタを含む行
        '3,Charlie,"He said, ""Hello World!"""\n'        # エスケープされたダブルクォート ("")
        '4,David,"Mixed: , \n and ""quotes"""\n'          # すべてが混在する行
    )
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8", newline="") as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        reader = CSVReader(delimiter=",")
        rows = list(reader.read(temp_file_path))
        
        # ヘッダーとデータ4行の計5行であること
        assert len(rows) == 5
        
        # すべての行が欠損なく正しいカラム数（3列）でパースされていること
        for idx, row in enumerate(rows):
            assert len(row) == 3, f"Row {idx} has invalid column count: {row}"
            
        assert rows[0] == ["ID", "Name", "Description"]
        # 改行が正しく保持されていること
        assert rows[1] == ["1", "Alice", "Line1\nLine2"]
        # デリミタ（カンマ）が正しく保持されていること
        assert rows[2] == ["2", "Bob", "This is , a comma"]
        # エスケープされたダブルクォーテーションが正しくデコードされていること
        assert rows[3] == ["3", "Charlie", 'He said, "Hello World!"']
        # 全要素の混在したフィールドが正しくパースされていること
        assert rows[4] == ["4", "David", 'Mixed: , \n and "quotes"']
    finally:
        os.remove(temp_file_path)
