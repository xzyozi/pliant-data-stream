from abc import ABC, abstractmethod
from typing import Any

from reusable_gui.core.config.schema import SettingField


class BaseSettingsManager(ABC):
    """Abstract Settings Manager for configuring the application."""

    @property
    @abstractmethod
    def settings(self) -> dict[str, Any]:
        """Gets settings dictionary."""
        pass

    @settings.setter
    @abstractmethod
    def settings(self, val: dict[str, Any]) -> None:
        """Sets settings dictionary."""
        pass

    @abstractmethod
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Gets specific setting value by key."""
        pass

    @abstractmethod
    def set_setting(self, key: str, value: Any) -> None:
        """Sets specific setting value by key."""
        pass

    @abstractmethod
    def save_settings(self) -> None:
        """Saves settings to the default storage."""
        pass

    @abstractmethod
    def load_settings_from_file(self, filepath: str) -> bool:
        """Loads settings from a specified JSON file."""
        pass

    @abstractmethod
    def save_settings_to_file(self, filepath: str) -> None:
        """Saves settings to a specified JSON file."""
        pass

    @abstractmethod
    def notify_listeners(self) -> None:
        """Notifies event listeners about the settings change."""
        pass

    @abstractmethod
    def _get_default_settings(self) -> dict[str, Any]:
        """Gets the default dictionary of settings."""
        pass

    @abstractmethod
    def get_settings_schema(self) -> list[SettingField]:
        """設定画面に表示する全項目のスキーマを返す。

        SettingsWindow はこの戻り値のみを使って UI を動的生成する。
        タブ・グループ・ウィジェット種別・初期値などを SettingField で定義すること。
        """
        pass
