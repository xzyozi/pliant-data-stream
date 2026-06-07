from typing import Any, Callable, Iterator, List, Protocol, runtime_checkable


@runtime_checkable
class ReaderProtocol(Protocol):
    """ファイルから行データを読み込むためのプロトコル"""

    def read(self, file_path: str) -> Iterator[List[Any]]:
        """指定されたパスのファイルを読み込み、パースされた行データ（Anyのリスト）のイテレータを返します。"""
        ...


@runtime_checkable
class FilterProtocol(Protocol):
    """行データをフィルタリング・加工するためのプロトコル"""

    def filter(self, rows: Iterator[List[Any]]) -> Iterator[List[Any]]:
        """行データのストリームを受け取り、フィルタリングや加工を施したストリームを返します。"""
        ...


@runtime_checkable
class SorterProtocol(Protocol):
    """データをソートするためのプロトコル"""

    def sort(
        self, rows: Iterator[List[Any]], key_func: Callable[[List[Any]], Any], temp_dir: str
    ) -> Iterator[List[Any]]:
        """行データのストリームを受け取り、指定されたソートキーでソートされたストリームを返します。
        必要に応じて一時ファイル出力先として temp_dir を利用します。
        """
        ...


@runtime_checkable
class WriterProtocol(Protocol):
    """処理結果を外部（ファイルやDB）に書き出すためのプロトコル"""

    def write(self, rows: Iterator[List[Any]], dest_path: str) -> None:
        """行データのストリームを指定された宛先に書き出します。"""
        ...
