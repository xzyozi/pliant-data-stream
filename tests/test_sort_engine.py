import pytest
from typing import Iterator, List
from sort_engine import (
    SortEngine,
    ReaderProtocol,
    SorterProtocol,
    WriterProtocol,
    GrepFilter,
)

# テスト用の簡易モック実装
class MockReader(ReaderProtocol):
    def __init__(self, data: List[List[str]]) -> None:
        self.data = data
        
    def read(self, file_path: str) -> Iterator[List[str]]:
        for row in self.data:
            yield row


class MockWriter(WriterProtocol):
    def __init__(self) -> None:
        self.written_data: List[List[str]] = []
        
    def write(self, rows: Iterator[List[str]], dest_path: str) -> None:
        self.written_data = list(rows)


class MockSorter(SorterProtocol):
    def sort(
        self,
        rows: Iterator[List[str]],
        key_func: any,
        temp_dir: str
    ) -> Iterator[List[str]]:
        data = list(rows)
        data.sort(key=key_func)
        for row in data:
            yield row


def test_sort_engine_pipeline() -> None:
    # テスト用ダミーデータ: [ID, Name, Role]
    input_data = [
        ["3", "Charlie", "Developer"],
        ["1", "Alice", "Manager"],
        ["2", "Bob", "Developer"],
    ]

    reader = MockReader(input_data)
    writer = MockWriter()
    sorter = MockSorter()

    # Roleが "Developer" の行のみを抽出するフィルタ
    grep_filter = GrepFilter(column_index=2, pattern="Developer")

    # ID（インデックス0）を整数値としてソートする設定
    engine = SortEngine(
        reader=reader,
        sorter=sorter,
        writer=writer,
        filter_chain=[grep_filter]
    )

    # 実行
    engine.execute(
        input_path="dummy_input.csv",
        output_path="dummy_output.csv",
        key_func=lambda row: int(row[0])
    )

    # 期待される結果:
    # 1. 'Manager' である Alice は除外される
    # 2. 'Developer' である Bob(ID:2) と Charlie(ID:3) が残り、ID順にソートされる
    assert len(writer.written_data) == 2
    assert writer.written_data[0] == ["2", "Bob", "Developer"]
    assert writer.written_data[1] == ["3", "Charlie", "Developer"]
