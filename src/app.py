import logging
import tkinter as tk
from collections.abc import Callable
from typing import Any

from core.bootstrap.base_application import BaseApplication, ApplicationState
from core.config.app_settings_manager import AppSettingsManager
from core.events.event_dispatcher import EventDispatcher
from theme_manager import ThemeManager
from windows.settings_window import SettingsWindow

logger = logging.getLogger(__name__)

# 簡易的な多言語翻訳辞書
TRANSLATIONS = {
    "ja": {
        "cut": "切り取り",
        "copy": "コピー",
        "paste": "貼り付け",
        "select_all": "すべて選択",
        "settings": "設定",
        "error": "エラー",
        "success": "成功",
    },
    "en": {
        "cut": "Cut",
        "copy": "Copy",
        "paste": "Paste",
        "select_all": "Select All",
        "settings": "Settings",
        "error": "Error",
        "success": "Success",
    }
}


class PliantApplication(BaseApplication):
    """Pliant Data Stream 用の Tkinter アプリケーション。"""

    def __init__(self, root: tk.Tk) -> None:
        super().__init__()
        self.root = root

        # 1. コアオブジェクトの初期化
        self._event_dispatcher = EventDispatcher()
        self._settings_manager = AppSettingsManager(event_dispatcher=self._event_dispatcher)
        self._theme_manager = ThemeManager(self.root)

        # 2. イベント購読
        self._event_dispatcher.subscribe("THEME_CHANGED", self._on_theme_changed)
        self._event_dispatcher.subscribe("LANGUAGE_CHANGED", self._on_language_changed)

        # 3. 初期設定の適用
        current_theme = self._settings_manager.get_setting("theme", "dark")
        self._theme_manager.apply_theme(current_theme)

        self._set_state(ApplicationState.READY)

    @property
    def translator(self) -> Callable[[str], str]:
        """多言語対応用の翻訳関数を返します。"""
        def translate(key: str) -> str:
            lang = self._settings_manager.get_setting("language", "ja")
            lang_dict = TRANSLATIONS.get(lang, TRANSLATIONS["ja"])
            return lang_dict.get(key, key)
        return translate

    @property
    def event_dispatcher(self) -> EventDispatcher:
        """イベントディスパッチャを取得します。"""
        return self._event_dispatcher

    @property
    def settings_manager(self) -> AppSettingsManager:
        """設定マネージャを取得します。"""
        return self._settings_manager

    @property
    def theme_manager(self) -> ThemeManager:
        """テーママネージャを取得します。"""
        return self._theme_manager

    def open_settings_window(self) -> None:
        """スキーマ駆動設定ウィンドウを表示します。"""
        settings_win = SettingsWindow(self.root, self, self._settings_manager)
        # 設定ウィンドウを表示した時、現在のテーマを再適用する
        self._theme_manager.apply_theme_to_toplevel(settings_win)
        settings_win.grab_set()  # モーダルとして表示

    def _on_theme_changed(self, theme_name: str) -> None:
        """テーマ変更イベント時の処理。"""
        self._theme_manager.apply_theme(theme_name)

    def _on_language_changed(self, lang_name: str) -> None:
        """言語変更イベント時の処理。"""
        # 必要に応じてウィンドウのテキストを更新するイベントを発行する
        pass

    def on_ready(self) -> None:
        """アプリケーションがReady状態になったときの処理。"""
        self._set_state(ApplicationState.RUNNING)
        logger.info("Application is running.")

    def on_closing(self) -> None:
        """メインウィンドウが閉じられる時の処理。"""
        self.shutdown()

    def shutdown(self) -> None:
        """終了時のクリーンアップ処理を行います。"""
        self._set_state(ApplicationState.SHUTTING_DOWN)
        logger.info("Application is shutting down.")
        self._settings_manager.save_settings()
        self._set_state(ApplicationState.CLOSED)
        self.root.destroy()
