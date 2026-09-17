from gold_bot.mt5 import MT5SafetyConfig, is_gold_symbol


def test_gold_symbol_detection_handles_broker_affixes() -> None:
    assert is_gold_symbol("XAUUSD")
    assert is_gold_symbol("XAUUSDm")
    assert is_gold_symbol("GOLD.pro")
    assert not is_gold_symbol("EURUSD")


def test_live_safety_limits_are_capped() -> None:
    try:
        MT5SafetyConfig(risk_per_trade=0.02)
    except ValueError as error:
        assert "risk_per_trade" in str(error)
    else:
        raise AssertionError("unsafe risk setting was accepted")


def test_volume_is_rejected_when_broker_minimum_breaks_risk_limit() -> None:
    class Account:
        balance = 10_000

    class MT5:
        @staticmethod
        def account_info():
            return Account()

    class Symbol:
        trade_tick_size = 0.01
        trade_tick_value = 1
        volume_min = 1.0
        volume_max = 100.0
        volume_step = 0.01

    from gold_bot.mt5 import MT5GoldBot

    bot = MT5GoldBot(MT5SafetyConfig(risk_per_trade=0.005))
    bot.mt5 = MT5()
    assert bot._volume(Symbol(), stop_distance=100) is None
