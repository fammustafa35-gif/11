"""A deterministic, long-only paper backtester for XAUUSD."""

from __future__ import annotations

from dataclasses import dataclass

from .data import Candle
from .strategy import atr, ema, rsi, signal_at


@dataclass(frozen=True)
class BacktestConfig:
    initial_balance: float = 10_000
    risk_per_trade: float = 0.01
    fast_ema: int = 20
    slow_ema: int = 50
    atr_period: int = 14
    stop_atr_multiple: float = 1.5
    reward_risk: float = 2.0
    contract_multiplier: float = 100.0
    commission_per_trade: float = 0.0

    def __post_init__(self) -> None:
        if self.initial_balance <= 0 or not 0 < self.risk_per_trade <= 0.02:
            raise ValueError("balance must be positive and risk_per_trade must be in (0, 0.02]")
        if self.fast_ema >= self.slow_ema or min(self.fast_ema, self.atr_period) < 1:
            raise ValueError("EMA periods must be positive and fast_ema must be below slow_ema")
        if min(self.stop_atr_multiple, self.reward_risk, self.contract_multiplier) <= 0 or self.commission_per_trade < 0:
            raise ValueError("risk multiples and contract multiplier must be positive")


@dataclass(frozen=True)
class Trade:
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    quantity: float
    reason: str
    pnl: float


@dataclass(frozen=True)
class BacktestResult:
    final_balance: float
    max_drawdown: float
    trades: list[Trade]


def run_backtest(candles: list[Candle], config: BacktestConfig = BacktestConfig()) -> BacktestResult:
    """Run signals only on completed candles; entry is placed at the next open."""
    if len(candles) <= max(config.slow_ema, config.atr_period) + 1:
        raise ValueError("not enough candles for the configured indicators")
    closes, highs, lows = [c.close for c in candles], [c.high for c in candles], [c.low for c in candles]
    fast, slow, volatility = ema(closes, config.fast_ema), ema(closes, config.slow_ema), atr(highs, lows, closes, config.atr_period)
    momentum = rsi(closes)
    balance, peak, drawdown, trades = config.initial_balance, config.initial_balance, 0.0, []
    position: dict[str, float | str] | None = None

    for index in range(1, len(candles)):
        candle = candles[index]
        if position:
            stop, target = float(position["stop"]), float(position["target"])
            # Conservative ambiguity rule: if both levels occur in one candle, stop wins.
            if candle.low <= stop:
                position = _close(position, candle.timestamp, stop, "stop_loss", config, trades)
            elif candle.high >= target:
                position = _close(position, candle.timestamp, target, "take_profit", config, trades)
            elif signal_at(index - 1, fast, slow, momentum).exit_long:
                position = _close(position, candle.timestamp, candle.open, "signal_exit", config, trades)
            if position is None:
                balance += trades[-1].pnl
                peak = max(peak, balance)
                drawdown = max(drawdown, (peak - balance) / peak)
        if position is None and index < len(candles) - 1:
            prior_atr = volatility[index - 1]
            if prior_atr and signal_at(index - 1, fast, slow, momentum).enter_long:
                entry, stop = candle.open, candle.open - prior_atr * config.stop_atr_multiple
                cash_risk = balance * config.risk_per_trade
                quantity = cash_risk / ((entry - stop) * config.contract_multiplier)
                position = {"time": candle.timestamp, "entry": entry, "stop": stop, "target": entry + (entry - stop) * config.reward_risk, "quantity": quantity}
    if position:
        final = candles[-1]
        _close(position, final.timestamp, final.close, "end_of_data", config, trades)
        balance += trades[-1].pnl
        peak = max(peak, balance)
        drawdown = max(drawdown, (peak - balance) / peak)
    return BacktestResult(balance, drawdown, trades)


def _close(position: dict[str, float | str], exit_time: str, exit_price: float, reason: str, config: BacktestConfig, trades: list[Trade]) -> None:
    pnl = (exit_price - float(position["entry"])) * float(position["quantity"]) * config.contract_multiplier - config.commission_per_trade
    trades.append(Trade(str(position["time"]), exit_time, float(position["entry"]), exit_price, float(position["quantity"]), reason, pnl))
    return None
