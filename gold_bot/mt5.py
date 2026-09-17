"""MetaTrader 5 adapter with explicit live-trading safety controls.

The MetaTrader5 package is imported only when this adapter is started, so CSV
backtests remain dependency-free.  Use a demo account before `--execute`.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .data import Candle
from .strategy import atr, ema, rsi, signal_at


@dataclass(frozen=True)
class MT5SafetyConfig:
    risk_per_trade: float = 0.005
    daily_loss_limit: float = 0.02
    max_open_positions: int = 1
    max_trades_per_day: int = 3
    max_spread_points: int = 100
    magic: int = 260917
    deviation_points: int = 20
    trailing_atr_multiple: float = 1.0
    log_path: str = "mt5_gold_bot.jsonl"

    def __post_init__(self) -> None:
        if not 0 < self.risk_per_trade <= 0.01 or not 0 < self.daily_loss_limit <= 0.05:
            raise ValueError("risk_per_trade must be <= 1% and daily_loss_limit must be <= 5%")
        if min(self.max_open_positions, self.max_trades_per_day, self.max_spread_points, self.deviation_points) < 1:
            raise ValueError("position, trade, spread, and deviation limits must be positive")
        if self.trailing_atr_multiple <= 0:
            raise ValueError("trailing_atr_multiple must be positive")


def is_gold_symbol(name: str) -> bool:
    """Recognise broker suffixes/prefixes for gold, e.g. XAUUSDm and GOLD.pro."""
    normalized = "".join(character for character in name.upper() if character.isalnum())
    return "XAU" in normalized or "GOLD" in normalized


def gold_symbols(mt5: Any) -> list[str]:
    return [symbol.name for symbol in mt5.symbols_get() or [] if is_gold_symbol(symbol.name)]


class MT5GoldBot:
    """One-cycle MT5 runner; call repeatedly from a scheduler, never concurrently."""

    def __init__(self, safety: MT5SafetyConfig, *, execute: bool = False) -> None:
        self.safety = safety
        self.execute = execute
        self.mt5: Any = None

    def connect(self) -> None:
        import MetaTrader5 as mt5

        self.mt5 = mt5
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialization failed: {mt5.last_error()}")

    def shutdown(self) -> None:
        if self.mt5:
            self.mt5.shutdown()

    def run_once(self, requested_symbols: list[str] | None = None) -> list[dict[str, Any]]:
        if self.mt5 is None:
            raise RuntimeError("call connect() before run_once()")
        symbols = requested_symbols or gold_symbols(self.mt5)
        if not symbols:
            raise RuntimeError("no gold symbols found; check the broker Market Watch list")
        events = [self._trail_position(symbol) for symbol in symbols]
        for symbol in symbols:
            events.append(self._consider_entry(symbol))
        for event in events:
            self._log(event)
        return events

    def _consider_entry(self, symbol: str) -> dict[str, Any]:
        if not is_gold_symbol(symbol):
            return self._event(symbol, "blocked", "not_a_gold_symbol")
        if not self.mt5.symbol_select(symbol, True):
            return self._event(symbol, "blocked", "symbol_unavailable")
        allowed, reason = self._entry_allowed(symbol)
        if not allowed:
            return self._event(symbol, "blocked", reason)
        candles = self._candles(symbol)
        closes, highs, lows = [c.close for c in candles], [c.high for c in candles], [c.low for c in candles]
        fast, slow, momentum, volatility = ema(closes, 20), ema(closes, 50), rsi(closes), atr(highs, lows, closes)
        index = len(candles) - 2  # completed candle only; final item can still be forming
        if not volatility[index] or not signal_at(index, fast, slow, momentum).enter_long:
            return self._event(symbol, "no_action", "no_entry_signal")
        tick, info = self.mt5.symbol_info_tick(symbol), self.mt5.symbol_info(symbol)
        if not tick or not info:
            return self._event(symbol, "blocked", "missing_tick_or_symbol_info")
        spread = (tick.ask - tick.bid) / info.point
        if spread > self.safety.max_spread_points:
            return self._event(symbol, "blocked", f"spread_too_wide:{spread:.1f}")
        stop = tick.ask - float(volatility[index]) * 1.5
        volume = self._volume(info, tick.ask - stop)
        if volume is None:
            return self._event(symbol, "blocked", "minimum_volume_exceeds_risk_limit")
        request = {"action": self.mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": volume, "type": self.mt5.ORDER_TYPE_BUY, "price": tick.ask, "sl": stop, "tp": tick.ask + (tick.ask - stop) * 2, "deviation": self.safety.deviation_points, "magic": self.safety.magic, "comment": "gold_bot", "type_time": self.mt5.ORDER_TIME_GTC, "type_filling": self.mt5.ORDER_FILLING_IOC}
        if not self.execute:
            return self._event(symbol, "dry_run", "entry_signal", request=request)
        result = self.mt5.order_send(request)
        if not result or result.retcode != self.mt5.TRADE_RETCODE_DONE:
            return self._event(symbol, "error", f"order_rejected:{getattr(result, 'comment', 'unknown')}", request=request)
        return self._event(symbol, "submitted", "buy_opened", ticket=result.order, request=request)

    def _trail_position(self, symbol: str) -> dict[str, Any]:
        positions = self.mt5.positions_get(symbol=symbol) or []
        own = [position for position in positions if position.magic == self.safety.magic]
        if not own:
            return self._event(symbol, "no_action", "no_managed_position")
        position, tick = own[0], self.mt5.symbol_info_tick(symbol)
        if not tick:
            return self._event(symbol, "blocked", "missing_tick")
        candles = self._candles(symbol)
        value = atr([c.high for c in candles], [c.low for c in candles], [c.close for c in candles])[-2]
        if not value:
            return self._event(symbol, "no_action", "atr_not_ready")
        new_stop = tick.bid - float(value) * self.safety.trailing_atr_multiple
        # Never loosen a stop; only protect a profitable long position.
        if tick.bid <= position.price_open or new_stop <= max(position.sl, position.price_open):
            return self._event(symbol, "no_action", "trailing_not_advanced")
        request = {"action": self.mt5.TRADE_ACTION_SLTP, "position": position.ticket, "symbol": symbol, "sl": new_stop, "tp": position.tp, "magic": self.safety.magic}
        if not self.execute:
            return self._event(symbol, "dry_run", "trail_stop", request=request)
        result = self.mt5.order_send(request)
        return self._event(symbol, "updated" if result and result.retcode == self.mt5.TRADE_RETCODE_DONE else "error", "trail_stop", request=request)

    def _entry_allowed(self, symbol: str) -> tuple[bool, str]:
        positions = self.mt5.positions_get() or []
        if len([p for p in positions if p.magic == self.safety.magic]) >= self.safety.max_open_positions:
            return False, "max_open_positions"
        if self.mt5.positions_get(symbol=symbol) or self.mt5.orders_get(symbol=symbol):
            return False, "duplicate_symbol_order_or_position"
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        deals = [d for d in (self.mt5.history_deals_get(start, datetime.now(UTC)) or []) if d.magic == self.safety.magic]
        if len({d.order for d in deals}) >= self.safety.max_trades_per_day:
            return False, "daily_trade_limit"
        pnl = sum(d.profit + d.commission + d.swap for d in deals)
        account = self.mt5.account_info()
        if not account or pnl <= -(account.balance * self.safety.daily_loss_limit):
            return False, "daily_loss_limit"
        return True, "ok"

    def _candles(self, symbol: str) -> list[Candle]:
        rates = self.mt5.copy_rates_from_pos(symbol, self.mt5.TIMEFRAME_M15, 0, 120)
        if rates is None or len(rates) < 60:
            raise RuntimeError(f"insufficient M15 history for {symbol}")
        return [Candle(datetime.fromtimestamp(int(row["time"]), UTC).isoformat(), float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]), float(row["tick_volume"])) for row in rates]

    def _volume(self, info: Any, stop_distance: float) -> float | None:
        account = self.mt5.account_info()
        if not account or stop_distance <= 0:
            raise RuntimeError("cannot calculate safe trade volume")
        cash_risk = account.balance * self.safety.risk_per_trade
        loss_per_lot = stop_distance / info.trade_tick_size * info.trade_tick_value
        raw = cash_risk / loss_per_lot
        if raw < info.volume_min:
            return None
        bounded = min(info.volume_max, raw)
        normalized = math.floor(bounded / info.volume_step) * info.volume_step
        return normalized if normalized >= info.volume_min else None

    def _event(self, symbol: str, status: str, reason: str, **extra: Any) -> dict[str, Any]:
        return {"timestamp": datetime.now(UTC).isoformat(), "symbol": symbol, "status": status, "reason": reason, **extra}

    def _log(self, event: dict[str, Any]) -> None:
        with Path(self.safety.log_path).open("a", encoding="utf-8") as target:
            target.write(json.dumps(event, default=str) + "\n")
