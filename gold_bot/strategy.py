"""Indicator calculations and long-only entry/exit rules."""

from __future__ import annotations

from dataclasses import dataclass


def ema(values: list[float], period: int) -> list[float | None]:
    if period < 1:
        raise ValueError("EMA period must be positive")
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    current = sum(values[:period]) / period
    result[period - 1] = current
    multiplier = 2 / (period + 1)
    for index in range(period, len(values)):
        current = (values[index] - current) * multiplier + current
        result[index] = current
    return result


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return result
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    avg_gain, avg_loss = sum(gains[:period]) / period, sum(losses[:period]) / period
    result[period] = 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for index in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[index]) / period
        avg_loss = (avg_loss * (period - 1) + losses[index]) / period
        result[index + 1] = 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return result


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return result
    ranges = [highs[0] - lows[0]] + [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])) for i in range(1, len(closes))]
    current = sum(ranges[1 : period + 1]) / period
    result[period] = current
    for index in range(period + 1, len(closes)):
        current = (current * (period - 1) + ranges[index]) / period
        result[index] = current
    return result


@dataclass(frozen=True)
class Signal:
    enter_long: bool
    exit_long: bool


def signal_at(index: int, fast: list[float | None], slow: list[float | None], momentum: list[float | None]) -> Signal:
    if None in (fast[index], slow[index], momentum[index]):
        return Signal(False, False)
    return Signal(enter_long=fast[index] > slow[index] and 50 <= momentum[index] < 70, exit_long=fast[index] < slow[index] or momentum[index] > 75)
