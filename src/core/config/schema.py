"""
reusable_gui.core.config.schema
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
設定画面のスキーマ型定義モジュール。

SettingsManager.get_settings_schema() の戻り値型として使用し、
SettingsWindow はこのスキーマを元に UI を動的生成する。
アプリ側でも import して利用する唯一の公開型。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class WidgetType(Enum):
    """設定ウィジェットの種別。"""

    CHECKBUTTON = auto()
    """bool 値: ttk.Checkbutton"""

    SPINBOX = auto()
    """int / float 値: ttk.Spinbox (min_value / max_value / increment が有効)"""

    OPTION_MENU = auto()
    """str 値: ttk.OptionMenu (choices が必須)"""

    FONT_PICKER = auto()
    """str 値: システムフォント一覧から選ぶ OptionMenu。choices は自動補完。"""

    LISTBOX_EDIT = auto()
    """list[str] 値: Listbox + Add / Remove ボタン付きの編集UI"""

    ENTRY = auto()
    """str 値: ttk.Entry (自由入力)"""


@dataclass
class SettingField:
    """1 つの設定項目の完全な定義。

    Attributes:
        key:         settings dict のキー（`settings_manager.get_setting(key)` に対応）。
        label:       UI に表示するラベル文字列。
        widget_type: 使用するウィジェットの種別（WidgetType）。
        tab:         設定ウィンドウの所属タブ名。
        group:       タブ内の LabelFrame グループ名。空文字列の場合はグループなし。
        default:     設定値が取得できない場合のデフォルト。
        choices:     OPTION_MENU 時の選択肢リスト。FONT_PICKER では自動補完されるため不要。
        min_value:   SPINBOX の最小値。
        max_value:   SPINBOX の最大値。
        increment:   SPINBOX のステップ幅。
        width:       ウィジェットの幅（文字数単位）。
    """

    key: str
    label: str
    widget_type: WidgetType
    tab: str
    group: str = ""
    default: Any = None
    choices: list[Any] = field(default_factory=list)
    min_value: float = 0.0
    max_value: float = 100.0
    increment: float = 1.0
    width: int = 10
