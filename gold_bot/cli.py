"""Command line entry point for CSV backtests and explicitly enabled MT5 runs."""

from __future__ import annotations

import argparse
import csv

from .backtest import BacktestConfig, run_backtest
from .data import load_candles
from .mt5 import MT5GoldBot, MT5SafetyConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="XAUUSD backtester with opt-in, guarded MT5 execution.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    backtest = subcommands.add_parser("backtest", help="run a CSV backtest")
    backtest.add_argument("--csv", required=True, help="OHLCV CSV file")
    backtest.add_argument("--balance", type=float, default=10_000)
    backtest.add_argument("--risk", type=float, default=0.01, help="risk fraction per trade; maximum 0.02")
    backtest.add_argument("--trades-out", help="optional output CSV for completed trades")
    mt5 = subcommands.add_parser("mt5", help="run one guarded MT5 monitoring/execution cycle")
    mt5.add_argument("--symbols", nargs="*", help="gold symbols; omit to detect all broker gold symbols")
    mt5.add_argument("--execute", action="store_true", help="send orders (default: inspect and log only)")
    mt5.add_argument("--risk", type=float, default=0.005, help="risk fraction per trade; maximum 0.01")
    mt5.add_argument("--daily-loss-limit", type=float, default=0.02)
    mt5.add_argument("--log", default="mt5_gold_bot.jsonl")
    args = parser.parse_args()
    if args.command == "backtest":
        result = run_backtest(load_candles(args.csv), BacktestConfig(initial_balance=args.balance, risk_per_trade=args.risk))
        print(f"Final balance: {result.final_balance:.2f}")
        print(f"Trades: {len(result.trades)}")
        print(f"Max drawdown: {result.max_drawdown:.2%}")
        if args.trades_out:
            with open(args.trades_out, "w", newline="", encoding="utf-8") as target:
                writer = csv.DictWriter(target, fieldnames=list(result.trades[0].__dict__) if result.trades else ["entry_time", "exit_time", "entry_price", "exit_price", "quantity", "reason", "pnl"])
                writer.writeheader()
                writer.writerows(trade.__dict__ for trade in result.trades)
    if args.command == "mt5":
        bot = MT5GoldBot(MT5SafetyConfig(risk_per_trade=args.risk, daily_loss_limit=args.daily_loss_limit, log_path=args.log), execute=args.execute)
        try:
            bot.connect()
            for event in bot.run_once(args.symbols):
                print(f"{event['symbol']}: {event['status']} ({event['reason']})")
        finally:
            bot.shutdown()


if __name__ == "__main__":
    main()
