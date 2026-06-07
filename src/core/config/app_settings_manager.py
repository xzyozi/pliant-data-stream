import json
import logging
import os
from typing import Any

from core.config.schema import SettingField, WidgetType
from core.config.settings_manager import BaseSettingsManager

logger = logging.getLogger(__name__)


class AppSettingsManager(BaseSettingsManager):
    """具象設定マネージャクラス。

    設定の読み込み、保存、スキーマの定義を行います。
    """

    def __init__(self, settings_path: str = "settings.json", event_dispatcher: Any = None) -> None:
        self.settings_path = settings_path
        self.event_dispatcher = event_dispatcher
        self._settings = self._get_default_settings()
        self.load_settings()

    @property
    def settings(self) -> dict[str, Any]:
        """設定辞書を取得します。"""
        return self._settings

    @settings.setter
    def settings(self, val: dict[str, Any]) -> None:
        """設定辞書をセットします。"""
        self._settings = val

    def get_setting(self, key: str, default: Any = None) -> Any:
        """指定したキーの設定値を取得します。"""
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        """指定したキーに設定値をセットします。"""
        self._settings[key] = value

    def save_settings(self) -> None:
        """設定を指定されたファイル（settings.json）に保存します。"""
        self.save_settings_to_file(self.settings_path)

    def load_settings(self) -> None:
        """デフォルトパスから設定を読み込みます。ファイルがない場合は作成します。"""
        if os.path.exists(self.settings_path):
            self.load_settings_from_file(self.settings_path)
        else:
            self.save_settings()

    def load_settings_from_file(self, filepath: str) -> bool:
        """JSONファイルから設定を読み込みます。"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    # デフォルト値をマージして、新しく追加された設定項目もカバーできるようにする
                    self._settings = self._get_default_settings()
                    self._settings.update(loaded)
                    return True
        except Exception as e:
            logger.error(f"Failed to load settings from {filepath}: {e}", exc_info=True)
        return False

    def save_settings_to_file(self, filepath: str) -> None:
        """JSONファイルに設定を保存します。"""
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save settings to {filepath}: {e}", exc_info=True)

    def notify_listeners(self) -> None:
        """設定の変更をイベントディスパッチャ経由で通知します。"""
        if self.event_dispatcher:
            self.event_dispatcher.dispatch("SETTINGS_CHANGED", self._settings)
            # テーマや言語の変更イベントを個別にディスパッチ
            self.event_dispatcher.dispatch("THEME_CHANGED", self._settings.get("theme", "light"))
            self.event_dispatcher.dispatch("LANGUAGE_CHANGED", self._settings.get("language", "ja"))

    def _get_default_settings(self) -> dict[str, Any]:
        """デフォルトの設定値を返します。"""
        return {
            "theme": "dark",
            "language": "ja",
            "default_chunk_size": 50000,
            "sqlite_journal_mode": "WAL",
            "sqlite_synchronous": "NORMAL",
        }

    def get_settings_schema(self) -> list[SettingField]:
        """設定画面で描画されるスキーマ定義を返します。"""
        return [
            SettingField(
                key="theme",
                label="テーマ (Theme)",
                widget_type=WidgetType.OPTION_MENU,
                tab="一般 (General)",
                group="外観設定",
                default="dark",
                choices=["light", "dark"],
            ),
            SettingField(
                key="language",
                label="言語 (Language)",
                widget_type=WidgetType.OPTION_MENU,
                tab="一般 (General)",
                group="多言語設定",
                default="ja",
                choices=["ja", "en"],
            ),
            SettingField(
                key="default_chunk_size",
                label="デフォルトチャンクサイズ",
                widget_type=WidgetType.SPINBOX,
                tab="エンジン (Engine)",
                group="パフォーマンス設定",
                default=50000,
                min_value=1000,
                max_value=1000000,
                increment=5000,
                width=10,
            ),
            SettingField(
                key="sqlite_journal_mode",
                label="SQLiteジャーナルモード",
                widget_type=WidgetType.OPTION_MENU,
                tab="エンジン (Engine)",
                group="データベース設定",
                default="WAL",
                choices=["DELETE", "TRUNCATE", "PERSIST", "MEMORY", "WAL", "OFF"],
            ),
            SettingField(
                key="sqlite_synchronous",
                label="SQLite同期モード",
                widget_type=WidgetType.OPTION_MENU,
                tab="エンジン (Engine)",
                group="データベース設定",
                default="NORMAL",
                choices=["OFF", "NORMAL", "FULL", "EXTRA"],
            ),
        ]
