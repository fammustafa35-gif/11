"""CSV input validation for OHLC(XAUUSD) candles."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


def load_candles(path: str | Path) -> list[Candle]:
    """Load ascending OHLCV candles, rejecting malformed market data early."""
    with Path(path).open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        required = {"timestamp", "open", "high", "low", "close"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("CSV must include timestamp,open,high,low,close columns")

        candles: list[Candle] = []
        for number, row in enumerate(reader, start=2):
            try:
                candle = Candle(
                    timestamp=row["timestamp"].strip(),
                    open=float(row["open"]), high=float(row["high"]),
                    low=float(row["low"]), close=float(row["close"]),
                    volume=float(row.get("volume") or 0),
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid numeric data on CSV line {number}") from exc
            if not candle.timestamp or min(candle.open, candle.high, candle.low, candle.close) <= 0:
                raise ValueError(f"non-positive or missing price on CSV line {number}")
            if candle.low > min(candle.open, candle.close) or candle.high < max(candle.open, candle.close):
                raise ValueError(f"inconsistent OHLC range on CSV line {number}")
            if candles and candle.timestamp <= candles[-1].timestamp:
                raise ValueError(f"timestamps must be strictly ascending (line {number})")
            candles.append(candle)
    if not candles:
        raise ValueError("CSV has no candle rows")
    return candles
