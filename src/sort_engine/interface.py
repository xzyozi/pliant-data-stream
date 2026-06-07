from typing import Any, Callable, Iterator, List, Protocol, runtime_checkable

@runtime_checkable
class ReaderProtocol(Protocol):
    """ファイルから行データを読み込むためのプロトコル"""
    def read(self, file_path: str) -> Iterator[List[str]]:
        """指定されたパスのファイルを読み込み、パースされた行データ（文字列リスト）のイテレータを返します。"""
        ...

@runtime_checkable
class FilterProtocol(Protocol):
    """行データをフィルタリング・加工するためのプロトコル"""
    def filter(self, rows: Iterator[List[str]]) -> Iterator[List[str]]:
        """行データのストリームを受け取り、フィルタリングや加工を施したストリームを返します。"""
        ...

@runtime_checkable
class SorterProtocol(Protocol):
    """データをソートするためのプロトコル"""
    def sort(
        self,
        rows: Iterator[List[str]],
        key_func: Callable[[List[str]], Any],
        temp_dir: str
    ) -> Iterator[List[str]]:
        """行データのストリームを受け取り、指定されたソートキーでソートされたストリームを返します。
        必要に応じて一時ファイル出力先として temp_dir を利用します。
        """
        ...

@runtime_checkable
class WriterProtocol(Protocol):
    """処理結果を外部（ファイルやDB）に書き出すためのプロトコル"""
    def write(self, rows: Iterator[List[str]], dest_path: str) -> None:
        """行データのストリームを指定された宛先に書き出します。"""
        ...
