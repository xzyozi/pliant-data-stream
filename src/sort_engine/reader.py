import csv
from datetime import date, datetime
from typing import Any, Callable, Iterator, List, Optional, Union

from .interface import ReaderProtocol

# 型定義
CastType = Union[int, float, datetime, date, str]


def auto_cast_value(val: str) -> CastType:
    """文字列値を最適なデータ型（int, float, datetime, date, str）に変換します。

    変換を試みる順序:
    1. 整数 (int)
    2. 浮動小数点数 (float)
    3. 日時 (datetime)
    4. 日付 (date)
    5. 元の文字列 (str)
    """
    val_stripped = val.strip()
    if not val_stripped:
        return val  # 空文字列（欠損値）はそのまま返す

    # 1. 整数
    try:
        return int(val_stripped)
    except ValueError:
        pass

    # 2. 浮動小数点数
    try:
        return float(val_stripped)
    except ValueError:
        pass

    # 3. 日時 (datetime)
    datetime_formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%I:%M:%S %p",
    )
    for fmt in datetime_formats:
        try:
            return datetime.strptime(val_stripped, fmt)
        except ValueError:
            pass

    # 4. 日付 (date)
    date_formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
    )
    for fmt in date_formats:
        try:
            return datetime.strptime(val_stripped, fmt).date()
        except ValueError:
            pass

    try:
        return datetime.fromisoformat(val_stripped)
    except ValueError:
        pass

    # 5. 文字列フォールバック
    return val


def make_caster(target_type: type, format_str: Optional[str] = None) -> Callable[[str], Any]:
    """指定された型に変換する関数を生成します。"""
    if target_type is int:
        return lambda x: int(x.strip())
    elif target_type is float:
        return lambda x: float(x.strip())
    elif target_type is datetime:
        if format_str:
            return lambda x: datetime.strptime(x.strip(), format_str)
        else:
            return lambda x: datetime.fromisoformat(x.strip())
    elif target_type is date:
        if format_str:
            return lambda x: datetime.strptime(x.strip(), format_str).date()
        else:
            return lambda x: datetime.fromisoformat(x.strip()).date()
    else:
        # str
        return lambda x: x


def infer_schema(samples: List[List[str]]) -> List[Callable[[str], Any]]:
    """サンプルデータを元に、各カラムの最適なキャスト関数リストを作成します。"""
    if not samples:
        return []

    num_cols = len(samples[0])
    casters = []

    for col_idx in range(num_cols):
        inferred_types = []
        date_formats = {}
        datetime_formats = {}

        for row in samples:
            if col_idx >= len(row):
                continue
            val = row[col_idx].strip()
            if not val:
                continue

            casted = auto_cast_value(val)
            inferred_types.append(type(casted))

            # 日付/日時の場合は、どのフォーマットでパースできたかも集計しておく
            if isinstance(casted, datetime):
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%I:%M:%S %p"):
                    try:
                        datetime.strptime(val, fmt)
                        datetime_formats[fmt] = datetime_formats.get(fmt, 0) + 1
                        break
                    except ValueError:
                        pass
            elif isinstance(casted, date):
                for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
                    try:
                        datetime.strptime(val, fmt)
                        date_formats[fmt] = date_formats.get(fmt, 0) + 1
                        break
                    except ValueError:
                        pass

        if not inferred_types:
            casters.append(make_caster(str))
            continue

        unique_types = set(inferred_types)

        # 最も強い型を判定
        if unique_types == {int}:
            casters.append(make_caster(int))
        elif unique_types == {float} or unique_types == {int, float}:
            casters.append(make_caster(float))
        elif unique_types == {datetime}:
            best_fmt = max(datetime_formats, key=datetime_formats.get) if datetime_formats else None
            casters.append(make_caster(datetime, best_fmt))
        elif unique_types == {date}:
            best_fmt = max(date_formats, key=date_formats.get) if date_formats else None
            casters.append(make_caster(date, best_fmt))
        else:
            casters.append(make_caster(str))

    return casters


class CSVReader(ReaderProtocol):
    """CSVおよびTSVファイル用のリーダー"""

    def __init__(
        self,
        delimiter: Optional[str] = None,
        auto_cast: bool = True,
        infer_rows: int = 10,
    ) -> None:
        """
        Args:
            delimiter: 区切り文字。Noneの場合は自動判定を試みます。
            auto_cast: Trueの場合、最初の infer_rows 行からスキーマを推論し、型変換を適用します。
            infer_rows: スキーマ推論に使用するデータの行数。
        """
        self.delimiter = delimiter
        self.auto_cast = auto_cast
        self.infer_rows = infer_rows

    def read(self, file_path: str) -> Iterator[List[Any]]:
        """ファイルを開いて行データを読み込みます。"""
        delim = self.delimiter

        # delimiterが指定されていない場合は csv.Sniffer による自動判定を試みる
        if delim is None:
            try:
                with open(file_path, mode="r", encoding="utf-8", newline="") as f:
                    sample = f.read(4096)
                    if sample:
                        dialect = csv.Sniffer().sniff(sample)
                        delim = dialect.delimiter
                    else:
                        delim = ","
            except Exception:
                delim = ","

        with open(file_path, mode="r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f, delimiter=delim)

            # 空ファイルチェックとヘッダー取得
            try:
                header = next(reader)
            except StopIteration:
                raise ValueError("Empty file")

            yield header
            expected_cols = len(header)

            if not self.auto_cast:
                for line_idx, row in enumerate(reader, start=2):
                    if len(row) != expected_cols:
                        raise ValueError(
                            f"Column count mismatch at line {line_idx}: expected {expected_cols}, got {len(row)}"
                        )
                    yield row
                return

            # スキーマ判定のため、最初の数行をバッファリング
            sample_rows = []
            for line_idx, row in enumerate(reader, start=2):
                if len(row) != expected_cols:
                    raise ValueError(
                        f"Column count mismatch at line {line_idx}: expected {expected_cols}, got {len(row)}"
                    )
                sample_rows.append((line_idx, row))
                if len(sample_rows) >= self.infer_rows:
                    break

            # サンプル行を元にスキーマ判定
            raw_samples = [r for _, r in sample_rows]
            casters = infer_schema(raw_samples)

            # バッファリングしたサンプル行をキャストして出力
            for line_idx, row in sample_rows:
                casted_row = []
                for col_idx, val in enumerate(row):
                    try:
                        if not val.strip():
                            # 空文字列はそのまま
                            casted_row.append(val)
                        else:
                            casted_row.append(casters[col_idx](val))
                    except ValueError as e:
                        raise ValueError(
                            f"Type cast error at line {line_idx}, "
                            f"column {col_idx}: '{val}' cannot be converted. "
                            f"Details: {e}"
                        )
                yield casted_row

            # 残りの行を読み込みながらキャスト出力
            start_line = 2 + len(sample_rows)
            for line_idx, row in enumerate(reader, start=start_line):
                if len(row) != expected_cols:
                    raise ValueError(
                        f"Column count mismatch at line {line_idx}: expected {expected_cols}, got {len(row)}"
                    )

                casted_row = []
                for col_idx, val in enumerate(row):
                    try:
                        if not val.strip():
                            casted_row.append(val)
                        else:
                            casted_row.append(casters[col_idx](val))
                    except ValueError as e:
                        raise ValueError(
                            f"Type cast error at line {line_idx}, "
                            f"column {col_idx}: '{val}' cannot be converted. "
                            f"Details: {e}"
                        )
                yield casted_row
