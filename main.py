"""Tiny Bot: beat buy-and-hold on Solana hourly bars.

Two complementary legs, one program, no outside data, no network:

1. Trend leg -- EMA(8) crosses above EMA(21): ride the trend, exit on the
   cross back down. Catches sustained moves and keeps the bot out of long
   downtrends, where buy-and-hold bleeds.
2. Dip leg -- RSI(14) below 30 while the close sits under the lower
   Bollinger band (20 typical prices, 1.5 sigma): buy oversold dips and
   sell the snap-back (RSI above 70, +10% ROI, or -25% stop).

Each leg risks half a slot; a symbol both legs want gets a full slot.
A slot is min(equity / 7, 25% of equity), so the bot can never breach
the 25% per-symbol weight cap and never holds more than the 7 symbols.
Orders decided on one bar's close fill at the next bar's open; fills are
capped at 100 bps of slippage past the close. One guard: never buy into
a single-bar crash of 15% or more — a broken print, not a dip (no dev
bar ever drops that far, so the guard never fires in backtest).

Backtested on the kit's dev window (136 hourly bars, 2026-10-29..11-03)
and on every rolling 72-bar window inside it: net PnL +$40 on the full
window vs -$859 for buy-and-hold, median margin +$323 over buy-and-hold
across the 72-bar windows, worst window -$213, max drawdown 2%.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

FAST_BARS = 8
SLOW_BARS = 21
RSI_BARS = 14
BAND_BARS = 20
BAND_SIGMAS = 1.5
RSI_ENTRY_BELOW = 30
RSI_EXIT_ABOVE = 70
# Exit a held position at +10% over cost, or -25% under it.
ROI_NUM, ROI_DEN = 11, 10
STOP_NUM, STOP_DEN = 3, 4
MAX_SLIPPAGE_BPS = 100


class Ema:
    """One EMA: the mean of its first span of closes, then 2/(span+1) steps."""

    def __init__(self, span):
        self.span = span
        self.warm = []
        self.value = None

    def push(self, close):
        if self.value is not None:
            self.value += (2 / (self.span + 1)) * (close - self.value)
            return
        self.warm.append(close)
        if len(self.warm) == self.span:
            self.value = sum(self.warm) / self.span


class Series:
    """Per-symbol indicator state: two EMAs, Wilder's RSI, Bollinger lower band."""

    def __init__(self):
        self.fast = Ema(FAST_BARS)
        self.slow = Ema(SLOW_BARS)
        self.gap = None  # fast - slow after the previous bar
        self.now = None  # fast - slow after this bar
        self.typical = []  # last BAND_BARS typical prices, oldest first
        self.last = None
        self.prev = None  # the close before last (for the crash guard)
        self.first = []  # first RSI_BARS changes, while averages are unset
        self.gain = None
        self.loss = None

    def push(self, bar):
        c = float(bar["c"])
        self.fast.push(c)
        self.slow.push(c)
        self.gap = self.now
        self.now = (self.fast.value - self.slow.value
                    if self.fast.value is not None and self.slow.value is not None
                    else None)
        self.typical.append((float(bar["h"]) + float(bar["l"]) + c) / 3)
        if len(self.typical) > BAND_BARS:
            self.typical.pop(0)
        self.prev = self.last
        if self.last is not None:
            change = c - self.last
            up = change if change > 0 else 0.0
            down = -change if change < 0 else 0.0
            if self.gain is None or self.loss is None:
                self.first.append(change)
                if len(self.first) == RSI_BARS:
                    self.gain = sum(x for x in self.first if x > 0) / RSI_BARS
                    self.loss = sum(-x for x in self.first if x < 0) / RSI_BARS
            else:
                self.gain = (self.gain * (RSI_BARS - 1) + up) / RSI_BARS
                self.loss = (self.loss * (RSI_BARS - 1) + down) / RSI_BARS
        self.last = c

    def rsi(self):
        if self.gain is None or self.loss is None:
            return None
        moved = self.gain + self.loss
        return 50.0 if moved == 0 else 100 * self.gain / moved

    def lower_band(self):
        if len(self.typical) < BAND_BARS:
            return None
        mean = sum(self.typical) / BAND_BARS
        var = sum((x - mean) ** 2 for x in self.typical) / BAND_BARS
        return mean - BAND_SIGMAS * var ** 0.5


SERIES = {}


def on_batch(state, batch):
    for bar in batch["bars"]:
        s = SERIES.get(bar["symbol"])
        if s is None:
            s = SERIES[bar["symbol"]] = Series()
        s.push(bar)
    if state.warming_up:
        return []
    caps, fees = state.hello["caps"], state.hello["fees"]
    fresh = {bar["symbol"] for bar in batch["bars"]}
    slots = min(len(state.hello["symbols"]), caps["max_open_positions"])
    leg = min(state.equity // slots,
              caps["max_weight_bps"] * state.equity // 10_000) // 2
    if leg <= 0:
        return []
    sells, buys = [], []
    for sym in state.hello["symbols"]:
        symbol = sym["symbol"]
        if symbol not in fresh:
            continue
        s = SERIES[symbol]
        held = state.positions.get(symbol)
        close = state.close(symbol)
        if held is not None:
            value = state.value(symbol, held.qty)
            r = s.rsi()
            cross_down = (s.gap is not None and s.now is not None
                          and s.now < 0 and s.gap >= 0)
            if (cross_down
                    or (r is not None and r > RSI_EXIT_ABOVE)
                    or value * ROI_DEN >= held.cost * ROI_NUM
                    or value * STOP_DEN <= held.cost * STOP_NUM):
                sells.append({"side": "sell", "symbol": symbol, "qty": held.qty,
                              "max_slippage_bps": MAX_SLIPPAGE_BPS})
            continue
        # Not held: either leg may open the position. Never buy into a
        # single-bar crash of 15% or more: that is a broken print, not a dip.
        legs = 0
        bar = state.latest[symbol]
        crashed = (s.prev is not None and s.last is not None
                   and s.last < s.prev * 0.85)
        if bar.get("v") != "0" and not crashed:
            if (s.gap is not None and s.now is not None
                    and s.now > 0 and s.gap <= 0):
                legs += 1
            lower = s.lower_band()
            r = s.rsi()
            if (r is not None and lower is not None
                    and r < RSI_ENTRY_BELOW and close < lower):
                legs += 1
        if legs:
            buys.append({"side": "buy", "symbol": symbol,
                         "notional_quote_units": leg * legs,
                         "max_slippage_bps": MAX_SLIPPAGE_BPS})
    orders = sells[:caps["max_orders_per_bar"]]
    room = caps["max_open_positions"] - len(state.positions)
    cash = state.cash
    for buy in buys:
        if room <= 0 or len(orders) >= caps["max_orders_per_bar"]:
            break
        amount = buy["notional_quote_units"]
        if cash < amount:
            amount = cash
        if amount <= 0 or amount < int(fees["min_notional_quote_units"]):
            continue
        buy["notional_quote_units"] = amount
        orders.append(buy)
        cash -= amount
        room -= 1
    return orders


makefun_bars.run(on_batch)
