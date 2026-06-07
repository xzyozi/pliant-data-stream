import csv
from datetime import datetime
import logging
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from core.bootstrap.base_application import BaseApplication
from sort_engine.engine import SortEngine
from sort_engine.reader import CSVReader
from sort_engine.sorter import ExternalMergeSorter, SafeComparableKey
from sort_engine.writer import CSVWriter, SQLiteWriter

logger = logging.getLogger(__name__)


class ReverseComparableKey:
    """降順ソートのためのキー反転ラッパークラス。"""

    def __init__(self, key: Any) -> None:
        self.key = key

    def __lt__(self, other: Any) -> bool:
        # 逆向きの比較を行う
        return other.key < self.key

    def __eq__(self, other: Any) -> bool:
        return self.key == other.key


class TextHandler(logging.Handler):
    """ロギングメッセージを Tkinter の Text ウィジェットに出力するハンドラー。

    スレッドセーフにするために root.after を使用します。
    """

    def __init__(self, text_widget: tk.Text, root: tk.Tk) -> None:
        super().__init__()
        self.text_widget = text_widget
        self.root = root

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)

        def append() -> None:
            self.text_widget.configure(state=tk.NORMAL)
            self.text_widget.insert(tk.END, msg + "\n")
            self.text_widget.see(tk.END)
            self.text_widget.configure(state=tk.DISABLED)

        self.root.after(0, append)


