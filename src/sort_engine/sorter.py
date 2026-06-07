import atexit
from collections.abc import Callable, Iterator
import heapq
import importlib.util
import os
import pickle
import sys
import tempfile
import threading
from typing import Any
import uuid

from .interface import SorterProtocol

# 作成された一時ファイルを追跡し、強制終了時に確実に削除するためのグローバルセットとロック
_created_temp_files: set[str] = set()
_created_temp_files_lock = threading.Lock()


def _cleanup_all_temp_files() -> None:
    """プロセス終了時に未削除の一時ファイルを確実に削除する atexit フック"""
    with _created_temp_files_lock:
        targets = list(_created_temp_files)
        _created_temp_files.clear()

    for file_path in targets:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError:
            pass


atexit.register(_cleanup_all_temp_files)


class SafeComparableKey:
    """異なる型や None が混在するソートスコア同士を安全に比較するためのラッパークラス"""

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, SafeComparableKey):
            return NotImplemented
        v1, v2 = self.value, other.value

        # 両方 None
        if v1 is None and v2 is None:
            return False
        # 片方 None (None を最小値として扱うフォールバック)
        if v1 is None:
            return True
        if v2 is None:
            return False

        # 通常の比較
        try:
            return v1 < v2
        except TypeError:
            # 型が異なり比較できない場合は、型名で比較。同じ型名なら文字列表現で比較
            t1, t2 = type(v1).__name__, type(v2).__name__
            if t1 != t2:
                return t1 < t2
            return str(v1) < str(v2)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, SafeComparableKey):
            return NotImplemented
        return self.value == other.value


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

    # ユニークなモジュール名にするため、UUIDを付与して衝突を回避
    unique_id = uuid.uuid4().hex
    module_name = f"_custom_key_{unique_id}"

    try:
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"スクリプトモジュールの仕様ロードに失敗しました: {script_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as e:
        raise ImportError(f"モジュール '{module_name}' のロード中にエラーが発生しました: {e}") from e
    finally:
        # sys.modules の汚染を防ぐため、即座にクリーンアップ
        sys.modules.pop(module_name, None)

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
        self._local_temp_files: set[str] = set()
        self._lock = threading.Lock()

    def _register_temp_file(self, file_path: str) -> None:
        with self._lock:
            self._local_temp_files.add(file_path)
        with _created_temp_files_lock:
            _created_temp_files.add(file_path)

    def _discard_temp_file(self, file_path: str) -> None:
        with self._lock:
            self._local_temp_files.discard(file_path)
        with _created_temp_files_lock:
            _created_temp_files.discard(file_path)

    def _cleanup_local_files(self) -> None:
        with self._lock:
            targets = list(self._local_temp_files)
            self._local_temp_files.clear()

        for tf in targets:
            try:
                if os.path.exists(tf):
                    os.remove(tf)
            except OSError:
                pass
            with _created_temp_files_lock:
                _created_temp_files.discard(tf)

    def _create_secure_temp_file(self, temp_dir: str) -> str:
        """所有者のみアクセス権(0o600)を持った安全な一時ファイルを作成し、パスを返します。"""
        # 一時ファイルパスの取得
        temp_file = tempfile.NamedTemporaryFile(dir=temp_dir, suffix=".pkl", delete=False)
        temp_file.close()

        # パーミッション 0o600 で開き直すことで、他者からの覗き見や差し替えを防止
        try:
            if os.path.exists(temp_file.name):
                os.remove(temp_file.name)
            # バイナリ書き込みかつ所有者制限
            o_binary = getattr(os, "O_BINARY", 0)
            fd = os.open(temp_file.name, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | o_binary, 0o600)
            os.close(fd)
        except OSError:
            pass

        self._register_temp_file(temp_file.name)
        return temp_file.name

    def _spill_buffer_to_file(self, buffer: list[tuple[SafeComparableKey, int, list[Any]]], temp_dir: str) -> str:
        """オンメモリバッファの内容を一時ファイルへシリアライズして退避します。"""
        file_path = self._create_secure_temp_file(temp_dir)
        with open(file_path, "wb") as f:
            pickle.dump(buffer, f)
        return file_path

    def _spill_stream_to_file(self, stream: Iterator[tuple[SafeComparableKey, int, list[Any]]], temp_dir: str) -> str:
        """マージストリームの内容を一時ファイルへ順次退避します。"""
        file_path = self._create_secure_temp_file(temp_dir)
        buf: list[tuple[SafeComparableKey, int, list[Any]]] = []
        with open(file_path, "wb") as f:
            for item in stream:
                buf.append(item)
                if len(buf) >= self.chunk_size:
                    pickle.dump(buf, f)
                    buf.clear()
            if buf:
                pickle.dump(buf, f)
        return file_path

    def _read_temp_file(self, file_path: str) -> Iterator[tuple[SafeComparableKey, int, list[Any]]]:
        """一時ファイルからデータを順次読み込み、完了時に自動的にファイルを削除します。"""
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
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except OSError:
                pass
            self._discard_temp_file(file_path)

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
        buffer: list[tuple[SafeComparableKey, int, list[Any]]] = []
        seq = 0

        try:
            # 1. シュワルツ変換の適用とSpill (一時ファイルへの退避)
            # 読み込み時に一度だけ key_func を適用して (SafeComparableKey(score), seq, row) に変換
            for row in rows:
                score = key_func(row)
                buffer.append((SafeComparableKey(score), seq, row))
                seq += 1
                if len(buffer) >= self.chunk_size:
                    buffer.sort(key=lambda x: x[0])
                    tf = self._spill_buffer_to_file(buffer, temp_dir)
                    temp_files.append(tf)
                    buffer.clear()

            # 残ったバッファをソートして退避
            if buffer:
                buffer.sort(key=lambda x: x[0])
                tf = self._spill_buffer_to_file(buffer, temp_dir)
                temp_files.append(tf)
                buffer.clear()

            if not temp_files:
                return

            # 2. 多段マージ (Cascading Merge)
            # 一時ファイル数が max_open_files を超えている間、段階的にマージして中間ファイルを生成
            while len(temp_files) > self.max_open_files:
                merge_batch = temp_files[: self.max_open_files]
                temp_files = temp_files[self.max_open_files :]

                # 部分的なマージストリームを作成
                batch_streams = [self._read_temp_file(tf) for tf in merge_batch]
                # (score, seq) を比較してタイブレークおよび型混在エラーを防止
                merged_batch = heapq.merge(*batch_streams, key=lambda x: (x[0], x[1]))

                # 新しい中間一時ファイルにマージストリームを書き出す
                new_temp_file = self._spill_stream_to_file(merged_batch, temp_dir)
                temp_files.append(new_temp_file)

            # 3. 最終マージと出力 (シュワルツ変換の解除)
            final_streams = [self._read_temp_file(tf) for tf in temp_files]
            for _, _, row in heapq.merge(*final_streams, key=lambda x: (x[0], x[1])):
                yield row

        except Exception:
            # エラー発生時の確実なクリーンアップ処理（元の例外はそのまま再送出）
            self._cleanup_local_files()
            raise
