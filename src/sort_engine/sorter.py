import atexit
from collections.abc import Callable, Iterator
import heapq
import importlib.util
import os
import pickle
import sys
import tempfile
from typing import Any

from .interface import SorterProtocol

# 作成された一時ファイルを追跡し、強制終了時に確実に削除するためのグローバルセット
_created_temp_files: set[str] = set()


def _cleanup_all_temp_files() -> None:
    """プロセス終了時に未削除の一時ファイルを確実に削除する atexit フック"""
    for file_path in list(_created_temp_files):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError:
            pass
    _created_temp_files.clear()


atexit.register(_cleanup_all_temp_files)


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

    def __init__(self, chunk_size: int = 100000, max_open_files: int = 200) -> None:
        """
        Args:
            chunk_size: メモリに保持する最大行数。これを超えるたびに一時ファイルへ書き出します。
            max_open_files: 同時にオープンを許可する最大一時ファイル数（ディスクリプタ上限回避用）。
        """
        self.chunk_size = chunk_size
        self.max_open_files = max_open_files

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
        buffer: list[tuple[Any, list[Any]]] = []

        # 2. 一時ファイルからデータを読み込み、自動的にファイルを削除するジェネレータ定義
        # 多段マージで複数回 append (dump) されたファイルに対応するため、EOFまでループロードする
        def _read_temp_file(file_path: str) -> Iterator[tuple[Any, list[Any]]]:
            try:
                with open(file_path, "rb") as f:
                    while True:
                        try:
                            chunk = pickle.load(f)
                            for item in chunk:
                                yield item
                        except EOFError:
                            break
            finally:
                # 読み込み完了時、またはエラー発生時に一時ファイルを確実に削除
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except OSError:
                    pass
                _created_temp_files.discard(file_path)

        # マージ中の中間結果ストリームを一時ファイルに Spill するヘルパー
        def _spill_stream_to_file(stream: Iterator[tuple[Any, list[Any]]]) -> str:
            temp_file = tempfile.NamedTemporaryFile(dir=temp_dir, suffix=".pkl", delete=False)
            temp_file.close()
            _created_temp_files.add(temp_file.name)

            buf: list[tuple[Any, list[Any]]] = []
            with open(temp_file.name, "wb") as f:
                for item in stream:
                    buf.append(item)
                    if len(buf) >= self.chunk_size:
                        pickle.dump(buf, f)
                        buf.clear()
                if buf:
                    pickle.dump(buf, f)
            return temp_file.name

        try:
            # 1. シュワルツ変換の適用とSpill (一時ファイルへの退避)
            # 読み込み時に一度だけ key_func を適用して (score, row) に変換
            for row in rows:
                score = key_func(row)
                buffer.append((score, row))
                if len(buffer) >= self.chunk_size:
                    buffer.sort(key=lambda x: x[0])
                    temp_file = tempfile.NamedTemporaryFile(dir=temp_dir, suffix=".pkl", delete=False)
                    temp_file.close()
                    _created_temp_files.add(temp_file.name)
                    with open(temp_file.name, "wb") as f:
                        pickle.dump(buffer, f)
                    temp_files.append(temp_file.name)
                    buffer.clear()

            # 残ったバッファをソートして退避
            if buffer:
                buffer.sort(key=lambda x: x[0])
                temp_file = tempfile.NamedTemporaryFile(dir=temp_dir, suffix=".pkl", delete=False)
                temp_file.close()
                _created_temp_files.add(temp_file.name)
                with open(temp_file.name, "wb") as f:
                    pickle.dump(buffer, f)
                temp_files.append(temp_file.name)
                buffer.clear()

            if not temp_files:
                return

            # 2. 多段マージ (Cascading Merge)
            # 一時ファイル数が max_open_files を超えている間、段階的にマージして中間ファイルを生成
            while len(temp_files) > self.max_open_files:
                merge_batch = temp_files[: self.max_open_files]
                temp_files = temp_files[self.max_open_files :]

                # 部分的なマージストリームを作成
                batch_streams = [_read_temp_file(tf) for tf in merge_batch]
                merged_batch = heapq.merge(*batch_streams, key=lambda x: x[0])

                # 新しい中間一時ファイルにマージストリームを書き出す
                new_temp_file = _spill_stream_to_file(merged_batch)
                temp_files.append(new_temp_file)

            # 3. 最終マージと出力 (シュワルツ変換の解除)
            final_streams = [_read_temp_file(tf) for tf in temp_files]
            for _, row in heapq.merge(*final_streams, key=lambda x: x[0]):
                yield row

        except Exception:
            # エラー発生時の確実なクリーンアップ処理
            for tf in list(temp_files):
                try:
                    if os.path.exists(tf):
                        os.remove(tf)
                except OSError:
                    pass
                _created_temp_files.discard(tf)
            raise
