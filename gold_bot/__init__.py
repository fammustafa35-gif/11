"""Backtesting components for a paper-only XAUUSD strategy."""

from .backtest import BacktestConfig, BacktestResult, run_backtest
from .data import Candle, load_candles

__all__ = ["BacktestConfig", "BacktestResult", "Candle", "load_candles", "run_backtest"]
