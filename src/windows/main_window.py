import logging
import os
import threading
import tkinter as tk
from datetime import datetime
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

        # 出力設定
        self.output_format_var = tk.StringVar(value="CSV")
        self.sqlite_table_name_var = tk.StringVar(value="sorted_data")

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

        # 入力ファイル
        ttk.Label(files_frame, text="入力CSVファイル:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(files_frame, textvariable=self.input_path_var, width=60).grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(files_frame, text="選択...", command=self._browse_input).grid(row=0, column=2, padx=5, pady=5)

        # ヘッダーチェックボックス
        ttk.Checkbutton(
            files_frame,
            text="1行目をヘッダーとして扱う",
            variable=self.has_header_var,
            command=self._on_header_toggled
        ).grid(row=1, column=1, sticky=tk.W, pady=2)

        # 出力ファイル
        ttk.Label(files_frame, text="出力先ファイル:").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(files_frame, textvariable=self.output_path_var, width=60).grid(row=2, column=1, padx=5, pady=5)
        ttk.Button(files_frame, text="選択...", command=self._browse_output).grid(row=2, column=2, padx=5, pady=5)

        # 出力形式
        ttk.Label(files_frame, text="出力形式:").grid(row=3, column=0, sticky=tk.W, pady=5)
        fmt_frame = ttk.Frame(files_frame)
        fmt_frame.grid(row=3, column=1, columnspan=2, sticky=tk.W)
        ttk.Radiobutton(
            fmt_frame, text="CSV/TSV", value="CSV", variable=self.output_format_var, command=self._on_format_changed
        ).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(
            fmt_frame, text="SQLite (Database)", value="SQLite", variable=self.output_format_var, command=self._on_format_changed
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

        # キーリスト表示 (Treeview)
        columns = ("col_idx_or_name", "type", "order")
        self.keys_tree = ttk.Treeview(keys_frame, columns=columns, show="headings", height=5)
        self.keys_tree.heading("col_idx_or_name", text="カラム名または列インデックス")
        self.keys_tree.heading("type", text="データ型")
        self.keys_tree.heading("order", text="並び順")

        self.keys_tree.column("col_idx_or_name", width=300)
        self.keys_tree.column("type", width=150)
        self.keys_tree.column("order", width=150)
        self.keys_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        # キー操作ボタン
        btn_frame = ttk.Frame(keys_frame)
        btn_frame.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Button(btn_frame, text="キーを追加", command=self._add_key_dialog).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="キーを削除", command=self._delete_key).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="上へ移動", command=self._move_key_up).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="下へ移動", command=self._move_key_down).pack(fill=tk.X, pady=2)

        # ----------------------------------------------------
        # 3. アクション＆ログエリア
        # ----------------------------------------------------
        bottom_frame = ttk.Frame(self, padding=10)
        bottom_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 実行ボタン
        self.run_button = ttk.Button(bottom_frame, text="ソートを実行", command=self._run_sort_thread, style="Run.TButton")
        self.run_button.pack(fill=tk.X, pady=(0, 5))

        # ログテキストボックス
        log_label = ttk.Label(bottom_frame, text="実行ログ:")
        log_label.pack(anchor=tk.W)
        self.log_text = tk.Text(bottom_frame, height=10, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # テーマ適用のための登録
        self.app.theme_manager.apply_theme_to_widget_tree(self, self.app.theme_manager.themes[self.app.theme_manager.current_theme])

    def _setup_logging(self) -> None:
        """Text ウィジェットにログを出力するハンドラーを追加します。"""
        self.text_handler = TextHandler(self.log_text, self.parent)
        self.text_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S"))
        logging.getLogger().addHandler(self.text_handler)
        logging.getLogger().setLevel(logging.INFO)

    def _browse_input(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv"), ("TSV files", "*.tsv"), ("All files", "*.*")])
        if path:
            self.input_path_var.set(path)

    def _browse_output(self) -> None:
        if self.output_format_var.get() == "SQLite":
            path = filedialog.asksaveasfilename(defaultextension=".db", filetypes=[("SQLite Database files", "*.db;*.sqlite"), ("All files", "*.*")])
        else:
            path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv"), ("TSV files", "*.tsv"), ("All files", "*.*")])
        if path:
            self.output_path_var.set(path)

    def _on_header_toggled(self) -> None:
        pass

    def _on_format_changed(self) -> None:
        if self.output_format_var.get() == "SQLite":
            self.sqlite_frame.grid(row=3, column=2, sticky=tk.W, padx=10)
        else:
            self.sqlite_frame.grid_forget()

    def _add_key_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("ソートキーの追加")
        dialog.geometry("350x200")
        dialog.grab_set()
        self.app.theme_manager.apply_theme_to_toplevel(dialog)

        ttk.Label(dialog, text="カラム名または列インデックス:").pack(pady=5)
        entry = ttk.Entry(dialog, width=30)
        entry.pack(pady=5)

        ttk.Label(dialog, text="データ型:").pack(pady=5)
        type_var = tk.StringVar(value="str")
        type_combo = ttk.Combobox(dialog, textvariable=type_var, values=["str", "int", "float", "datetime"], state="readonly")
        type_combo.pack(pady=5)

        order_var = tk.StringVar(value="昇順")
        order_combo = ttk.Combobox(dialog, textvariable=order_var, values=["昇順", "降順"], state="readonly")
        order_combo.pack(pady=5)

        def save() -> None:
            col = entry.get().strip()
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
            col_key = values[0]
            col_type = values[1]
            is_descending = values[2] == "降順"
            key_settings.append((col_key, col_type, is_descending))

        def key_func(row: list[Any]) -> tuple[Any, ...]:
            # 行データからソート対象のカラム値を取得し、型キャストを行う
            # CSVReader を使用した場合は、読み込み時に型変換が行われるため、
            # row にはすでに変換後の値が入っている可能性がある。
            # しかし、念のためここでも型変換を試みる。
            key_values = []
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
                casted_val = None
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
            messagebox.showerror("エラー", "正しい入力ファイルを指定してください。")
            return
        if not output_path:
            messagebox.showerror("エラー", "出力ファイルを指定してください。")
            return
        if not self.keys_tree.get_children():
            messagebox.showerror("エラー", "ソートキーを少なくとも1つ追加してください。")
            return

        self.run_button.configure(state=tk.DISABLED)
        thread = threading.Thread(target=self._execute_sort, args=(input_path, output_path), daemon=True)
        thread.start()

    def _execute_sort(self, input_path: str, output_path: str) -> None:
        try:
            logger.info("ソート処理を開始します...")

            # 設定値の取得
            chunk_size = self.app.settings_manager.get_setting("default_chunk_size", 50000)
            has_header = self.has_header_var.get()
            output_format = self.output_format_var.get()

            # Readerの初期化
            # ソートキーを正しくインデックス化するために、一度 Reader のヘッダーを先読みする
            reader = CSVReader(has_header=has_header)
            # 一時的にヘッダーを特定するために先読み
            temp_stream = reader.read(input_path)
            try:
                # 最初のイテレートでヘッダーが確定する
                next(temp_stream)
            except StopIteration:
                pass
            self._active_reader_header = getattr(reader, "header", None)

            # 再び新鮮なリーダーを用意する
            reader = CSVReader(has_header=has_header)

            # Sorterの初期化
            sorter = ExternalMergeSorter(chunk_size=chunk_size)

            # Writerの初期化
            if output_format == "SQLite":
                table_name = self.sqlite_table_name_var.get().strip() or "sorted_data"
                journal_mode = self.app.settings_manager.get_setting("sqlite_journal_mode", "WAL")
                synchronous = self.app.settings_manager.get_setting("sqlite_synchronous", "NORMAL")
                writer = SQLiteWriter(
                    table_name=table_name,
                    has_header=has_header,
                    journal_mode=journal_mode,
                    synchronous=synchronous
                )
            else:
                writer = CSVWriter()

            # ソートキー評価関数の生成
            key_func = self._build_key_func()

            # エンジンの構築と実行
            engine = SortEngine(reader=reader, sorter=sorter, writer=writer)
            engine.execute(input_path=input_path, output_path=output_path, key_func=key_func)

            logger.info(f"ソート処理が完了しました！ 出力先: {output_path}")
            self.parent.after(0, lambda: messagebox.showinfo("成功", f"ソート処理が完了しました。\n出力先: {output_path}"))

        except Exception as e:
            logger.error(f"ソート処理中にエラーが発生しました: {e}", exc_info=True)
            self.parent.after(0, lambda: messagebox.showerror("エラー", f"エラーが発生しました:\n{e}"))
        finally:
            self.parent.after(0, lambda: self.run_button.configure(state=tk.NORMAL))
