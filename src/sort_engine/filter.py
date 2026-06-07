import re
from typing import Iterator, List, Set, Tuple
from .interface import FilterProtocol

class GrepFilter(FilterProtocol):
    """指定カラムに対して正規表現パターンでフィルタリングを行うクラス"""
    
    def __init__(self, column_index: int, pattern: str) -> None:
        """
        Args:
            column_index: 正規表現を適用するカラムの0ベースインデックス
            pattern: 検索する正規表現パターン
        """
        self.column_index = column_index
        self.pattern = re.compile(pattern)

    def filter(self, rows: Iterator[List[str]]) -> Iterator[List[str]]:
        """条件に合致する行のみを流します。"""
        for row in rows:
            if self.column_index < len(row):
                if self.pattern.search(row[self.column_index]):
                    yield row


class UniqueFilter(FilterProtocol):
    """指定されたキーカラム群の値に基づいて、重複行を排除するクラス"""
    
    def __init__(self, key_indices: List[int]) -> None:
        """
        Args:
            key_indices: 重複チェックのキーとして用いるカラムのインデックス一覧
        """
        self.key_indices = key_indices

    def filter(self, rows: Iterator[List[str]]) -> Iterator[List[str]]:
        """重複していない行のみを流します。"""
        seen: Set[Tuple[str, ...]] = set()
        for row in rows:
            # 指定カラムの値をキーとして抽出
            key = tuple(row[idx] for idx in self.key_indices if idx < len(row))
            if key not in seen:
                seen.add(key)
                yield row
