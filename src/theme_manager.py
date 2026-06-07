import logging
import tkinter as tk
from tkinter import Tk, Toplevel, ttk
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_THEMES = {
    "light": {
        "bg": "#f0f0f0",
        "fg": "#000000",
        "frame_bg": "#f0f0f0",
        "label_fg": "#000000",
        "button_bg": "#e1e1e1",
        "button_fg": "#000000",
        "entry_bg": "#ffffff",
        "entry_fg": "#000000",
        "listbox_bg": "#ffffff",
        "listbox_fg": "#000000",
        "select_bg": "#0078d7",
        "select_fg": "#ffffff",
        "pinned_bg": "#ffeb3b",
    },
    "dark": {
        "bg": "#2d2d2d",
        "fg": "#ffffff",
        "frame_bg": "#2d2d2d",
        "label_fg": "#ffffff",
        "button_bg": "#3d3d3d",
        "button_fg": "#ffffff",
        "entry_bg": "#1e1e1e",
        "entry_fg": "#ffffff",
        "listbox_bg": "#1e1e1e",
        "listbox_fg": "#ffffff",
        "select_bg": "#0f5b9e",
        "select_fg": "#ffffff",
        "pinned_bg": "#5c5c00",
    }
}


class ThemeManager:
    def __init__(self, root: Tk, themes: dict[str, dict[str, str]] | None = None) -> None:
        self.root = root
        self.current_theme = "light"
        self.menubar: tk.Menu | None = None
        self.themes = themes or DEFAULT_THEMES

    def set_menubar(self, menubar: tk.Menu) -> None:
        self.menubar = menubar

    def apply_theme(self, theme_name: str) -> None:
        if theme_name not in self.themes:
            logger.warning(f"Theme '{theme_name}' not found. Falling back to 'light'.")
            theme_name = "light"
        self.current_theme = theme_name
        theme = self.themes[theme_name]

        # 1. Configure ttk styles
        style = ttk.Style(self.root)
        if theme_name == 'dark':
            style.theme_use('clam')
        else:
            style.theme_use('default')

        style.configure('.', background=theme["bg"], foreground=theme["fg"])
        style.configure('TFrame', background=theme["frame_bg"])
        style.configure('TLabel', background=theme["frame_bg"], foreground=theme["label_fg"])
        style.configure('TLabelFrame', background=theme["frame_bg"], foreground=theme["label_fg"])
        style.configure('TButton', background=theme["button_bg"], foreground=theme["button_fg"])
        style.map('TButton', background=[('active', theme["button_bg"])])

        # Custom button styles for calendar
        style.configure('Today.TButton', background=theme.get("highlight_bg", theme["button_bg"]), foreground=theme["button_fg"])
        style.map('Today.TButton', background=[('active', theme.get("highlight_bg", theme["button_bg"]))])
        style.configure('Selected.TButton', background=theme["select_bg"], foreground=theme["select_fg"])
        style.map('Selected.TButton', background=[('active', theme["select_bg"])])

        style.configure('TCheckbutton', background=theme["frame_bg"], foreground=theme["label_fg"])
        style.configure('TRadiobutton', background=theme["frame_bg"], foreground=theme["label_fg"])
        style.configure('TEntry', fieldbackground=theme["entry_bg"], foreground=theme["entry_fg"], insertbackground=theme["fg"])
        style.configure('TSpinbox', fieldbackground=theme["entry_bg"], foreground=theme["entry_fg"])
        style.configure('TCombobox', fieldbackground=theme["entry_bg"], foreground=theme["entry_fg"])

        # Notebook specific styling
        style.configure('TNotebook', background=theme["bg"], bordercolor=theme["frame_bg"])
        style.configure('TNotebook.Tab', background=theme["frame_bg"], foreground=theme["label_fg"])
        style.map('TNotebook.Tab', background=[('selected', theme["bg"])], foreground=[('selected', theme["fg"])])

        # Treeview specific styling
        style.configure('Treeview', background=theme["listbox_bg"], foreground=theme["listbox_fg"], fieldbackground=theme["listbox_bg"])
        style.map('Treeview', background=[('selected', theme["select_bg"])], foreground=[('selected', theme["select_fg"])])
        style.configure('Treeview.Heading', background=theme["button_bg"], foreground=theme["button_fg"])

        # 2. Recursively apply theme to non-ttk widgets
        self.apply_theme_to_widget_tree(self.root, theme)

        # 3. Apply theme to menubar
        if self.menubar:
            self._apply_theme_to_menu(self.menubar, theme)

    def _apply_theme_to_menu(self, menu: tk.Menu, theme: dict[str, str]) -> None:
        menu_config: dict[str, Any] = {
            "relief": tk.FLAT,
            "borderwidth": 0
        }
        if "menu_bg" in theme:
            menu_config["background"] = theme["menu_bg"]
        if "menu_fg" in theme:
            menu_config["foreground"] = theme["menu_fg"]
        if "active_menu_bg" in theme:
            menu_config["activebackground"] = theme["active_menu_bg"]
        if "active_menu_fg" in theme:
            menu_config["activeforeground"] = theme["active_menu_fg"]

        try:
            menu.config(**menu_config)
        except tk.TclError:
            pass # May fail on some systems

        try:
            end_index = menu.index("end")
            if end_index is not None:
                for i in range(end_index + 1):
                    if menu.type(i) == "cascade":
                        submenu_name = menu.entrycget(i, "menu")
                        if submenu_name:
                            submenu = menu.nametowidget(submenu_name)
                            self._apply_theme_to_menu(submenu, theme)
        except (tk.TclError, AttributeError):
            # This can fail on some systems or if the menu is torn off
            pass

    def apply_theme_to_widget_tree(self, widget: tk.Misc, theme: dict[str, Any]) -> None:
        try:
            if isinstance(widget, (tk.Tk, tk.Toplevel, tk.Frame, tk.LabelFrame)):
                 widget.config(bg=theme["bg"])
            elif isinstance(widget, (tk.Text, tk.Listbox)):
                widget.config(bg=theme["listbox_bg"], fg=theme["listbox_fg"], selectbackground=theme["select_bg"], selectforeground=theme["select_fg"])
            elif isinstance(widget, tk.Button):
                widget.config(bg=theme["button_bg"], fg=theme["button_fg"], activebackground=theme["select_bg"], activeforeground=theme["select_fg"])
            elif isinstance(widget, (tk.Checkbutton, tk.Radiobutton)):
                widget.config(bg=theme["button_bg"], fg=theme["button_fg"], activebackground=theme["select_bg"], activeforeground=theme["select_fg"], selectcolor=theme["frame_bg"])
            elif isinstance(widget, tk.Label):
                widget.config(bg=theme["bg"], fg=theme["label_fg"])

        except (tk.TclError, AttributeError):
            pass # Ignore errors for widgets that don't support these properties

        for child in widget.winfo_children():
            self.apply_theme_to_widget_tree(child, theme)

    def apply_theme_to_toplevel(self, toplevel_window: Toplevel) -> None:
        """Applies the current theme to a Toplevel window and its children."""
        theme = self.themes[self.current_theme]
        self.apply_theme_to_widget_tree(toplevel_window, theme)

    def get_current_theme(self) -> str:
        return self.current_theme
