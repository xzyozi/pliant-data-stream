import csv
from datetime import date, datetime
import itertools
import logging
from typing import Any, Callable, Iterator, List, Optional, Union

from .interface import ReaderProtocol

logger = logging.getLogger(__name__)

# 型定義
CastType = Union[int, float, datetime, date, str]

# タイムスタンプ判定範囲 (2001-09-09 〜 2065-01-24)
_TS_SEC_MIN = 1_000_000_000
_TS_SEC_MAX = 3_000_000_000
_TS_MS_MIN = 1_000_000_000_000
_TS_MS_MAX = 3_000_000_000_000

# デリミタ判定用のサンプル行数
_SNIFFER_SAMPLE_LINES = 20


def auto_cast_value(val: str, *, enable_timestamp_cast: bool = True) -> CastType:
    """文字列値を最適なデータ型（int, float, datetime, date, str）に変換します。

    変換を試みる順序:
    1. タイムスタンプ (秒・ミリ秒)  ※ enable_timestamp_cast=True の場合のみ
    2. 整数 (int)
    3. 浮動小数点数 (float)
    4. 日時 (datetime)
    5. 日付 (date)
    6. 元の文字列 (str)

    Args:
        val: 変換対象の文字列。
        enable_timestamp_cast: Trueの場合、10桁(秒)・13桁(ミリ秒)の数値を
            Unixタイムスタンプとしてdatetimeに変換します。デフォルトは ``True``。
            業務IDや電話番号など10桁の数値が混在するデータではFalseを推奨します。
    """
    val_stripped = val.strip()
    if not val_stripped:
        return val  # 空文字列（欠損値）はそのまま返す

    # 1. タイムスタンプ (通算秒/ミリ秒)
    if enable_timestamp_cast:
        try:
            val_num = float(val_stripped)
            if _TS_SEC_MIN <= val_num <= _TS_SEC_MAX:
                return datetime.fromtimestamp(val_num)
            if _TS_MS_MIN <= val_num <= _TS_MS_MAX:
                return datetime.fromtimestamp(val_num / 1000.0)
        except (ValueError, OverflowError, OSError):
            pass

    # 2. 整数
    try:
        return int(val_stripped)
    except ValueError:
        pass

    # 3. 浮動小数点数
    try:
        return float(val_stripped)
    except ValueError:
        pass

    # 4. 日時 (datetime) — strptime で主要フォーマットを試行した後、fromisoformat にフォールバック
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

    # 5. 日付 (date)
    date_formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
    )
    for fmt in date_formats:
        try:
            return datetime.strptime(val_stripped, fmt).date()
        except ValueError:
            pass

    # ISO 8601 フォールバック (Python 3.11+ では fromisoformat が大幅に拡張されており高速)
    try:
        return datetime.fromisoformat(val_stripped)
    except ValueError:
        pass

    # 6. 文字列フォールバック
    return val


def make_caster(
    target_type: type,
    format_str: Optional[str] = None,
    *,
    enable_timestamp_cast: bool = True,
) -> Callable[[str], Any]:
    """指定された型に変換する関数を生成します。

    Args:
        target_type: 変換先の型 (int, float, datetime, date, str)。
        format_str: datetime/date のフォーマット文字列。
            ``"timestamp_sec"`` / ``"timestamp_ms"`` を指定するとUnixタイムスタンプとして扱います。
        enable_timestamp_cast: タイムスタンプ変換を有効にするか（CSVReader の設定と連動します）。
    """
    if target_type is int:
        return lambda x: int(x.strip())
    elif target_type is float:
        return lambda x: float(x.strip())
    elif target_type is datetime:
        if format_str == "timestamp_sec":
            return lambda x: datetime.fromtimestamp(float(x.strip()))
        elif format_str == "timestamp_ms":
            return lambda x: datetime.fromtimestamp(float(x.strip()) / 1000.0)
        elif format_str:
            return lambda x: datetime.strptime(x.strip(), format_str)
        else:
            # fromisoformat は Python 3.11+ で大幅拡張済み。strptime より高速。
            return lambda x: datetime.fromisoformat(x.strip())
    elif target_type is date:
        if format_str:
            return lambda x: datetime.strptime(x.strip(), format_str).date()
        else:
            return lambda x: datetime.fromisoformat(x.strip()).date()
    else:
        # str
        return lambda x: x


