import csv
import json
import os
import sqlite3
import tempfile
import tkinter as tk
from tkinter import ttk
from typing import Any, Generator

import pytest

from app import PliantApplication
from core.bootstrap.base_application import ApplicationState
from custom_widgets import CustomEntry
from windows.main_window import MainWindow
from windows.settings_window import SettingsWindow


@pytest.fixture
def temp_settings_file() -> Generator[str, None, None]:
    """テスト用の一時的な settings.json ファイルパスを提供するフィクスチャ。"""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    if os.path.exists(path):
        os.remove(path)
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
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


# =================================================================----------
# 1. 設定管理機能とUIの連携（SettingsManager ↔ SettingsWindow）
# =================================================================----------

def test_1_1_settings_ui_initial_binding(tk_root: tk.Tk, temp_settings_file: str) -> None:
    """初期値のUIバインディング検証"""
    app = PliantApplication(tk_root)
    app.settings_manager.settings_path = temp_settings_file
    app.settings_manager.set_setting("theme", "dark")
    app.settings_manager.set_setting("language", "ja")
    app.settings_manager.save_settings()

    settings_win = SettingsWindow(tk_root, app, app.settings_manager)
    try:
        # UIの変数が初期値と合致しているか
        assert settings_win._vars["theme"].get() == "dark"
        assert settings_win._vars["language"].get() == "ja"
    finally:
        settings_win.destroy()


def test_1_2_settings_apply_updates_state(tk_root: tk.Tk, temp_settings_file: str) -> None:
    """Apply（適用）による状態更新"""
    app = PliantApplication(tk_root)
    app.settings_manager.settings_path = temp_settings_file
    app.settings_manager.set_setting("language", "en")
    app.settings_manager.save_settings()

    settings_win = SettingsWindow(tk_root, app, app.settings_manager)
    try:
        # 変数を変更
        settings_win._vars["language"].set("ja")

        # イベント発火の検知用
        notified = False

        def on_changed(*args: Any) -> None:
            nonlocal notified
            notified = True

        app.event_dispatcher.subscribe("LANGUAGE_CHANGED", on_changed)

        # Applyボタンの押下をシミュレート
        settings_win._apply_only()

        # 設定が更新され、イベントが発行され、ウィンドウは閉じないこと
        assert app.settings_manager.get_setting("language") == "ja"
        assert notified is True
        assert settings_win.winfo_exists()
    finally:
        settings_win.destroy()


def test_1_3_settings_save_persistence(tk_root: tk.Tk, temp_settings_file: str) -> None:
    """Save（保存）による永続化連携"""
    app = PliantApplication(tk_root)
    app.settings_manager.settings_path = temp_settings_file
    app.settings_manager.set_setting("default_chunk_size", 50000)
    app.settings_manager.save_settings()

    settings_win = SettingsWindow(tk_root, app, app.settings_manager)
    settings_win._vars["default_chunk_size"].set(100000)

    # Saveボタンの押下をシミュレート
    settings_win._save_and_close()

    # 永続化ファイルが更新されていること
    with open(temp_settings_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["default_chunk_size"] == 100000


def test_1_4_settings_cancel_rollback(tk_root: tk.Tk, temp_settings_file: str) -> None:
    """Cancel（破棄）によるロールバック"""
    app = PliantApplication(tk_root)
    app.settings_manager.settings_path = temp_settings_file
    app.settings_manager.set_setting("theme", "dark")
    app.settings_manager.save_settings()

    settings_win = SettingsWindow(tk_root, app, app.settings_manager)
    settings_win._vars["theme"].set("light")

    # Cancel（ウィンドウ破棄）
    settings_win.destroy()

    # 値が保存されずにロールバックされていること
    assert app.settings_manager.get_setting("theme") == "dark"


def test_1_5_settings_import_sync(tk_root: tk.Tk, temp_settings_file: str) -> None:
    """Import（設定取り込み）とUI同期"""
    app = PliantApplication(tk_root)
    app.settings_manager.settings_path = temp_settings_file
    app.settings_manager.save_settings()

    settings_win = SettingsWindow(tk_root, app, app.settings_manager)
    try:
        # インポート用の一時ファイルを作成
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False, encoding="utf-8") as tmp:
            json.dump({"theme": "light", "language": "en"}, tmp)
            tmp_path = tmp.name

        try:
            # 設定ファイルから読み込む
            app.settings_manager.load_settings_from_file(tmp_path)
            # UI側の更新処理を呼び出す
            settings_win._update_ui_from_settings()

            # UIの変数が同期されていること
            assert settings_win._vars["theme"].get() == "light"
            assert settings_win._vars["language"].get() == "en"
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    finally:
        settings_win.destroy()


# =================================================================----------
# 2. イベント駆動とUIコンポーネントの連携（EventDispatcher ↔ Widgets）
# =================================================================----------

