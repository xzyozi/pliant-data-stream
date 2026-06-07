import csv
import os
import sqlite3
import tempfile
import tkinter as tk
from typing import Generator

import pytest

from app import PliantApplication
from windows.main_window import MainWindow


@pytest.fixture
def temp_settings_file() -> Generator[str, None, None]:
    """テスト用の一時的な settings.json ファイルパスを提供するフィクスチャ。"""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    if os.path.exists(path):
        os.remove(path)  # 初期状態では存在しないようにする
    yield path
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
@pytest.fixture(scope="module")
def tk_root() -> Generator[tk.Tk, None, None]:
    """テスト用の Tk インスタンスを提供するフィクスチャ。"""
    root = tk.Tk()
    root.withdraw()  # ウィンドウを表示しない
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def test_app_and_settings_integration(tk_root: tk.Tk, temp_settings_file: str) -> None:
    """アプリケーションと設定・イベントの結合テスト。"""
    # アプリの初期化
    app = PliantApplication(tk_root)
    # テスト用パスに切り替え
    app.settings_manager.settings_path = temp_settings_file
    app.settings_manager.save_settings()

    assert os.path.exists(temp_settings_file)

    # テーマ変更のディスパッチテスト
    # 初期状態はデフォルト（dark）
    assert app.theme_manager.current_theme == "dark"

    # 設定マネージャで値を変更し、通知をトリガーする
    app.settings_manager.set_setting("theme", "light")
    app.settings_manager.notify_listeners()

    # テーマ変更イベントが正しくディスパッチされ、適用されていること
    assert app.theme_manager.current_theme == "light"


def test_gui_sort_pipeline_csv(tk_root: tk.Tk, temp_settings_file: str) -> None:
    """CSV書き出しでのGUI経由ソート処理の結合テスト。"""
    app = PliantApplication(tk_root)
    app.settings_manager.settings_path = temp_settings_file

    main_win = MainWindow(tk_root, app)

    # 一時的な入力CSVの作成
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False, newline="") as f_in:
        writer = csv.writer(f_in)
        writer.writerow(["id", "name", "age"])
        writer.writerow(["2", "Alice", "30"])
        writer.writerow(["1", "Bob", "25"])
        writer.writerow(["3", "Charlie", "35"])
        input_path = f_in.name

    # 一時的な出力CSVのパス
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f_out:
        output_path = f_out.name
    os.remove(output_path)  # テスト時に新規生成させるため一度削除

    try:
        # GUI変数へパスを設定
        main_win.input_path_var.set(input_path)
        main_win.output_path_var.set(output_path)
        main_win.has_header_var.set(True)
        main_win.output_format_var.set("CSV")

        # ソートキーをGUIに追加 (age 列を数値で降順にソートする)
        main_win.keys_tree.insert("", tk.END, values=("age", "int", "降順"))

        # GUIスレッドで実行する _execute_sort を同期的に呼び出す
        main_win._execute_sort(input_path, output_path)

        # 結果の検証
        assert os.path.exists(output_path)
        with open(output_path, "r", encoding="utf-8") as f:
            reader = list(csv.reader(f))
            # ヘッダーが維持され、年齢の降順（Charlie 35 -> Alice 30 -> Bob 25）になっていること
            assert reader[0] == ["id", "name", "age"]
            assert reader[1] == ["3", "Charlie", "35"]
            assert reader[2] == ["2", "Alice", "30"]
            assert reader[3] == ["1", "Bob", "25"]

    finally:
        # 後片付け
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(output_path):
            os.remove(output_path)


def test_gui_sort_pipeline_sqlite(tk_root: tk.Tk, temp_settings_file: str) -> None:
    """SQLite書き出しでのGUI経由ソート処理の結合テスト。"""
    app = PliantApplication(tk_root)
    app.settings_manager.settings_path = temp_settings_file

    main_win = MainWindow(tk_root, app)

    # 一時的な入力CSVの作成
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False, newline="") as f_in:
        writer = csv.writer(f_in)
        writer.writerow(["id", "name", "score"])
        writer.writerow(["10", "X", "95.5"])
        writer.writerow(["20", "Y", "88.0"])
        writer.writerow(["30", "Z", "99.1"])
        input_path = f_in.name

    # 一時的なSQLite DBのパス
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f_out:
        output_path = f_out.name
    os.remove(output_path)

    try:
        # GUI変数設定
        main_win.input_path_var.set(input_path)
        main_win.output_path_var.set(output_path)
        main_win.has_header_var.set(True)
        main_win.output_format_var.set("SQLite")
        main_win.sqlite_table_name_var.set("scores")

        # ソートキー設定 (score 列を float で昇順にソートする)
        main_win.keys_tree.insert("", tk.END, values=("score", "float", "昇順"))

        # 実行
        main_win._execute_sort(input_path, output_path)

        # DBの検証
        assert os.path.exists(output_path)
        conn = sqlite3.connect(output_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, score FROM scores")
        rows = cursor.fetchall()
        conn.close()

        # スコアの昇順（Y 88.0 -> X 95.5 -> Z 99.1）になっていること
        assert len(rows) == 3
        assert rows[0] == (20, "Y", 88.0)
        assert rows[1] == (10, "X", 95.5)
        assert rows[2] == (30, "Z", 99.1)

    finally:
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(output_path):
            os.remove(output_path)