def infer_schema(
    samples: List[List[str]],
    *,
    enable_timestamp_cast: bool = True,
) -> List[Callable[[str], Any]]:
    """サンプルデータを元に、各カラムの最適なキャスト関数リストを作成します。

    Args:
        samples: 推論に使用する生文字列の行リスト。
        enable_timestamp_cast: Unixタイムスタンプの推論を行うか。

    Note:
        ``infer_rows`` で指定した行数内で特定カラムがすべて空文字列だった場合、
        そのカラムは ``str`` としてフォールバックされます。
        欠損率が高いデータでは ``infer_rows=100`` 〜 ``1000`` 程度を推奨します。
    """
    if not samples:
        return []

    num_cols = len(samples[0])
    casters = []

    for col_idx in range(num_cols):
        inferred_types: List[type] = []
        date_formats: dict[str, int] = {}
        datetime_formats: dict[str, int] = {}

        for row in samples:
            if col_idx >= len(row):
                continue
            val = row[col_idx].strip()
            if not val:
                continue

            casted = auto_cast_value(val, enable_timestamp_cast=enable_timestamp_cast)
            inferred_types.append(type(casted))

            # 日付/日時の場合は、どのフォーマットでパースできたかも集計しておく
            if isinstance(casted, datetime):
                _count_datetime_format(val, datetime_formats, enable_timestamp_cast)
            elif isinstance(casted, date):
                _count_date_format(val, date_formats)

        if not inferred_types:
            casters.append(make_caster(str))
            continue

        unique_types = set(inferred_types)

        # 最も強い型を判定
        if unique_types == {int}:
            casters.append(make_caster(int, enable_timestamp_cast=enable_timestamp_cast))
        elif unique_types == {float} or unique_types == {int, float}:
            casters.append(make_caster(float, enable_timestamp_cast=enable_timestamp_cast))
        elif unique_types == {datetime}:
            best_fmt = max(datetime_formats, key=lambda k: datetime_formats[k]) if datetime_formats else None
            casters.append(make_caster(datetime, best_fmt, enable_timestamp_cast=enable_timestamp_cast))
        elif unique_types == {date}:
            best_fmt = max(date_formats, key=lambda k: date_formats[k]) if date_formats else None
            casters.append(make_caster(date, best_fmt, enable_timestamp_cast=enable_timestamp_cast))
        else:
            casters.append(make_caster(str, enable_timestamp_cast=enable_timestamp_cast))

    return casters


def _count_datetime_format(val: str, counters: dict[str, int], enable_timestamp_cast: bool) -> None:
    """datetime 型と判定された値のフォーマットを集計します。"""
    if enable_timestamp_cast:
        try:
            val_num = float(val)
            if _TS_SEC_MIN <= val_num <= _TS_SEC_MAX:
                counters["timestamp_sec"] = counters.get("timestamp_sec", 0) + 1
                return
            elif _TS_MS_MIN <= val_num <= _TS_MS_MAX:
                counters["timestamp_ms"] = counters.get("timestamp_ms", 0) + 1
                return
        except ValueError:
            pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%I:%M:%S %p"):
        try:
            datetime.strptime(val, fmt)
            counters[fmt] = counters.get(fmt, 0) + 1
            return
        except ValueError:
            pass


def _count_date_format(val: str, counters: dict[str, int]) -> None:
    """date 型と判定された値のフォーマットを集計します。"""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            datetime.strptime(val, fmt)
            counters[fmt] = counters.get(fmt, 0) + 1
            return
        except ValueError:
            pass


def _read_sniffer_sample(file_path: str, n_lines: int = _SNIFFER_SAMPLE_LINES) -> str:
    """Sniffer に渡すサンプルを「完全な行」単位で取得します。

    ``f.read(N)`` では行の途中で切れてダブルクオート内改行を誤認識する可能性があるため、
    ``readline()`` を使って完全な行のみを収集します。
    """
    try:
        with open(file_path, mode="r", encoding="utf-8", newline="") as f:
            lines = [f.readline() for _ in range(n_lines)]
        return "".join(lines)
    except OSError as e:
        logger.warning("サンプル取得に失敗しました: %s", e)
        return ""


