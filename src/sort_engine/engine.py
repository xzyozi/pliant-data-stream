from collections.abc import Callable, Iterator
import os
from typing import Any

from .interface import FilterProtocol, ReaderProtocol, SorterProtocol, WriterProtocol


class SortEngine:
    """依存関係注入（DI）により各処理層を結合し、パイプラインを実行するソートエンジン"""

    def __init__(
        self,
        reader: ReaderProtocol,
        sorter: SorterProtocol,
        writer: WriterProtocol,
        filter_chain: list[FilterProtocol] | None = None,
    ) -> None:
        """
        Args:
            reader: データ読み込み用パーサ
            sorter: ソートアルゴリズム実装
            writer: データ書き出し・永続化実装
            filter_chain: 適用するフィルタのリスト（順序依存）
        """
        self.reader = reader
        self.sorter = sorter
        self.writer = writer
        self.filter_chain = filter_chain if filter_chain is not None else []

    def execute(
        self, input_path: str, output_path: str, key_func: Callable[[list[Any]], Any], temp_dir: str | None = None
    ) -> None:
        """パイプライン処理を実行します。

        Args:
            input_path: 入力ファイルのパス
            output_path: 出力ファイルのパス（またはDBの接続文字列等）
            key_func: 各行（list[Any]）に対するソートキー評価関数
            temp_dir: 一時ディレクトリのパス（未指定時はシステムデフォルト）
        """
        # 1. リーダーによる読み込み
        rows_stream = self.reader.read(input_path)

        # 2. フィルタチェーンの順次適用
        for filter_obj in self.filter_chain:
            rows_stream = filter_obj.filter(rows_stream)

        # 一時ディレクトリの解決
        if temp_dir is None:
            temp_dir = os.path.dirname(output_path) if output_path else ""
            if not temp_dir:
                temp_dir = "."

        # 3. ソート処理の実行
        sorted_stream = self.sorter.sort(rows_stream, key_func, temp_dir)

        # 4. イテレータ消費開始後にヘッダーを復元するための遅延評価ジェネレータを定義
        def _header_restoration_stream() -> Iterator[list[Any]]:
            for row in sorted_stream:
                header = getattr(self.reader, "header", None)
                if header is not None:
                    yield header
                    # 二重に出力しないようクリア
                    setattr(self.reader, "header", None)
                yield row

        final_stream = _header_restoration_stream()

        # 5. ライターによる書き出し
        self.writer.write(final_stream, output_path)
