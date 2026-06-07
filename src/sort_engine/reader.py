import csv
from datetime import datetime
from typing import Iterator, List, Optional, Union

from .interface import ReaderProtocol


def auto_cast_value(val: str) -> Union[int, float, datetime, str]:
    """文字列値を最適なデータ型（int, float, datetime, str）に変換します。

    変換を試みる順序:
    1. 整数 (int)
    2. 浮動小数点数 (float)
    3. 日付/日時 (datetime)
    4. 元の文字列 (str)
    """
    val_stripped = val.strip()
    if not val_stripped:
        return val  # 空文字列（欠損値）はそのまま返す

    # 1. 整数
    try:
        return int(val_stripped)
    except ValueError:
        pass

    # 2. 浮動小数点数
    try:
        return float(val_stripped)
    except ValueError:
        pass

    # 3. 日付/日時
    # 代表的な日付フォーマットでのパースを試みる
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
        "%I:%M:%S %p",
    ):
        try:
            return datetime.strptime(val_stripped, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(val_stripped)
    except ValueError:
        pass

    # 4. 文字列フォールバック
    return val


class CSVReader(ReaderProtocol):
    """CSVおよびTSVファイル用のリーダー"""

    def __init__(self, delimiter: Optional[str] = None) -> None:
        """
        Args:
            delimiter: 区切り文字。Noneの場合は自動判定を試みます。
        """
        self.delimiter = delimiter

    def read(self, file_path: str) -> Iterator[List[str]]:
        """ファイルを開いて行データをストリームで読み込みます。"""
        delim = self.delimiter

        # delimiterが指定されていない場合は csv.Sniffer による自動判定を試みる
        if delim is None:
            try:
                with open(file_path, mode="r", encoding="utf-8", newline="") as f:
                    # 先頭4KB程度を読み取って判定
                    sample = f.read(4096)
                    if sample:
                        dialect = csv.Sniffer().sniff(sample)
                        delim = dialect.delimiter
                    else:
                        delim = ","
            except Exception:
                # 判定失敗時（フォーマット破損や空ファイル等）はカンマをデフォルトとする
                delim = ","

        with open(file_path, mode="r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f, delimiter=delim)
            for row in reader:
                yield row
