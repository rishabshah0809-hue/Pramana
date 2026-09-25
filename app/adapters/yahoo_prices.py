"""Delayed NSE prices from Yahoo Finance through the yfinance library (trust tier 2).

Terms note (DATA_SOURCES.md): automated access conflicts with Yahoo's terms. The owner
chose to use it until Angel One is connected. Prices are always labelled "Delayed · Yahoo".
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.timeutil import IST

SOURCE_ID = "yahoo_prices"


@dataclass(frozen=True)
class Bar:
    symbol: str          # NSE symbol, without ".NS"
    interval: str        # "1d" or "15m"
    start: datetime      # bar start (tz-aware)
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class FetchResult:
    status: str                                  # ok | blocked | timeout | error | missing
    message: str
    bars: list[Bar] = field(default_factory=list)
    rows_received: int = 0
    rows_valid: int = 0
    no_data: list[str] = field(default_factory=list)  # symbols Yahoo returned nothing for
    error: Exception | None = None                    # kept for the log file only


def _download(tickers: list[str], period: str, interval: str):
    import yfinance as yf

    return yf.download(tickers, period=period, interval=interval, group_by="ticker",
                       auto_adjust=False, progress=False, threads=True,
                       multi_level_index=True, timeout=20)


def _yf_errors() -> dict:
    try:
        import yfinance.shared as shared

        return dict(getattr(shared, "_ERRORS", {}) or {})
    except Exception:
        return {}


def _valid(o, h, l, c, v) -> bool:
    try:
        vals = [float(x) for x in (o, h, l, c)]
    except (TypeError, ValueError):
        return False
    if any(x != x or x <= 0 for x in vals):  # NaN or non-positive
        return False
    o, h, l, c = vals
    if h < max(o, c, l) or l > min(o, c, h):
        return False
    return v is None or v != v or float(v) >= 0


def _to_ist(ts) -> datetime:
    dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt


def _parse(df, symbols: list[str], interval: str, result: FetchResult, keep_last_only: bool):
    seen = set()
    if df is None or getattr(df, "empty", True):
        return seen
    for sym in symbols:
        ticker = f"{sym}.NS"
        if ticker not in df.columns.get_level_values(0):
            continue
        sub = df[ticker].dropna(how="all")
        rows = list(sub.itertuples())
        if keep_last_only and rows:
            rows = rows[-1:]
        for r in rows:
            result.rows_received += 1
            vol = getattr(r, "Volume", None)
            if not _valid(r.Open, r.High, r.Low, r.Close, vol):
                continue
            result.rows_valid += 1
            seen.add(sym)
            result.bars.append(Bar(sym, interval, _to_ist(r.Index), float(r.Open), float(r.High),
                                   float(r.Low), float(r.Close),
                                   0.0 if vol is None or vol != vol else float(vol)))
    return seen


def _classify(exc: Exception) -> tuple[str, str]:
    name = type(exc).__name__
    text = str(exc).lower()
    if "ratelimit" in name.lower() or "too many requests" in text or "429" in text:
        return "blocked", "Yahoo is limiting requests right now. The app will try again later."
    if "timeout" in name.lower() or "timed out" in text:
        return "timeout", "Yahoo did not answer in time. Check your internet; the app will retry."
    if isinstance(exc, (ConnectionError, OSError)) or "connect" in text or "resolve" in text:
        return "error", "Could not reach Yahoo. Check your internet connection."
    return "error", "Yahoo returned an unexpected response. Details are in the log file."


def fetch(symbols: list[str], downloader=_download) -> FetchResult:
    """Daily bars (last 5 sessions) plus the latest 15-minute bar for each NSE symbol."""
    result = FetchResult(status="ok", message="")
    tickers = [f"{s}.NS" for s in symbols]
    try:
        daily = downloader(tickers, "5d", "1d")
        intraday = downloader(tickers, "1d", "15m")
    except Exception as exc:  # noqa: BLE001 — every failure becomes a plain message
        result.status, result.message = _classify(exc)
        result.error = exc
        return result
    got = _parse(daily, symbols, "1d", result, keep_last_only=False)
    got |= _parse(intraday, symbols, "15m", result, keep_last_only=True)
    result.no_data = [s for s in symbols if s not in got]

    if not got:
        errors = " ".join(str(v) for v in _yf_errors().values()).lower()
        if "rate" in errors or "too many" in errors:
            result.status = "blocked"
            result.message = "Yahoo is limiting requests right now. The app will try again later."
        else:
            result.status = "missing"
            result.message = ("Yahoo returned no prices. You may be offline, or Yahoo may be "
                              "unavailable. The app will retry.")
    elif result.no_data:
        result.message = (f"Prices received for {len(got)} of {len(symbols)} companies. "
                          f"No data for: {', '.join(result.no_data)}.")
    else:
        result.message = f"Prices received for all {len(symbols)} companies."
    return result
