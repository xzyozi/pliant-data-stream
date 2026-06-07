import csv
from typing import Iterator, List, Optional

from .interface import ReaderProtocol


class CSVReader(ReaderProtocol):
    """CSVおよびTSVファイル用のリーダー"""

    def __init__(self, delimiter: Optional[str] = None) -> None:
        """
        Args:
            delimiter: 区切り文字。Noneの場合は自動判定を試みます。
        """
        self.delimiter = delimiter

    def read(self, file_path: str) -> Iterator[List[str]]:
        """ファイルを開いて行データを読み込みます。"""
        # TODO: 巨大ファイルを扱うため、必要に応じてジェネレータで適切にストリーム処理します。
        # TODO: csv.Sniffer を使ったデリミタ自動判定をここに組み込みます。
        delim = self.delimiter if self.delimiter is not None else ","

        with open(file_path, mode="r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f, delimiter=delim)
            for row in reader:
                yield row