class CSVReader(ReaderProtocol):
    """CSVおよびTSVファイル用のリーダー"""

    def __init__(
        self,
        delimiter: Optional[str] = None,
        has_header: Optional[bool] = None,
        auto_cast: bool = True,
        infer_rows: int = 10,
        enable_timestamp_cast: bool = False,
    ) -> None:
        """
        Args:
            delimiter: 区切り文字。Noneの場合は自動判定を試みます。
            has_header: カラム名行（ヘッダー）の有無。Noneの場合はSnifferによる自動判定を試みます。
            auto_cast: Trueの場合、最初の infer_rows 行からスキーマを推論し、型変換を適用します。
            infer_rows: スキーマ推論に使用するデータの行数。
                欠損値が多いデータや型の多様性が高いデータでは 100〜1000 程度を推奨します。
            enable_timestamp_cast: Trueの場合、10桁(秒)/13桁(ミリ秒)の数値をUnixタイムスタンプ
                として datetime に変換します。デフォルトは ``False``。
                業務ID・電話番号など10桁の数値が混在するデータでは無効のまま使用してください。
        """
        self.delimiter = delimiter
        self.has_header = has_header
        self.auto_cast = auto_cast
        self.infer_rows = infer_rows
        self.enable_timestamp_cast = enable_timestamp_cast

    def _detect_delimiter(self, file_path: str) -> str:
        """指定のパスのファイルからデリミタを自動判定します。

        ``f.read(N)`` ではダブルクォートで囲まれた改行の途中でサンプルが切れる場合があるため、
        完全な行単位でサンプルを収集して ``csv.Sniffer`` に渡します。
        """
        if self.delimiter is not None:
            return self.delimiter

        sample = _read_sniffer_sample(file_path)
        if sample:
            try:
                dialect = csv.Sniffer().sniff(sample)
                return dialect.delimiter
            except csv.Error:
                logger.warning("デリミタの自動判定に失敗しました。カンマをデフォルト値として使用します。")
        return ","

    def _detect_has_header(self, file_path: str) -> bool:
        """指定のファイルにヘッダー（カラム名行）が存在するか判定します。

        ``csv.Sniffer`` を使って判定します。失敗した場合はヘッダーありとして扱います。
        """
        if self.has_header is not None:
            return self.has_header

        sample = _read_sniffer_sample(file_path)
        if sample:
            try:
                return csv.Sniffer().has_header(sample)
            except csv.Error:
                logger.warning("ヘッダーの自動判定に失敗しました。ヘッダーありとして扱います。")
        return True

    def _cast_row(
        self,
        row: List[str],
        casters: List[Callable[[str], Any]],
        line_idx: int,
        expected_cols: int,
    ) -> List[Any]:
        """1行のデータを決定したスキーマに沿ってキャストします。"""
        if len(row) != expected_cols:
            raise ValueError(f"Column count mismatch at line {line_idx}: expected {expected_cols}, got {len(row)}")

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
                    f"Type cast error at line {line_idx}, column {col_idx}: '{val}' cannot be converted. Details: {e}"
                )
        return casted_row

    def read(self, file_path: str) -> Iterator[List[Any]]:
        """ファイルを開いて行データを読み込みます。"""
        delim = self._detect_delimiter(file_path)
        has_header = self._detect_has_header(file_path)

        with open(file_path, mode="r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f, delimiter=delim)

            # 空ファイルチェック
            try:
                first_row = next(reader)
            except StopIteration:
                raise ValueError("Empty file")

            expected_cols = len(first_row)

            # データ読み出し用イテレータの準備
            # itertools.chain を使うことで、内部ジェネレータ定義を排除しC実装レベルの速度で結合する
            if has_header:
                yield first_row
                start_line = 2
                data_reader: Iterator[List[str]] = reader
            else:
                start_line = 1
                data_reader = itertools.chain([first_row], reader)

            if not self.auto_cast:
                for line_idx, row in enumerate(data_reader, start=start_line):
                    if len(row) != expected_cols:
                        raise ValueError(
                            f"Column count mismatch at line {line_idx}: expected {expected_cols}, got {len(row)}"
                        )
                    yield row
                return

            # スキーマ判定のため、最初の数行をバッファリング
            sample_rows: List[tuple[int, List[str]]] = []
            for line_idx, row in enumerate(data_reader, start=start_line):
                if len(row) != expected_cols:
                    raise ValueError(
                        f"Column count mismatch at line {line_idx}: expected {expected_cols}, got {len(row)}"
                    )
                sample_rows.append((line_idx, row))
                if len(sample_rows) >= self.infer_rows:
                    break

            # サンプル行を元にスキーマ判定
            raw_samples = [r for _, r in sample_rows]
            casters = infer_schema(raw_samples, enable_timestamp_cast=self.enable_timestamp_cast)

            # バッファリングしたサンプル行をキャストして出力
            for line_idx, row in sample_rows:
                yield self._cast_row(row, casters, line_idx, expected_cols)

            # 残りの行を読み込みながらキャスト出力
            next_start_line = start_line + len(sample_rows)
            for line_idx, row in enumerate(data_reader, start=next_start_line):
                yield self._cast_row(row, casters, line_idx, expected_cols)
