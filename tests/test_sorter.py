import os
import tempfile
import tracemalloc
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any
import pytest
from sort_engine import ExternalMergeSorter
from sort_engine.sorter import load_custom_key_func


def test_external_merge_sorter_in_memory() -> None:
    """chunk_size に達しない小規模データのソート検証"""
    data = [
        [3, "Charlie"],
        [1, "Alice"],
        [2, "Bob"],
    ]

    sorter = ExternalMergeSorter(chunk_size=10)
    with tempfile.TemporaryDirectory() as temp_dir:
        result = list(sorter.sort(iter(data), key_func=lambda x: x[0], temp_dir=temp_dir))

    assert len(result) == 3
    assert result[0] == [1, "Alice"]
    assert result[1] == [2, "Bob"]
    assert result[2] == [3, "Charlie"]


def test_external_merge_sorter_spilling() -> None:
    """chunk_size を超えるデータを一時ファイルに退避（Spill）させてマージする動作の検証"""
    # チャンクサイズ 2 に対し 5 件のデータ
    data = [
        [5, "Eve"],
        [3, "Charlie"],
        [1, "Alice"],
        [4, "David"],
        [2, "Bob"],
    ]

    sorter = ExternalMergeSorter(chunk_size=2)
    with tempfile.TemporaryDirectory() as temp_dir:
        result = list(sorter.sort(iter(data), key_func=lambda x: x[0], temp_dir=temp_dir))

        # ソート中に生成された一時ファイルがすべて削除されているかを検証するため、
        # ディレクトリ内が空であることを確認します
        remaining_files = os.listdir(temp_dir)
        assert len(remaining_files) == 0

    assert len(result) == 5
    assert result[0] == [1, "Alice"]
    assert result[1] == [2, "Bob"]
    assert result[2] == [3, "Charlie"]
    assert result[3] == [4, "David"]
    assert result[4] == [5, "Eve"]


def test_external_merge_sorter_with_objects() -> None:
    """datetime や date オブジェクトを含むデータのソート検証"""
    data = [
        [datetime(2026, 6, 3), "C"],
        [datetime(2026, 6, 1), "A"],
        [datetime(2026, 6, 2), "B"],
    ]

    sorter = ExternalMergeSorter(chunk_size=2)
    with tempfile.TemporaryDirectory() as temp_dir:
        result = list(sorter.sort(iter(data), key_func=lambda x: x[0], temp_dir=temp_dir))

    assert len(result) == 3
    assert result[0][1] == "A"
    assert result[1][1] == "B"
    assert result[2][1] == "C"


