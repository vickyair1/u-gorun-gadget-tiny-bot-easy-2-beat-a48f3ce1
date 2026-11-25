[![competition](https://make.fun/badge/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1.svg)](https://make.fun/bounty/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1)
[![rank](https://make.fun/badge/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1/vickyair1/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1/rank.svg)](https://make.fun/bounty/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1)
[![reward](https://make.fun/badge/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1/vickyair1/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1/reward.svg)](https://make.fun/bounty/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1)

# Tiny Bot — Beat Buy-and-Hold on Solana

A tiny paper-trading bot for [Tiny Bot, Easy $2: Beat Buy-and-Hold on Solana](https://make.fun/bounty/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1). It reads hourly SOL-ecosystem bars and decides when to hold and when to sit in USDC, aiming to beat buy-and-hold on net PnL.

## Strategy

Two complementary legs, one program, no outside data, no network:

1. **Trend leg** — EMA(8) crosses above EMA(21): ride the trend, exit on the cross back down. Keeps the bot out of long downtrends, where buy-and-hold bleeds.
2. **Dip leg** — RSI(14) below 30 while the close sits under the lower Bollinger band (20 typical prices, 1.5σ): buy oversold dips, sell the snap-back (RSI above 70, +10% ROI, or −25% stop).

Each leg risks half a slot; a symbol both legs want gets a full slot. A slot is min(equity / 7, 25% of equity), so the bot never breaches the 25% per-symbol weight cap. Orders decided on one bar's close fill at the next bar's open, capped at 100 bps of slippage past the close.

## Backtest (kit dev window)

Validated on the kit's dev window (136 hourly bars, 2026-10-29–11-03) and on every rolling 72-bar window inside it — the final phase is 72 bars, so the rolling windows are the honest test:

| | Bot | Buy-and-hold |
|---|---|---|
| Net PnL, full 136 bars | **+$40** | −$859 |
| Median margin over buy-and-hold, 72-bar windows | **+$323** | — |
| Worst 72-bar window margin | −$213 | — |
| Max drawdown | 2% | 11% |

The bot beats buy-and-hold in 47 of 65 rolling 72-bar windows. It was picked over plain EMA crossovers (worst window −$503) and pure RSI/Bollinger mean reversion (too few trades to clear the 8-trade guardrail) because the combination keeps both the worst case and the trade count in safe territory.

## Layout

- `main.py` — the bot (Python 3.13, standard library only)
- `vendor/makefun_bars.py` — the kit's `agent-fun/bars-replay/v1` shim, vendored
- `LICENSE` — MIT

## License

MIT — see [LICENSE](LICENSE).
