from collections.abc import Callable, Iterator
import csv
from datetime import date, datetime
import itertools
from typing import Any

from .interface import ReaderProtocol

# 型定義
CastType = int | float | datetime | date | str

# タイムスタンプ判定範囲 (2001-09-09 〜 2065-01-24)
_TS_SEC_MIN = 1_000_000_000
_TS_SEC_MAX = 3_000_000_000
_TS_MS_MIN = 1_000_000_000_000
_TS_MS_MAX = 3_000_000_000_000

# デリミタ判定用のサンプル行数
_SNIFFER_SAMPLE_LINES = 20


def _profile_value(val: str, *, enable_timestamp_cast: bool = True) -> tuple[type, str | None]:
    """文字列値をパースし、最適な型とフォーマット情報を返します。

    戻り値:
        (判定された型, フォーマット文字列またはタイムスタンプ識別子)
    """
    val_stripped = val.strip()
    if not val_stripped:
        return str, None

    # 1. タイムスタンプ (通算秒/ミリ秒)
    if enable_timestamp_cast:
        try:
            val_num = float(val_stripped)
            if _TS_SEC_MIN <= val_num <= _TS_SEC_MAX:
                return datetime, "timestamp_sec"
            if _TS_MS_MIN <= val_num <= _TS_MS_MAX:
                return datetime, "timestamp_ms"
        except (ValueError, OverflowError, OSError):
            pass

    # 2. 整数
    try:
        int(val_stripped)
        return int, None
    except ValueError:
        pass

    # 3. 浮動小数点数
    try:
        float(val_stripped)
        return float, None
    except ValueError:
        pass

    # 4. 日時 (datetime)
    datetime_formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%I:%M:%S %p",
    )
    for fmt in datetime_formats:
        try:
            datetime.strptime(val_stripped, fmt)
            return datetime, fmt
        except ValueError:
            pass

    # 5. 日付 (date)
    date_formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
    )
    for fmt in date_formats:
        try:
            datetime.strptime(val_stripped, fmt)
            return date, fmt
        except ValueError:
            pass

    # ISO 8601 フォールバック
    try:
        datetime.fromisoformat(val_stripped)
        return datetime, None
    except ValueError:
        pass

    return str, None


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
        return val_stripped  # 空文字列（欠損値）はトリミングした空文字列を返す

    target_type, format_str = _profile_value(val_stripped, enable_timestamp_cast=enable_timestamp_cast)
    caster = make_caster(target_type, format_str)
    return caster(val_stripped)


