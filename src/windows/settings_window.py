"""
reusable_gui.windows.settings_window
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
スキーマ駆動の汎用設定ウィンドウ。

SettingsManager.get_settings_schema() が返す list[SettingField] を唯一の情報源とし、
タブ・グループ・ウィジェットを自動生成する。
特定アプリの設定項目はこのモジュールに一切含まれない。
"""
from __future__ import annotations

import copy
import logging
import tkinter as tk
from collections import defaultdict
from tkinter import filedialog, font, messagebox, simpledialog, ttk
from typing import TYPE_CHECKING, Any

from reusable_gui.core.config import defaults as config
from reusable_gui.core.config.schema import SettingField, WidgetType

if TYPE_CHECKING:
    from reusable_gui.core.bootstrap.base_application import BaseApplication
    from reusable_gui.core.config.settings_manager import BaseSettingsManager

logger = logging.getLogger(__name__)


class SettingsWindow(tk.Toplevel):
    """スキーマ駆動の汎用設定ウィンドウ。

    SettingsManager が提供するスキーマ（list[SettingField]）を読み取り、
    タブ・グループ・ウィジェットを動的に生成する。
    アプリ固有の設定項目はスキーマとして外部から注入されるため、
    このクラス自体は完全に汎用的に保たれる。
    """

    def __init__(
        self,
        master: tk.Misc,
        app_instance: BaseApplication,
        settings_manager: BaseSettingsManager,
    ) -> None:
        super().__init__(master)
        self.app = app_instance
        if hasattr(app_instance, "theme_manager") and hasattr(
            app_instance.theme_manager, "apply_theme_to_toplevel"
        ):
            app_instance.theme_manager.apply_theme_to_toplevel(self)  # type: ignore

        self.title("Settings")
        self.geometry(config.SETTINGS_WINDOW_GEOMETRY)
        self.resizable(True, True)

        self.settings_manager = settings_manager
        self.app_instance = app_instance

        self.initial_settings = copy.deepcopy(self.settings_manager.settings)
        self.settings_saved = False

        # スキーマ取得
        self._schema: list[SettingField] = self.settings_manager.get_settings_schema()

        # key -> tk.Variable のマップ（WidgetType に応じた型で生成）
        self._vars: dict[str, tk.Variable] = {}

        # LISTBOX_EDIT 型の値は list なので別途管理
        self._list_vars: dict[str, list[str]] = {}
        self._listbox_widgets: dict[str, tk.Listbox] = {}

        self._init_variables()
        self._build_ui()

    # ------------------------------------------------------------------
    # 変数の初期化
    # ------------------------------------------------------------------

    def _init_variables(self) -> None:
        """スキーマを走査し、各設定項目に対応する tk.Variable を生成する。"""
        for f in self._schema:
            value: Any = self.settings_manager.get_setting(f.key, f.default)

            if f.widget_type == WidgetType.CHECKBUTTON:
                self._vars[f.key] = tk.BooleanVar(value=bool(value))

            elif f.widget_type == WidgetType.SPINBOX:
                if isinstance(value, float):
                    self._vars[f.key] = tk.DoubleVar(value=float(value))
                else:
                    self._vars[f.key] = tk.IntVar(value=int(value) if value is not None else 0)

            elif f.widget_type in (WidgetType.OPTION_MENU, WidgetType.FONT_PICKER, WidgetType.ENTRY):
                self._vars[f.key] = tk.StringVar(value=str(value) if value is not None else "")

            elif f.widget_type == WidgetType.LISTBOX_EDIT:
                # リスト型は tk.Variable では扱えないので別管理
                self._list_vars[f.key] = list(value) if value else []

    # ------------------------------------------------------------------
    # UIの構築
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Notebook・タブ・グループ・ウィジェット・ボタン群を構築する。"""
        self._build_notebook()
        self._build_action_buttons()

    def _build_notebook(self) -> None:
        """スキーマからタブ・グループ構造を推論し Notebook を構築する。"""
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(
            pady=config.BUTTON_PADDING_Y,
            padx=config.BUTTON_PADDING_X,
            fill=tk.BOTH,
            expand=True,
        )

        # タブ順序を保持したまま tab -> group -> [fields] に整理
        tab_order: list[str] = []
        tab_groups: dict[str, dict[str, list[SettingField]]] = {}

        for f in self._schema:
            if f.tab not in tab_groups:
                tab_order.append(f.tab)
                tab_groups[f.tab] = defaultdict(list)
            tab_groups[f.tab][f.group].append(f)

        self._tab_frames: dict[str, ttk.Frame] = {}

        for tab_name in tab_order:
            frame = ttk.Frame(self.notebook, padding=config.FRAME_PADDING)
            self.notebook.add(frame, text=tab_name)
            self._tab_frames[tab_name] = frame
            self._render_tab(frame, tab_groups[tab_name])

    def _render_tab(
        self, parent: ttk.Frame, groups: dict[str, list[SettingField]]
    ) -> None:
        """タブ内のグループ（LabelFrame）とウィジェットを描画する。"""
        for group_name, fields in groups.items():
            if group_name:
                container: tk.Widget = ttk.LabelFrame(
                    parent, text=group_name, padding=config.FRAME_PADDING
                )
                container.pack(
                    fill=tk.X,
                    pady=config.BUTTON_PADDING_Y,
                    padx=config.BUTTON_PADDING_X,
                )
            else:
                container = ttk.Frame(parent, padding=config.FRAME_PADDING)
                container.pack(fill=tk.X)

            row = 0
            for f in fields:
                row = self._render_field(container, f, row)

    def _render_field(self, parent: tk.Widget, f: SettingField, row: int) -> int:
        """WidgetType に応じてウィジェットを生成し、grid で配置する。row の次の値を返す。"""
        if f.widget_type == WidgetType.CHECKBUTTON:
            cb = ttk.Checkbutton(parent, text=f.label, variable=self._vars[f.key])
            cb.grid(
                row=row, column=0, columnspan=2, sticky=tk.W,
                padx=config.BUTTON_PADDING_X, pady=config.BUTTON_PADDING_Y,
            )
            return row + 1

        elif f.widget_type == WidgetType.SPINBOX:
            lbl = ttk.Label(parent, text=f"{f.label}:")
            lbl.grid(row=row, column=0, sticky=tk.W,
                     padx=config.BUTTON_PADDING_X, pady=config.BUTTON_PADDING_Y)
            sp = ttk.Spinbox(
                parent,
                from_=f.min_value,
                to=f.max_value,
                increment=f.increment,
                textvariable=self._vars[f.key],
                width=f.width,
            )
            sp.grid(row=row, column=1, sticky=tk.W,
                    padx=config.BUTTON_PADDING_X, pady=config.BUTTON_PADDING_Y)
            return row + 1

        elif f.widget_type == WidgetType.OPTION_MENU:
            lbl = ttk.Label(parent, text=f"{f.label}:")
            lbl.grid(row=row, column=0, sticky=tk.W,
                     padx=config.BUTTON_PADDING_X, pady=config.BUTTON_PADDING_Y)
            var = self._vars[f.key]
            menu = ttk.OptionMenu(parent, var, var.get(), *f.choices)  # type: ignore[arg-type]
            menu.grid(row=row, column=1, sticky=tk.W,
                      padx=config.BUTTON_PADDING_X, pady=config.BUTTON_PADDING_Y)
            return row + 1

        elif f.widget_type == WidgetType.FONT_PICKER:
            lbl = ttk.Label(parent, text=f"{f.label}:")
            lbl.grid(row=row, column=0, sticky=tk.W,
                     padx=config.BUTTON_PADDING_X, pady=config.BUTTON_PADDING_Y)
            font_families = sorted(font.families())
            var = self._vars[f.key]
            menu = ttk.OptionMenu(parent, var, var.get(), *font_families)  # type: ignore[arg-type]
            menu.grid(row=row, column=1, sticky=tk.W,
                      padx=config.BUTTON_PADDING_X, pady=config.BUTTON_PADDING_Y)
            return row + 1

        elif f.widget_type == WidgetType.ENTRY:
            lbl = ttk.Label(parent, text=f"{f.label}:")
            lbl.grid(row=row, column=0, sticky=tk.W,
                     padx=config.BUTTON_PADDING_X, pady=config.BUTTON_PADDING_Y)
            entry = ttk.Entry(parent, textvariable=self._vars[f.key], width=f.width)
            entry.grid(row=row, column=1, sticky=tk.EW,
                       padx=config.BUTTON_PADDING_X, pady=config.BUTTON_PADDING_Y)
            return row + 1

        elif f.widget_type == WidgetType.LISTBOX_EDIT:
            self._render_listbox_edit(parent, f)
            return row + 1  # LISTBOX_EDIT はグリッドではなく pack を使うため行は +1 のみ

        logger.warning("Unknown WidgetType %s for key '%s'. Skipped.", f.widget_type, f.key)
        return row

    def _render_listbox_edit(self, parent: tk.Widget, f: SettingField) -> None:
        """LISTBOX_EDIT 型: Listbox + Add/Remove ボタンを描画する。"""
        wrapper = ttk.Frame(parent)
        wrapper.pack(fill=tk.BOTH, expand=True,
                     padx=config.BUTTON_PADDING_X, pady=config.BUTTON_PADDING_Y)

        listbox = tk.Listbox(wrapper)
        for item in self._list_vars[f.key]:
            listbox.insert(tk.END, item)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._listbox_widgets[f.key] = listbox

        btn_frame = ttk.Frame(wrapper)
        btn_frame.pack(side=tk.LEFT, padx=(10, 0))

        ttk.Button(
            btn_frame, text="Add",
            command=lambda key=f.key: self._add_list_item(key),
        ).pack(fill=tk.X, pady=config.BUTTON_PADDING_Y)

        ttk.Button(
            btn_frame, text="Remove",
            command=lambda key=f.key: self._remove_list_item(key),
        ).pack(fill=tk.X, pady=config.BUTTON_PADDING_Y)

    def _build_action_buttons(self) -> None:
        """Import / Export / Restore Defaults / Save / Cancel / Apply ボタンを構築する。"""
        # Import / Export / Restore Defaults
        io_frame = ttk.Frame(self)
        io_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=config.BUTTON_PADDING_Y,
                      padx=config.BUTTON_PADDING_X)

        ttk.Button(io_frame, text="Export Settings", command=self._export_settings).pack(
            side=tk.LEFT
        )
        ttk.Button(io_frame, text="Import Settings", command=self._import_settings).pack(
            side=tk.LEFT, padx=config.BUTTON_PADDING_X
        )
        ttk.Button(io_frame, text="Restore Defaults", command=self._restore_defaults).pack(
            side=tk.LEFT
        )

        # Save / Cancel / Apply
        btn_frame = ttk.Frame(self, padding=config.FRAME_PADDING)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        ttk.Button(btn_frame, text="Save", command=self._save_and_close).pack(
            side=tk.RIGHT, padx=(10, 0)
        )
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Apply", command=self._apply_only).pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    # リスト操作（LISTBOX_EDIT）
    # ------------------------------------------------------------------

    def _add_list_item(self, key: str) -> None:
        new_item: str | None = simpledialog.askstring(
            "Add Item", f"Enter value for '{key}':", parent=self
        )
        if new_item and new_item not in self._list_vars[key]:
            self._list_vars[key].append(new_item)
            self._listbox_widgets[key].insert(tk.END, new_item)

    def _remove_list_item(self, key: str) -> None:
        selected = self._listbox_widgets[key].curselection()
        for i in reversed(selected):
            self._listbox_widgets[key].delete(i)
            del self._list_vars[key][i]

    # ------------------------------------------------------------------
    # 設定の読み書き
    # ------------------------------------------------------------------

    def _collect_values(self) -> None:
        """全 tk.Variable と list_vars から値を収集し settings_manager に書き込む。"""
        for f in self._schema:
            if f.widget_type == WidgetType.LISTBOX_EDIT:
                self.settings_manager.set_setting(f.key, list(self._list_vars[f.key]))
            else:
                self.settings_manager.set_setting(f.key, self._vars[f.key].get())

    def _update_ui_from_settings(self) -> None:
        """設定値を settings_manager から再読み込みし、全 UI 変数を更新する。"""
        for f in self._schema:
            value: Any = self.settings_manager.get_setting(f.key, f.default)

            if f.widget_type == WidgetType.LISTBOX_EDIT:
                self._list_vars[f.key] = list(value) if value else []
                lb = self._listbox_widgets[f.key]
                lb.delete(0, tk.END)
                for item in self._list_vars[f.key]:
                    lb.insert(tk.END, item)
            else:
                try:
                    self._vars[f.key].set(value)
                except (tk.TclError, KeyError) as e:
                    logger.warning("Failed to update UI for key '%s': %s", f.key, e)

    # ------------------------------------------------------------------
    # アクション
    # ------------------------------------------------------------------

    def _apply_only(self) -> None:
        self._collect_values()
        self.settings_manager.notify_listeners()

    def _save_and_close(self) -> None:
        self._collect_values()
        self.settings_manager.save_settings()
        self.settings_saved = True
        logger.info("Settings saved.")
        self.destroy()

    def _export_settings(self) -> None:
        filepath: str | None = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Export Settings",
        )
        if filepath:
            self.settings_manager.save_settings_to_file(filepath)
            logger.info("Settings exported to %s", filepath)
            messagebox.showinfo("Export Successful", f"Settings exported to {filepath}")

    def _import_settings(self) -> bool:
        filepath: str | None = filedialog.askopenfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Import Settings",
        )
        if filepath:
            if self.settings_manager.load_settings_from_file(filepath):
                self._update_ui_from_settings()
                messagebox.showinfo("Import Successful", "Settings imported successfully.")
                return True
            else:
                logger.error("Could not load settings from: %s", filepath)
                messagebox.showerror(
                    "Import Failed", "Could not load settings from the selected file."
                )
        return False

    def _restore_defaults(self) -> None:
        if messagebox.askyesno(
            "Restore Defaults",
            "Are you sure you want to restore all settings to their default values?",
        ):
            self.settings_manager.settings = self.settings_manager._get_default_settings()
            self._update_ui_from_settings()
            logger.info("Settings restored to defaults.")

    def destroy(self) -> None:
        if not self.settings_saved:
            self.settings_manager.settings = copy.deepcopy(self.initial_settings)
            self.settings_manager.notify_listeners()
        super().destroy()
