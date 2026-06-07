from typing import Any, Callable, Iterator, List

from .interface import SorterProtocol


class ExternalMergeSorter(SorterProtocol):
    """大容量データ用の外部マージソート（External Merge Sort）を実行するクラス"""

    def __init__(self, chunk_size: int = 100000) -> None:
        """
        Args:
            chunk_size: メモリに保持する最大行数。これを超えるたびに一時ファイルへ書き出します。
        """
        self.chunk_size = chunk_size

    def sort(
        self, rows: Iterator[List[str]], key_func: Callable[[List[str]], Any], temp_dir: str
    ) -> Iterator[List[str]]:
        """行データをソートしたイテレータを返します。"""
        # TODO: chunk_size を超えるデータを tempfile を用いてディスクに退避(Spilling)する
        # TODO: heapq.merge を利用して、退避した複数の一時ファイルをマージ(K-wayマージ)する

        # 骨組み実装：ひとまずメモリ上でソートを実行します
        buffer = []
        for row in rows:
            buffer.append(row)
            # 本来はここで chunk_size に達したらソートしてファイルに吐き出します

        buffer.sort(key=key_func)
        for row in buffer:
            yield row
