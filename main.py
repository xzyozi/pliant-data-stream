import os
import sys

# srcディレクトリをPythonのモジュール検索パスに追加
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from src.__main__ import main

if __name__ == "__main__":
    main()
