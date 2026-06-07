import logging
import tkinter as tk

from app import PliantApplication
from windows.main_window import MainWindow

# ログ設定の初期化
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Initializing Pliant Data Stream GUI...")

    # Tkinter root の作成
    root = tk.Tk()

    # アプリケーション本体のインスタンス作成
    app = PliantApplication(root)

    # メイン画面の構築
    MainWindow(root, app)

    # 閉じるボタンのイベント紐付け
    root.protocol("WM_DELETE_WINDOW", app.on_closing)

    # アプリケーションの開始
    app.on_ready()

    # メインループ
    root.mainloop()


if __name__ == "__main__":
    main()
