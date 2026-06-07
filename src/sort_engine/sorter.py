from collections.abc import Callable, Iterator
import heapq
import importlib.util
import os
import pickle
import sys
import tempfile
from typing import Any

from .interface import SorterProtocol


def load_custom_key_func(script_path: str, function_name: str) -> Callable[[list[Any]], Any]:
    """外部の Python スクリプトから指定されたソートキー評価関数を動的にロードします。

    Args:
        script_path: インポート対象の Python ファイルの絶対パスまたは相対パス。
        function_name: ロード対象の関数名。

    Returns:
        Callable[[list[Any]], Any]: ロードされた関数オブジェクト。

    Raises:
        FileNotFoundError: スクリプトファイルが存在しない場合。
        ImportError: モジュールのインポートに失敗した場合。
        AttributeError: 指定された関数がモジュール内に存在しない場合。
        TypeError: ロードされたオブジェクトが関数（呼び出し可能オブジェクト）でない場合。
    """
    if not os.path.exists(script_path):
        raise FileNotFoundError(f"カスタムスクリプトファイルが見つかりません: {script_path}")

    # モジュール名としてスクリプトのファイル名（拡張子なし）を使用
    module_name = os.path.splitext(os.path.basename(script_path))[0]

    try:
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"スクリプトモジュールの仕様ロードに失敗しました: {script_path}")

        module = importlib.util.module_from_spec(spec)
        # 依存関係解決などのために sys.modules に登録
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as e:
        raise ImportError(f"モジュール '{module_name}' のロード中にエラーが発生しました: {e}") from e

    func = getattr(module, function_name, None)
    if func is None:
        raise AttributeError(f"関数 '{function_name}' がスクリプト '{script_path}' 内に見つかりません。")

    if not callable(func):
        raise TypeError(f"'{function_name}' は呼び出し可能なオブジェクト（関数）ではありません。")

    return func


class ExternalMergeSorter(SorterProtocol):
    """大容量データ用の外部マージソート（External Merge Sort）を実行するクラス"""

    def __init__(self, chunk_size: int = 100000) -> None:
        """
        Args:
            chunk_size: メモリに保持する最大行数。これを超えるたびに一時ファイルへ書き出します。
        """
        self.chunk_size = chunk_size

    def sort(
        self, rows: Iterator[list[Any]], key_func: Callable[[list[Any]], Any], temp_dir: str
    ) -> Iterator[list[Any]]:
        """行データを外部マージソートしたイテレータを返します。

        各チャンクは ``chunk_size`` に達するごとにソートされ、一時ファイルに pickle 形式で
        退避（Spill）されます。最終出力時に ``heapq.merge`` を用いてマージソートが実行されます。

        Args:
            rows: ソート対象データのイテレータ。
            key_func: ソート用のキーを返す評価関数。
            temp_dir: 一時ファイルを配置するディレクトリ。

        Yields:
            list[Any]: ソート済みの行データ。
        """
        temp_files: list[str] = []
        buffer: list[list[Any]] = []

        try:
            # 1. チャンク分割と一時ファイルへの退避 (Spilling)
            for row in rows:
                buffer.append(row)
                if len(buffer) >= self.chunk_size:
                    buffer.sort(key=key_func)
                    # delete=False で作成し、手動で削除管理を行う
                    temp_file = tempfile.NamedTemporaryFile(dir=temp_dir, suffix=".pkl", delete=False)
                    temp_file.close()
                    with open(temp_file.name, "wb") as f:
                        pickle.dump(buffer, f)
                    temp_files.append(temp_file.name)
                    buffer.clear()

            # 残ったバッファをソートして退避
            if buffer:
                buffer.sort(key=key_func)
                temp_file = tempfile.NamedTemporaryFile(dir=temp_dir, suffix=".pkl", delete=False)
                temp_file.close()
                with open(temp_file.name, "wb") as f:
                    pickle.dump(buffer, f)
                temp_files.append(temp_file.name)
                buffer.clear()

            if not temp_files:
                return

            # 2. 一時ファイルからデータを読み込み、自動的にファイルを削除するジェネレータ定義
            def _read_temp_file(file_path: str) -> Iterator[list[Any]]:
                try:
                    with open(file_path, "rb") as f:
                        chunk = pickle.load(f)
                    for r in chunk:
                        yield r
                finally:
                    # 読み込み完了時、またはエラー発生時に一時ファイルを確実に削除
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    except OSError:
                        pass

            # 3. heapq.merge による K-way マージソート
            streams = [_read_temp_file(tf) for tf in temp_files]
            yield from heapq.merge(*streams, key=key_func)

        except Exception:
            # エラー発生時のクリーンアップ処理
            for tf in temp_files:
                try:
                    if os.path.exists(tf):
                        os.remove(tf)
                except OSError:
                    pass
            raise
