from gold_bot.backtest import BacktestConfig, run_backtest
from gold_bot.data import Candle, load_candles
from gold_bot.strategy import atr, ema, rsi


def candle(index: int, close: float) -> Candle:
    return Candle(f"2026-01-{index + 1:02d}T00:00:00Z", close, close + 2, close - 2, close)


def test_indicators_wait_for_enough_data() -> None:
    assert ema([1, 2], 3) == [None, None]
    assert rsi([1, 2, 3], 3) == [None, None, None]
    assert atr([2, 3], [0, 1], [1, 2], 2) == [None, None]


def test_backtest_closes_position_and_protects_risk_limit() -> None:
    closes = [2000.0]
    for index in range(1, 70):
        closes.append(closes[-1] + (-2 if index % 3 == 0 else 2))
    candles = [candle(i, close) for i, close in enumerate(closes)]
    result = run_backtest(candles, BacktestConfig(fast_ema=3, slow_ema=8, atr_period=3, risk_per_trade=0.01))
    assert result.trades
    assert result.trades[-1].reason in {"take_profit", "end_of_data"}
    assert result.max_drawdown <= 0.01


def test_invalid_csv_is_rejected(tmp_path) -> None:
    source = tmp_path / "bad.csv"
    source.write_text("timestamp,open,high,low,close\n1,10,9,8,9\n", encoding="utf-8")
    try:
        load_candles(source)
    except ValueError as error:
        assert "inconsistent" in str(error)
    else:
        raise AssertionError("invalid price range was accepted")
