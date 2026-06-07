import csv
import sqlite3
from typing import Iterator, List
from .interface import WriterProtocol

class CSVWriter(WriterProtocol):
    """結果をCSV（またはTSV）ファイルに出力するライター"""
    
    def __init__(self, delimiter: str = ",") -> None:
        """
        Args:
            delimiter: 区切り文字（デフォルトはカンマ）
        """
        self.delimiter = delimiter

    def write(self, rows: Iterator[List[str]], dest_path: str) -> None:
        """データをCSVファイルに書き込みます。"""
        with open(dest_path, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter=self.delimiter)
            for row in rows:
                writer.writerow(row)


class SQLiteWriter(WriterProtocol):
    """結果をSQLiteデータベースにインポート・永続化するライター"""
    
    def __init__(self, table_name: str = "data_records") -> None:
        """
        Args:
            table_name: インポート先テーブル名
        """
        self.table_name = table_name

    def write(self, rows: Iterator[List[str]], dest_path: str) -> None:
        """SQLiteデータベース（ファイルまたはインメモリ）にデータを永続化します。"""
        # TODO: カラム定義の自動生成、インポート処理の実装
        # 骨組み実装のみ
        conn = sqlite3.connect(dest_path)
        cursor = conn.cursor()
        
        # 例としての仮処理
        try:
            # 実際の実装では最初の行などを元に動的にテーブルを作成します
            pass
        finally:
            conn.close()