def test_load_custom_key_func_success() -> None:
    """外部スクリプトからキー評価関数を正常に動的ロードできることの検証"""
    script_content = """
def custom_key(row):
    # row[1] の長さをソートキーとする
    return len(row[1])
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as temp_script:
        temp_script.write(script_content)
        script_path = temp_script.name

    try:
        # ロードして検証
        key_func = load_custom_key_func(script_path, "custom_key")
        assert callable(key_func)
        assert key_func([1, "Alice"]) == 5
        assert key_func([2, "Bob"]) == 3

        # 実際にソートへ適用
        data = [
            [1, "Alice"],  # 長さ 5
            [2, "Bob"],    # 長さ 3
            [3, "Zack"],   # 長さ 4
        ]
        sorter = ExternalMergeSorter(chunk_size=2)
        with tempfile.TemporaryDirectory() as temp_dir:
            result = list(sorter.sort(iter(data), key_func=key_func, temp_dir=temp_dir))

        assert result[0] == [2, "Bob"]  # 3
        assert result[1] == [3, "Zack"]  # 4
        assert result[2] == [1, "Alice"]  # 5
    finally:
        if os.path.exists(script_path):
            os.remove(script_path)


def test_load_custom_key_func_errors() -> None:
    """load_custom_key_func の異常系エラーハンドリング検証"""
    # 1. 存在しないスクリプトファイルパス
    with pytest.raises(FileNotFoundError, match="カスタムスクリプトファイルが見つかりません"):
        load_custom_key_func("non_existent_file.py", "some_func")

    # 2. 関数が存在しない場合
    script_content = "def another_func(x): return x"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as temp_script:
        temp_script.write(script_content)
        script_path = temp_script.name

    try:
        with pytest.raises(AttributeError, match="内に見つかりません"):
            load_custom_key_func(script_path, "non_existent_func")

        # 3. 指定したオブジェクトが関数（呼び出し可能オブジェクト）ではない場合
        script_content_var = "custom_var = 123"
        with open(script_path, "w") as f:
            f.write(script_content_var)
        with pytest.raises(TypeError, match="呼び出し可能なオブジェクト.*ではありません"):
            load_custom_key_func(script_path, "custom_var")
    finally:
        if os.path.exists(script_path):
            os.remove(script_path)


def test_external_merge_sorter_cleanup_on_exception() -> None:
    """ソートイテレーションの処理中に例外が発生した場合、生成された一時ファイルがクリーンアップされることの検証"""

    # 意図的にイテレーションの途中で ValueError を投げるジェネレータ
    def broken_rows() -> Iterator[list[int]]:
        yield [1, 2]
        yield [3, 4]
        raise ValueError("意図的なエラー")

    sorter = ExternalMergeSorter(chunk_size=1)
    with tempfile.TemporaryDirectory() as temp_dir:
        # イテレータの実行（消費）で例外が起きる
        with pytest.raises(ValueError, match="意図的なエラー"):
            list(sorter.sort(broken_rows(), key_func=lambda x: x[0], temp_dir=temp_dir))

        # エラー発生後に一時ファイルが削除されていること
        remaining_files = os.listdir(temp_dir)
        assert len(remaining_files) == 0


def test_external_merge_sorter_cascading_merge() -> None:
    """max_open_files 制限を小さくし、多段マージ（Cascading Merge）が正常に機能するかの境界値検証"""
    # チャンクサイズ 2、同時オープンファイル上限 2 に対して 9 件のデータ
    # チャンクは 5 つ生成される（一時ファイル 5 個）
    # 5 > 2 なので、多段マージがトリガーされる
    data = [
        [9, "I"],
        [8, "H"],
        [7, "G"],
        [6, "F"],
        [5, "E"],
        [4, "D"],
        [3, "C"],
        [2, "B"],
        [1, "A"],
    ]

    sorter = ExternalMergeSorter(chunk_size=2, max_open_files=2)
    with tempfile.TemporaryDirectory() as temp_dir:
        result = list(sorter.sort(iter(data), key_func=lambda x: x[0], temp_dir=temp_dir))

        # 一時ファイルが中間ファイルを含めてすべて綺麗に削除されていることを検証
        remaining_files = os.listdir(temp_dir)
        assert len(remaining_files) == 0

    assert len(result) == 9
    assert result[0] == [1, "A"]
    assert result[4] == [5, "E"]
    assert result[8] == [9, "I"]


def test_external_merge_sorter_memory_leak() -> None:
    """巨大データをソートした際、メモリ使用量のピーク値が一定以下に抑えられていることの検証"""
    # 5000 行のデータを chunk_size = 50 でソートする（一時ファイル 100 個）
    # メモリ上には一度に 50 行しか乗らないため、メモリピークは小さく保たれる
    data = [[i % 100, f"data-{i}"] for i in range(5000)]

    tracemalloc.start()
    try:
        sorter = ExternalMergeSorter(chunk_size=50)
        with tempfile.TemporaryDirectory() as temp_dir:
            result = list(sorter.sort(iter(data), key_func=lambda x: x[0], temp_dir=temp_dir))

            assert len(result) == 5000

            # メモリピーク値の取得 (current, peak)
            _, peak = tracemalloc.get_traced_memory()

            # メモリピーク値が 5MB 以下に収まっていることを確認
            assert peak < 5 * 1024 * 1024, f"メモリ使用量のピークが大きすぎます: {peak} bytes"
    finally:
        tracemalloc.stop()