def make_caster(
    target_type: type,
    format_str: str | None = None,
) -> Callable[[str], Any]:
    """指定された型に変換する関数を生成します。

    Args:
        target_type: 変換先の型 (int, float, datetime, date, str)。
        format_str: datetime/date のフォーマット文字列。
            ``"timestamp_sec"`` / ``"timestamp_ms"`` を指定するとUnixタイムスタンプとして扱います。
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
        else:

            def _parse_datetime(x: str) -> datetime:
                xs = x.strip()
                if format_str:
                    try:
                        return datetime.strptime(xs, format_str)
                    except ValueError:
                        pass
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
                    try:
                        return datetime.strptime(xs, fmt)
                    except ValueError:
                        pass
                return datetime.fromisoformat(xs)

            return _parse_datetime
    elif target_type is date:
        if format_str:
            return lambda x: datetime.strptime(x.strip(), format_str).date()
        else:
            return lambda x: datetime.fromisoformat(x.strip()).date()
    else:
        return lambda x: x


def infer_schema(
    samples: list[list[str]],
    *,
    enable_timestamp_cast: bool = True,
) -> list[Callable[[str], Any]]:
    """サンプルデータを元に、各カラムの最適なキャスト関数リストを作成します。

    Args:
        samples: 推論に使用する生文字列の行リスト。
        enable_timestamp_cast: Unixタイムスタンプの推論を行うか。

    Note:
        ``infer_rows`` で指定した行数内で特定カラムがすべて空文字列だった場合、
        そのカラムは ``str`` としてフォールバックされます。
        欠損値が多いデータや型の多様性が高いデータでは ``infer_rows=100`` 〜 ``1000`` 程度を推奨します。
    """
    if not samples:
        return []

    num_cols = len(samples[0])
    casters = []

    for col_idx in range(num_cols):
        inferred_types: list[type] = []
        date_formats: dict[str, int] = {}
        datetime_formats: dict[str, int] = {}

        for row in samples:
            if col_idx >= len(row):
                continue
            val = row[col_idx].strip()
            if not val:
                continue

            target_type, format_str = _profile_value(val, enable_timestamp_cast=enable_timestamp_cast)
            inferred_types.append(target_type)

            # 日付/日時の場合は、フォーマットを集計
            if target_type is datetime and format_str:
                datetime_formats[format_str] = datetime_formats.get(format_str, 0) + 1
            elif target_type is date and format_str:
                date_formats[format_str] = date_formats.get(format_str, 0) + 1

        if not inferred_types:
            casters.append(make_caster(str))
            continue

        unique_types = set(inferred_types)

        # 最も強い型を判定
        if unique_types == {int}:
            casters.append(make_caster(int))
        elif unique_types == {float} or unique_types == {int, float}:
            casters.append(make_caster(float))
        elif unique_types == {datetime} or unique_types == {date, datetime}:
            # date と datetime が混在している場合は datetime に統一して情報損失を防ぐ
            best_fmt = max(datetime_formats, key=lambda k: datetime_formats[k]) if datetime_formats else None
            casters.append(make_caster(datetime, best_fmt))
        elif unique_types == {date}:
            best_fmt = max(date_formats, key=lambda k: date_formats[k]) if date_formats else None
            casters.append(make_caster(date, best_fmt))
        else:
            casters.append(make_caster(str))

    return casters


def _read_sniffer_sample(
    file_path: str,
    n_lines: int = _SNIFFER_SAMPLE_LINES,
    on_warn: Callable[[str], None] | None = None,
) -> str:
    """Sniffer に渡すサンプルを「完全な行」単位で取得します。

    ``f.read(N)`` では行の途中で切れてダブルクオート内改行を誤認識する可能性があるため、
    ``readline()`` を使って完全な行のみを収集します。

    Args:
        file_path: 対象ファイルのパス。
        n_lines: 取得する行数。
        on_warn: 警告メッセージを受け取るコールバック。省略時は無視します。
    """
    try:
        with open(file_path, mode="r", encoding="utf-8", newline="") as f:
            lines = [f.readline() for _ in range(n_lines)]
        return "".join(lines)
    except OSError as e:
        if on_warn is not None:
            on_warn(f"サンプル取得に失敗しました: {e}")
        return ""


class CSVReader(ReaderProtocol):
    """CSVおよびTSVファイル用のリーダー"""

    def __init__(
        self,
        delimiter: str | None = None,
        has_header: bool | None = None,
        auto_cast: bool = True,
        infer_rows: int = 10,
        enable_timestamp_cast: bool = False,
        on_warn: Callable[[str], None] | None = None,
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
            on_warn: 自動判定の失敗など、処理を継続しつつ呼び出し元へ通知したい警告を
                受け取るコールバック関数。省略時は警告を無視します。
        """
        self.delimiter = delimiter
        self.has_header = has_header
        self.auto_cast = auto_cast
        self.infer_rows = infer_rows
        self.enable_timestamp_cast = enable_timestamp_cast
        self.on_warn = on_warn
        self.header: list[str] | None = None

    def _detect_properties(self, file_path: str) -> tuple[str, bool]:
        """ファイルからサンプルを1回だけ読み込み、デリミタとヘッダー有無を判定します。"""
        delim = self.delimiter
        has_header = self.has_header

        # デリミタまたはヘッダーの自動判定が必要な場合のみサンプルをロード
        if delim is None or has_header is None:
            sample = _read_sniffer_sample(file_path, on_warn=self.on_warn)
            if sample:
                if delim is None:
                    try:
                        dialect = csv.Sniffer().sniff(sample)
                        delim = dialect.delimiter
                    except csv.Error:
                        if self.on_warn is not None:
                            self.on_warn("デリミタの自動判定に失敗しました。カンマをデフォルト値として使用します。")
                        delim = ","
                if has_header is None:
                    try:
                        has_header = csv.Sniffer().has_header(sample)
                    except csv.Error:
                        if self.on_warn is not None:
                            self.on_warn("ヘッダーの自動判定に失敗しました。ヘッダーありとして扱います。")
                        has_header = True
            else:
                if delim is None:
                    delim = ","
                if has_header is None:
                    has_header = True

        return delim, has_header

    def _cast_row(
        self,
        row: list[str],
        casters: list[Callable[[str], Any]],
        line_idx: int,
        expected_cols: int,
    ) -> list[Any]:
        """1行のデータを決定したスキーマに沿ってキャストします。"""
        if len(row) != expected_cols:
            raise ValueError(f"行 {line_idx} で列数が一致しません: 期待値 {expected_cols}、取得値 {len(row)}")

        casted_row = []
        for col_idx, val in enumerate(row):
            try:
                if not val.strip():
                    casted_row.append(val.strip())
                else:
                    casted_row.append(casters[col_idx](val))
            except ValueError as e:
                msg = (
                    f"行 {line_idx} の列 {col_idx} で型キャストエラーが発生しました: "
                    f"'{val}' を変換できません。詳細: {e}"
                )
                raise ValueError(msg)
        return casted_row

    def read(self, file_path: str) -> Iterator[list[Any]]:
        """ファイルを開いて行データを読み込みます。

        注意:
            ヘッダー行が検出された場合、それはイテレータからは yield されず、
            ``self.header`` に格納されます。
        """
        delim, has_header = self._detect_properties(file_path)

        with open(file_path, mode="r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f, delimiter=delim)

            # 空ファイルチェック
            try:
                first_row = next(reader)
            except StopIteration:
                raise ValueError("ファイルが空です")

            expected_cols = len(first_row)

            # ヘッダーの退避とイテレータの準備
            if has_header:
                self.header = first_row
                start_line = 2
                data_reader: Iterator[list[str]] = reader
            else:
                self.header = None
                start_line = 1
                data_reader = itertools.chain([first_row], reader)

            if not self.auto_cast:
                for line_idx, row in enumerate(data_reader, start=start_line):
                    if len(row) != expected_cols:
                        raise ValueError(
                            f"行 {line_idx} で列数が一致しません: 期待値 {expected_cols}、取得値 {len(row)}"
                        )
                    yield row
                return

            # スキーマ判定のため、最初の数行をバッファリング
            sample_rows: list[tuple[int, list[str]]] = []
            for line_idx, row in enumerate(data_reader, start=start_line):
                if len(row) != expected_cols:
                    raise ValueError(f"行 {line_idx} で列数が一致しません: 期待値 {expected_cols}、取得値 {len(row)}")
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