def test_2_1_language_changed_menu_rebuild(tk_root: tk.Tk, temp_settings_file: str) -> None:
    """言語変更イベントの受信と再描画"""
    app = PliantApplication(tk_root)
    app.settings_manager.settings_path = temp_settings_file

    # CustomEntry の配置
    entry = CustomEntry(tk_root, app=app)
    try:
        # 初期言語設定を ja に
        app.settings_manager.set_setting("language", "ja")
        entry._rebuild_menu()
        # メニューの「コピー」のラベルを確認
        assert entry.context_menu.entrycget(1, "label") == "コピー"

        # 言語を en に切り替えてイベント発行
        app.settings_manager.set_setting("language", "en")
        app.event_dispatcher.dispatch("LANGUAGE_CHANGED", "en")

        # 英語表記に切り替わっていること
        assert entry.context_menu.entrycget(1, "label") == "Copy"
    finally:
        entry.destroy()


def test_2_2_widget_destroy_unsubscribes(tk_root: tk.Tk, temp_settings_file: str) -> None:
    """ウィジェット破棄時の購読解除（メモリリーク防止）"""
    app = PliantApplication(tk_root)
    app.settings_manager.settings_path = temp_settings_file

    entry = CustomEntry(tk_root, app=app)
    # 購読リストにあることを確認
    listeners = app.event_dispatcher._listeners["LANGUAGE_CHANGED"]
    assert entry._rebuild_menu in listeners

    # ウィジェット破棄
    entry.destroy()
    # Tclのイベントループを進める
    tk_root.update_idletasks()

    # 購読解除されていること
    assert entry._rebuild_menu not in listeners


def test_2_3_event_dispatch_continues_on_exception(tk_root: tk.Tk) -> None:
    """例外発生時のイベントディスパッチ継続"""
    app = PliantApplication(tk_root)

    called_success = False

    def error_listener(*args: Any) -> None:
        raise ValueError("Intentional error for test")

    def success_listener(*args: Any) -> None:
        nonlocal called_success
        called_success = True

    # リスナー登録（エラーを起こすものを先にする）
    app.event_dispatcher.subscribe("TEST_EVENT", error_listener)
    app.event_dispatcher.subscribe("TEST_EVENT", success_listener)

    # 実行してもクラッシュせず、後続のリスナーが呼ばれること
    app.event_dispatcher.dispatch("TEST_EVENT")
    assert called_success is True


# =================================================================----------
# 3. テーマ管理と動的スタイリングの連携（ThemeManager ↔ Toplevel/Widgets）
# =================================================================----------

def test_3_1_global_theme_apply(tk_root: tk.Tk) -> None:
    """グローバルテーマの適用"""
    app = PliantApplication(tk_root)
    style = ttk.Style(tk_root)

    # darkテーマ適用
    app.theme_manager.apply_theme("dark")
    bg_dark = style.lookup("TFrame", "background")

    # lightテーマ適用
    app.theme_manager.apply_theme("light")
    bg_light = style.lookup("TFrame", "background")

    # それぞれ異なるスタイルになっていること
    assert bg_dark != bg_light


def test_3_2_recursive_theme_widget_tree(tk_root: tk.Tk) -> None:
    """標準ウィジェットへの再帰的適用"""
    app = PliantApplication(tk_root)
    frame = tk.Frame(tk_root)
    text_widget = tk.Text(frame)
    text_widget.pack()
    frame.pack()

    # darkテーマ適用
    app.theme_manager.apply_theme("dark")
    bg_dark = text_widget.cget("bg")

    # lightテーマ適用
    app.theme_manager.apply_theme("light")
    bg_light = text_widget.cget("bg")

    assert bg_dark != bg_light
    frame.destroy()


def test_3_3_menu_theme_apply(tk_root: tk.Tk) -> None:
    """メニューバーへのテーマ適用"""
    app = PliantApplication(tk_root)
    menubar = tk.Menu(tk_root)
    submenu = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="Test Cascade", menu=submenu)
    app.theme_manager.set_menubar(menubar)

    # テーマを適用してエラーが起きないことを確認
    app.theme_manager.apply_theme("dark")
    app.theme_manager.apply_theme("light")


# =================================================================----------
# 4. アプリケーションライフサイクルの連携（BaseApplication ↔ 状態リスナー）
# =================================================================----------

def test_4_1_state_change_listener_notification(tk_root: tk.Tk) -> None:
    """状態遷移のリスナー通知"""
    app = PliantApplication(tk_root)
    notified_state = None

    def listener(state: ApplicationState) -> None:
        nonlocal notified_state
        notified_state = state

    app.subscribe_to_state(listener)
    app._set_state(ApplicationState.RUNNING)

    assert notified_state == ApplicationState.RUNNING


def test_4_2_state_change_notification_skips_on_duplicate(tk_root: tk.Tk) -> None:
    """重複状態の通知スキップ"""
    app = PliantApplication(tk_root)
    app._set_state(ApplicationState.RUNNING)

    notified_count = 0

    def listener(state: ApplicationState) -> None:
        nonlocal notified_count
        notified_count += 1

    app.subscribe_to_state(listener)

    # 同じ状態に遷移しても通知されないこと
    app._set_state(ApplicationState.RUNNING)
    assert notified_count == 0

    # 別の状態に遷移した場合は通知されること
    app._set_state(ApplicationState.SHUTTING_DOWN)
    assert notified_count == 1


# =================================================================----------
# 5. 既存ソート実行パイプラインの結合テスト
# =================================================================----------

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