class MainWindow(ttk.Frame):
    """SortEngine 用のメインGUI画面。"""

    def __init__(self, parent: tk.Tk, app_instance: BaseApplication) -> None:
        super().__init__(parent)
        self.parent = parent
        self.app = app_instance

        self.parent.title("Pliant Data Stream - Sort Engine")
        self.parent.geometry("800x650")
        self.pack(fill=tk.BOTH, expand=True)

        self._init_variables()
        self._build_ui()
        self._setup_logging()

    def _init_variables(self) -> None:
        # ファイルパス関連の変数
        self.input_path_var = tk.StringVar()
        self.output_path_var = tk.StringVar()
        self.has_header_var = tk.BooleanVar(value=True)
        self.auto_sync_path_var = tk.BooleanVar(value=True)

        # 出力設定
        self.output_format_var = tk.StringVar(value="CSV")
        self.sqlite_table_name_var = tk.StringVar(value="sorted_data")

        # 検出されたカラム
        self.detected_columns: list[str] = []

        # 入力パスやヘッダー扱いの変更時にカラム自動検出を実行するためのトレース設定
        self.input_path_var.trace_add("write", lambda *args: self._on_input_path_changed())
        self.has_header_var.trace_add("write", lambda *args: self._on_input_path_changed())

    def _build_ui(self) -> None:
        # メニューバーの設定
        self.menubar = tk.Menu(self.parent)
        self.parent.config(menu=self.menubar)
        self.app.theme_manager.set_menubar(self.menubar)

        # ファイルメニュー
        self.file_menu = tk.Menu(self.menubar, tearoff=0)
        self.file_menu.add_command(label="設定 (Settings)", command=self.app.open_settings_window)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="終了 (Exit)", command=self.app.on_closing)
        self.menubar.add_cascade(label="ファイル", menu=self.file_menu)

        # ----------------------------------------------------
        # 1. ファイル選択エリア (Input/Output)
        # ----------------------------------------------------
        files_frame = ttk.LabelFrame(self, text="データソースと出力先の設定", padding=10)
        files_frame.pack(fill=tk.X, padx=10, pady=5)

        # 入力
        ttk.Label(files_frame, text="入力(ファイル/フォルダ):").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(files_frame, textvariable=self.input_path_var, width=50).grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(files_frame, text="ファイル選択...", command=self._browse_input).grid(
            row=0, column=2, padx=5, pady=5
        )
        ttk.Button(files_frame, text="フォルダ選択...", command=self._browse_input_dir).grid(
            row=0, column=3, padx=5, pady=5
        )

        # ヘッダー / 自動同期チェックボックス
        cb_frame = ttk.Frame(files_frame)
        cb_frame.grid(row=1, column=1, columnspan=3, sticky=tk.W)
        ttk.Checkbutton(
            cb_frame, text="1行目をヘッダーとして扱う", variable=self.has_header_var, command=self._on_header_toggled
        ).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Checkbutton(
            cb_frame, text="出力先を入力パスと同期する", variable=self.auto_sync_path_var, command=self._on_sync_toggled
        ).pack(side=tk.LEFT)

        # 出力先
        ttk.Label(files_frame, text="出力先(ファイル/フォルダ):").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(files_frame, textvariable=self.output_path_var, width=50).grid(row=2, column=1, padx=5, pady=5)
        ttk.Button(files_frame, text="ファイル選択...", command=self._browse_output).grid(
            row=2, column=2, padx=5, pady=5
        )
        ttk.Button(files_frame, text="フォルダ選択...", command=self._browse_output_dir).grid(
            row=2, column=3, padx=5, pady=5
        )

        # 出力形式
        ttk.Label(files_frame, text="出力形式:").grid(row=3, column=0, sticky=tk.W, pady=5)
        fmt_frame = ttk.Frame(files_frame)
        fmt_frame.grid(row=3, column=1, columnspan=3, sticky=tk.W)
        ttk.Radiobutton(
            fmt_frame, text="CSV/TSV", value="CSV", variable=self.output_format_var, command=self._on_format_changed
        ).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(
            fmt_frame,
            text="SQLite (Database)",
            value="SQLite",
            variable=self.output_format_var,
            command=self._on_format_changed,
        ).pack(side=tk.LEFT, padx=5)

        # SQLite設定
        self.sqlite_frame = ttk.Frame(files_frame)
        ttk.Label(self.sqlite_frame, text="テーブル名:").pack(side=tk.LEFT, padx=5)
        ttk.Entry(self.sqlite_frame, textvariable=self.sqlite_table_name_var, width=20).pack(side=tk.LEFT, padx=5)

        # ----------------------------------------------------
        # 2. ソートキー設定エリア
        # ----------------------------------------------------
        keys_frame = ttk.LabelFrame(self, text="ソートキーの設定 (優先度順)", padding=10)
        keys_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 検出されたカラムの表示ラベル
        self.detected_cols_label = ttk.Label(keys_frame, text="検出されたカラム: (なし)", wraplength=700)
        self.detected_cols_label.pack(anchor=tk.W, pady=(0, 5))

        # 左右に分割するための親フレーム
        panes_frame = ttk.Frame(keys_frame)
        panes_frame.pack(fill=tk.BOTH, expand=True)

        # 左側：利用可能なカラム
        avail_frame = ttk.LabelFrame(panes_frame, text="利用可能なカラム (ダブルクリックで追加)", padding=5)
        avail_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        self.cols_listbox = tk.Listbox(avail_frame, selectmode=tk.SINGLE, height=6)
        self.cols_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.cols_listbox.bind("<Double-1>", lambda event: self._add_key_from_list())

        # スクロールバー
        avail_scroll = ttk.Scrollbar(avail_frame, orient=tk.VERTICAL, command=self.cols_listbox.yview)
        avail_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.cols_listbox.config(yscrollcommand=avail_scroll.set)

        # 中央：追加ボタン
        mid_frame = ttk.Frame(panes_frame)
        mid_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5)
        self.add_from_list_btn = ttk.Button(mid_frame, text="追加 ➡️", command=self._add_key_from_list)
        self.add_from_list_btn.pack(expand=True)

        # 右側：ソート順の設定
        config_frame = ttk.LabelFrame(panes_frame, text="ソート順の設定", padding=5)
        config_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))

        # キーリスト表示 (Treeview)
        columns = ("col_idx_or_name", "type", "order")
        self.keys_tree = ttk.Treeview(config_frame, columns=columns, show="headings", height=5)
        self.keys_tree.heading("col_idx_or_name", text="カラム名または列インデックス")
        self.keys_tree.heading("type", text="データ型")
        self.keys_tree.heading("order", text="並び順")

        self.keys_tree.column("col_idx_or_name", width=180)
        self.keys_tree.column("type", width=80)
        self.keys_tree.column("order", width=80)
        self.keys_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        # キー操作ボタン
        btn_frame = ttk.Frame(config_frame)
        btn_frame.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Button(btn_frame, text="新規追加...", command=self._add_key_dialog).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="キーを削除", command=self._delete_key).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="上へ移動", command=self._move_key_up).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="下へ移動", command=self._move_key_down).pack(fill=tk.X, pady=2)

        # ----------------------------------------------------
        # 3. アクション＆ログエリア
        # ----------------------------------------------------
        bottom_frame = ttk.Frame(self, padding=10)
        bottom_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 実行ボタン
        self.run_button = ttk.Button(
            bottom_frame, text="ソートを実行", command=self._run_sort_thread, style="Run.TButton"
        )
        self.run_button.pack(fill=tk.X, pady=(0, 5))

        # ログテキストボックス
        log_label = ttk.Label(bottom_frame, text="実行ログ:")
        log_label.pack(anchor=tk.W)
        self.log_text = tk.Text(bottom_frame, height=10, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # テーマ適用のための登録
        self.app.theme_manager.apply_theme_to_widget_tree(
            self, self.app.theme_manager.themes[self.app.theme_manager.current_theme]
        )

    def _setup_logging(self) -> None:
        """Text ウィジェットにログを出力するハンドラーを追加します。"""
        self.text_handler = TextHandler(self.log_text, self.parent)
        self.text_handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S")
        )
        logging.getLogger().addHandler(self.text_handler)
        logging.getLogger().setLevel(logging.INFO)

    def _browse_input(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("CSV files", "*.csv"), ("TSV files", "*.tsv"), ("All files", "*.*")]
        )
        if path:
            self.input_path_var.set(path)
            self._auto_set_output_path(path)

    def _browse_input_dir(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.input_path_var.set(path)
            self._auto_set_output_path(path)

    def _auto_set_output_path(self, input_path: str) -> None:
        if not input_path or not self.auto_sync_path_var.get():
            return

        if os.path.isdir(input_path):
            dir_name, base_name = os.path.split(os.path.normpath(input_path))
            output_name = f"{base_name}_sorted"
            output_path = os.path.join(dir_name, output_name)
            self.output_path_var.set(output_path)
        else:
            dir_name, file_name = os.path.split(input_path)
            base_name, ext = os.path.splitext(file_name)

            if self.output_format_var.get() == "SQLite":
                out_ext = ".db"
            else:
                out_ext = ext if ext else ".csv"

            output_name = f"{base_name}_sorted{out_ext}"
            output_path = os.path.join(dir_name, output_name)
            self.output_path_var.set(output_path)

    def _browse_output(self) -> None:
        if self.output_format_var.get() == "SQLite":
            path = filedialog.asksaveasfilename(
                defaultextension=".db", filetypes=[("SQLite Database files", "*.db;*.sqlite"), ("All files", "*.*")]
            )
        else:
            path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("TSV files", "*.tsv"), ("All files", "*.*")],
            )
        if path:
            self.output_path_var.set(path)

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.output_path_var.set(path)

    def _on_header_toggled(self) -> None:
        pass

    def _detect_columns(self, input_path: str) -> None:
        """入力パスからカラム名を自動検出して self.detected_columns を更新します。"""
        self.detected_columns = []
        if not input_path:
            return

        target_file = None
        if os.path.isdir(input_path):
            try:
                for entry_name in os.listdir(input_path):
                    full_in = os.path.join(input_path, entry_name)
                    if os.path.isfile(full_in) and entry_name.lower().endswith((".csv", ".tsv")):
                        target_file = full_in
                        break
            except Exception as e:
                logger.warning(f"フォルダ内のファイル一覧取得中にエラーが発生しました: {e}")
        elif os.path.isfile(input_path):
            target_file = input_path

        if not target_file:
            return

        try:
            has_header = self.has_header_var.get()
            reader = CSVReader(has_header=has_header)
            delim, actual_has_header = reader._detect_properties(target_file)

            with open(target_file, mode="r", encoding="utf-8", newline="") as f:
                csv_reader = csv.reader(f, delimiter=delim)
                first_row = next(csv_reader)

            if actual_has_header:
                self.detected_columns = [col.strip() for col in first_row if col.strip()]
                if not self.detected_columns:
                    self.detected_columns = [str(i) for i in range(len(first_row))]
            else:
                self.detected_columns = [str(i) for i in range(len(first_row))]

            if self.detected_columns:
                self.detected_cols_label.configure(text=f"検出されたカラム: {', '.join(self.detected_columns)}")
            else:
                self.detected_cols_label.configure(text="検出されたカラム: (なし)")

            # Listboxの更新
            self.cols_listbox.delete(0, tk.END)
            for col in self.detected_columns:
                self.cols_listbox.insert(tk.END, col)

            logger.info(f"カラム名を検出しました: {self.detected_columns}")
        except Exception as e:
            logger.warning(f"カラム名の自動検出中にエラーが発生しました: {e}")
            self.detected_cols_label.configure(text="検出されたカラム: (なし)")
            self.cols_listbox.delete(0, tk.END)

    def _on_input_path_changed(self) -> None:
        path = self.input_path_var.get().strip()
        if path and os.path.exists(path):
            self._detect_columns(path)

    def _on_sync_toggled(self) -> None:
        if self.auto_sync_path_var.get():
            self._auto_set_output_path(self.input_path_var.get())

    def _on_format_changed(self) -> None:
        if self.output_format_var.get() == "SQLite":
            self.sqlite_frame.grid(row=3, column=2, sticky=tk.W, padx=10)
        else:
            self.sqlite_frame.grid_forget()

        input_path = self.input_path_var.get().strip()
        if input_path:
            self._auto_set_output_path(input_path)

    def _add_key_from_list(self) -> None:
        selected_indices = self.cols_listbox.curselection()
        if not selected_indices:
            messagebox.showinfo("情報", "利用可能なカラムから追加するカラムを選択してください。")
            return
        col_name = self.cols_listbox.get(selected_indices[0])
        self._add_key_dialog(default_col=col_name)

    def _add_key_dialog(self, default_col: str | None = None) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("ソートキーの追加")
        dialog.geometry("350x200")
        dialog.grab_set()
        self.app.theme_manager.apply_theme_to_toplevel(dialog)

        ttk.Label(dialog, text="カラム名または列インデックス:").pack(pady=5)
        col_var = tk.StringVar(value=default_col if default_col else "")
        entry = ttk.Combobox(dialog, textvariable=col_var, width=28)
        if self.detected_columns:
            entry["values"] = self.detected_columns
            if default_col and default_col in self.detected_columns:
                entry.set(default_col)
            else:
                entry.current(0)
        entry.pack(pady=5)

        ttk.Label(dialog, text="データ型:").pack(pady=5)
        type_var = tk.StringVar(value="str")
        type_combo = ttk.Combobox(
            dialog, textvariable=type_var, values=["str", "int", "float", "datetime"], state="readonly"
        )
        type_combo.pack(pady=5)

        order_var = tk.StringVar(value="昇順")
        order_combo = ttk.Combobox(dialog, textvariable=order_var, values=["昇順", "降順"], state="readonly")
        order_combo.pack(pady=5)

        def save() -> None:
            col = col_var.get().strip()
            if not col:
                messagebox.showerror("エラー", "カラム名を入力してください。")
                return
            self.keys_tree.insert("", tk.END, values=(col, type_var.get(), order_var.get()))
            dialog.destroy()

        ttk.Button(dialog, text="追加", command=save).pack(pady=10)

    def _delete_key(self) -> None:
        selected = self.keys_tree.selection()
        if not selected:
            return
        for item in selected:
            self.keys_tree.delete(item)

    def _move_key_up(self) -> None:
        selected = self.keys_tree.selection()
        if not selected:
            return
        for idx in selected:
            index = self.keys_tree.index(idx)
            if index > 0:
                self.keys_tree.move(idx, self.keys_tree.parent(idx), index - 1)

    def _move_key_down(self) -> None:
        selected = self.keys_tree.selection()
        if not selected:
            return
        # 下から順に移動しないとインデックスが狂うため reversed を使用
        for idx in reversed(selected):
            index = self.keys_tree.index(idx)
            # 全子ノードの数を取得
            total = len(self.keys_tree.get_children())
            if index < total - 1:
                self.keys_tree.move(idx, self.keys_tree.parent(idx), index + 1)

    def _build_key_func(self) -> Callable[[list[Any]], Any]:
        """Treeview からソート用の key_func を生成します。"""
        key_settings = []
        has_header = self.has_header_var.get()

        for item in self.keys_tree.get_children():
            values = self.keys_tree.item(item, "values")
            if not isinstance(values, (list, tuple)) or len(values) < 3:
                continue
            col_key = values[0]
            col_type = values[1]
            is_descending = values[2] == "降順"
            key_settings.append((col_key, col_type, is_descending))

        def key_func(row: list[Any]) -> tuple[Any, ...]:
            # 行データからソート対象のカラム値を取得し、型キャストを行う
            # CSVReader を使用した場合は、読み込み時に型変換が行われるため、
            # row にはすでに変換後の値が入っている可能性がある。
            # しかし、念のためここでも型変換を試みる。
            key_values: list[Any] = []
            for col_key, col_type, is_descending in key_settings:
                # インデックスかカラム名かの特定
                val = None
                # has_header が有効な場合、ヘッダー名で検索を試みる
                # ただし row は list[Any] なので、列インデックスへのマッピングが必要
                # reader のヘッダー情報を利用する
                reader_header = getattr(self, "_active_reader_header", None)

                idx = None
                if has_header and reader_header:
                    try:
                        idx = reader_header.index(col_key)
                    except ValueError:
                        pass

                if idx is None:
                    try:
                        idx = int(col_key)
                    except ValueError:
                        pass

                if idx is not None and 0 <= idx < len(row):
                    val = row[idx]
                else:
                    val = None

                # キャスト処理
                casted_val: Any = None
                if val is not None and val != "":
                    try:
                        if col_type == "int":
                            casted_val = int(val)
                        elif col_type == "float":
                            casted_val = float(val)
                        elif col_type == "datetime":
                            if isinstance(val, datetime):
                                casted_val = val
                            else:
                                # 代表的なISOフォーマットでパース
                                casted_val = datetime.fromisoformat(str(val))
                        else:
                            casted_val = str(val)
                    except Exception:
                        casted_val = val
                else:
                    casted_val = None

                # SafeComparableKey で異なる型や None の比較を安全にする
                wrapped_val = SafeComparableKey(casted_val)

                # 降順の場合は ReverseComparableKey で逆比較にする
                if is_descending:
                    key_values.append(ReverseComparableKey(wrapped_val))
                else:
                    key_values.append(wrapped_val)

            return tuple(key_values)

        return key_func

    def _run_sort_thread(self) -> None:
        """GUIをフリーズさせないよう、別スレッドでソート処理を走らせます。"""
        input_path = self.input_path_var.get().strip()
        output_path = self.output_path_var.get().strip()

        if not input_path or not os.path.exists(input_path):
            messagebox.showerror("エラー", "正しい入力ファイルまたはフォルダを指定してください。")
            return
        if not output_path:
            messagebox.showerror("エラー", "出力先を指定してください。")
            return
        if not self.keys_tree.get_children():
            messagebox.showerror("エラー", "ソートキーを少なくとも1つ追加してください。")
            return

        if os.path.isdir(input_path):
            if os.path.isfile(output_path):
                messagebox.showerror("エラー", "入力がフォルダの場合、出力先にはフォルダを指定してください。")
                return

        self.run_button.configure(state=tk.DISABLED)
        thread = threading.Thread(target=self._execute_sort, args=(input_path, output_path), daemon=True)
        thread.start()

    def _execute_sort(self, input_path: str, output_path: str) -> None:
        try:
            logger.info("ソート処理を開始します...")

            chunk_size = self.app.settings_manager.get_setting("default_chunk_size", 50000)
            has_header = self.has_header_var.get()
            output_format = self.output_format_var.get()

            is_dir_mode = os.path.isdir(input_path)

            if is_dir_mode:
                os.makedirs(output_path, exist_ok=True)
                target_files = []
                for entry_name in os.listdir(input_path):
                    full_in = os.path.join(input_path, entry_name)
                    if os.path.isfile(full_in) and entry_name.lower().endswith((".csv", ".tsv")):
                        target_files.append(full_in)

                if not target_files:
                    raise FileNotFoundError("指定されたフォルダ内に対象となるCSV/TSVファイルが見つかりません。")

                logger.info(f"{len(target_files)} 件のファイルの一括処理を開始します。")

                for i, file_in in enumerate(target_files, 1):
                    file_name = os.path.basename(file_in)
                    base_name, ext = os.path.splitext(file_name)

                    if output_format == "SQLite":
                        out_ext = ".db"
                    else:
                        out_ext = ext if ext else ".csv"

                    file_out = os.path.join(output_path, f"{base_name}_sorted{out_ext}")
                    logger.info(f"[{i}/{len(target_files)}] 処理中: {file_name} -> {os.path.basename(file_out)}")
                    self._execute_single_sort(file_in, file_out, chunk_size, has_header, output_format)
            else:
                if os.path.isdir(output_path):
                    file_name = os.path.basename(input_path)
                    base_name, ext = os.path.splitext(file_name)
                    if output_format == "SQLite":
                        out_ext = ".db"
                    else:
                        out_ext = ext if ext else ".csv"
                    file_out = os.path.join(output_path, f"{base_name}_sorted{out_ext}")
                else:
                    parent_dir = os.path.dirname(output_path)
                    if parent_dir:
                        os.makedirs(parent_dir, exist_ok=True)
                    file_out = output_path

                self._execute_single_sort(input_path, file_out, chunk_size, has_header, output_format)

            logger.info(f"ソート処理が完了しました！ 出力先: {output_path}")
            self.parent.after(
                0, lambda: messagebox.showinfo("成功", f"ソート処理が完了しました。\n出力先: {output_path}")
            )

        except Exception as e:
            logger.error(f"ソート処理中にエラーが発生しました: {e}", exc_info=True)
            err_msg = str(e)
            self.parent.after(0, lambda: messagebox.showerror("エラー", f"エラーが発生しました:\n{err_msg}"))
        finally:
            self.parent.after(0, lambda: self.run_button.configure(state=tk.NORMAL))

    def _execute_single_sort(
        self, file_in: str, file_out: str, chunk_size: int, has_header: bool, output_format: str
    ) -> None:
        reader = CSVReader(has_header=has_header)
        temp_stream = reader.read(file_in)
        try:
            next(temp_stream)
        except StopIteration:
            pass
        self._active_reader_header = getattr(reader, "header", None)

        reader = CSVReader(has_header=has_header)
        sorter = ExternalMergeSorter(chunk_size=chunk_size)

        writer: Any
        if output_format == "SQLite":
            gui_table_name = self.sqlite_table_name_var.get().strip()
            is_dir_input = os.path.isdir(self.input_path_var.get().strip())

            if gui_table_name and not is_dir_input:
                table_name = gui_table_name
            else:
                file_name = os.path.basename(file_in)
                base_name, _ = os.path.splitext(file_name)
                table_name = "".join(c for c in base_name if c.isalnum() or c == "_")
                if table_name and table_name[0].isdigit():
                    table_name = f"t_{table_name}"
                if not table_name:
                    table_name = "sorted_data"

            journal_mode = self.app.settings_manager.get_setting("sqlite_journal_mode", "WAL")
            synchronous = self.app.settings_manager.get_setting("sqlite_synchronous", "NORMAL")
            writer = SQLiteWriter(
                table_name=table_name, has_header=has_header, journal_mode=journal_mode, synchronous=synchronous
            )
        else:
            writer = CSVWriter()

        key_func = self._build_key_func()
        engine = SortEngine(reader=reader, sorter=sorter, writer=writer)
        engine.execute(input_path=file_in, output_path=file_out, key_func=key_func)
