from typing import Iterator, List, Set, Tuple
from .interface import FilterProtocol


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
