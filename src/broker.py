import json
import math
import os
from collections import deque
from datetime import datetime
from decimal import Decimal
from functools import cached_property
from pathlib import Path

import pandas as pd
import pytz
from alpaca_client import AlpacaClient, Order, OrderSide
from matplotlib import pyplot as plt
from matplotlib.patches import Patch, Rectangle
from thinker import CandleStick, RenkoBrick, RenkoState, ThinkEncoder


class RenkoTracker:
    MAXLEN = 15 * 30  # Minutes of typical market day
    PRECISION = 3

    def __init__(
        self,
        symbol: str,
        entry_price: Decimal,
        entry_time: datetime,
        brick_size: Decimal,
    ):
        self.symbol = symbol
        self.entry_price = entry_price
        self.current_price = entry_price
        self.data: deque[CandleStick] = deque(maxlen=self.MAXLEN)
        self.current_time = entry_time
        self.brick_size = brick_size
        self.renko_state = RenkoState(
            high=entry_price,
            abs_high=entry_price,
            low=entry_price,
            abs_low=entry_price,
            last_index=entry_time,
        )
        self.bricks = list()

    @cached_property
    def filename(self) -> str:
        return f"{self.symbol}-1m-{self.MAXLEN}p"

    def read_from(self, cache: Path):
        filepath = cache / (self.filename + ".json")
        if not filepath.exists():
            return

        with open(filepath, "rt") as datafile:
            data = json.loads(datafile.read(), object_hook=ThinkEncoder.object_hook)
            for key, value in data.items():
                if key == "data":
                    self.data = deque(value)
                else:
                    setattr(self, key, value)

    def write_to(self, cache: Path):
        if not self.data:
            print("Nothing to cache for", self.symbol)
            return

        filepath = cache / (self.filename + ".json")
        with open(filepath, "wt") as datafile:
            data = dict()
            for k, v in vars(self).items():
                if isinstance(v, deque):
                    data[k] = [*v]
                else:
                    data[k] = v
            datafile.write(json.dumps(data, indent=4, cls=ThinkEncoder))

    def feed(self, data_points: list[dict]):
        last_ts = int(self.current_time.timestamp())
        new_data = list(
            CandleStick(**x) for x in data_points if x["timestamp"] > last_ts
        )

        if not new_data:
            return

        self.data.extend(new_data)
        self.current_price = new_data[-1].close
        ts = datetime.fromtimestamp(new_data[-1].timestamp)
        self.current_time = pytz.utc.localize(ts)

        # prepare data frame for bricks computation
        df = pd.DataFrame(new_data).astype(CandleStick.AS_DTYPE)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        df.set_index("timestamp", inplace=True)

        # compute bricks from new data
        bricks = list()
        for row in df.itertuples():
            new_bricks = self.digest_row(row)
            bricks.extend(new_bricks)

        self.bricks.extend(bricks)
        return bricks

    def digest_row(self, row):
        new_bricks = list()

        if row.close >= self.renko_state.high + self.brick_size:
            # build bullish bricks
            while row.close >= self.renko_state.high + self.brick_size:
                new_bricks.append(
                    RenkoBrick(
                        self.renko_state.last_index,
                        self.renko_state.high,
                        self.renko_state.high + self.brick_size,
                        "up",
                    )
                )
                self.renko_state.last_index = row.Index
                self.renko_state.low = self.renko_state.high
                self.renko_state.high += self.brick_size
                self.renko_state.abs_high = max(
                    self.renko_state.high, self.renko_state.abs_high
                )

        elif row.close <= self.renko_state.low - self.brick_size:
            # build bearish bricks
            while row.close <= self.renko_state.low - self.brick_size:
                new_bricks.append(
                    RenkoBrick(
                        self.renko_state.last_index,
                        self.renko_state.low,
                        self.renko_state.low - self.brick_size,
                        "down",
                    )
                )
                self.renko_state.last_index = row.Index
                self.renko_state.high = self.renko_state.low
                self.renko_state.low -= self.brick_size
                self.renko_state.abs_low = min(
                    self.renko_state.low, self.renko_state.abs_low
                )

        return new_bricks

    def draw_chart(self, to_folder: Path):
        if not self.data:
            print("No data to chart")
            return None

        fig, ax = plt.subplots(figsize=(21, 13))
        timestamps = list()
        for i, brick in enumerate(self.bricks):
            if brick.direction == "up":
                rect = Rectangle(
                    (i, brick.open),
                    1,
                    brick.close - brick.open,
                    facecolor="forestgreen",
                    edgecolor="forestgreen",
                    alpha=0.7,
                )
            else:
                rect = Rectangle(
                    (i, brick.close),
                    1,
                    brick.open - brick.close,
                    facecolor="tomato",
                    edgecolor="tomato",
                    alpha=0.7,
                )
            ax.add_patch(rect)
            timestamps.append(brick.timestamp)
        timestamps.append(datetime.fromtimestamp(self.data[-1].timestamp))

        # humanize the axes
        major_ticks = list()
        major_labels = list()
        minor_ticks = list()
        divider = (len(timestamps) // 10) or 1
        for i, ts in enumerate(timestamps):
            if i % divider == 0:
                major_ticks.append(i)
                major_labels.append(ts.strftime("%b %d, %H:%M"))
            else:
                minor_ticks.append(i)
        ax.set_xticks(major_ticks)
        ax.set_xticklabels(major_labels)
        ax.set_xticks(minor_ticks, minor=True)
        ax.set_ylim(
            [
                self.renko_state.abs_low - self.brick_size / 3,
                self.renko_state.abs_high + self.brick_size / 3,
            ]
        )

        up_patch = Patch(color="forestgreen", label=f"Size {self.brick_size:.2f} $")
        down_patch = Patch(color="tomato", label=f"Size {self.brick_size:.2f} $")
        ax.legend(handles=[up_patch, down_patch], loc="lower left")
        ax.grid()

        filepath = to_folder / (self.filename + "-renko.png")
        plt.savefig(filepath, bbox_inches="tight", dpi=300)
        plt.close()

        return filepath

    def strategy_eval(self):
        def zone_log(x: int):
            return int(math.log(x - 1, 3)) if x > 1 else 0

        if not self.bricks:
            print("no bricks, no strategy.")
            return

        REVERSE = dict(up="down", down="up")

        trend = self.bricks[0].direction
        strength = 0
        breakout = 0
        events = list()

        for i, brick in enumerate(self.bricks):
            if brick.direction == trend:
                strength += 1
                breakout = 0
            else:
                strength -= 1
                breakout += 1

            if breakout:
                needed = zone_log(strength)
                if breakout > needed:
                    trend = REVERSE[trend]
                    strength = breakout
                    events.append((i + 1, trend))

        return events


class PositionBroker:
    """
    - enter with a buy order
    - monitors the activity
    - exit with a sell order
    """

    CACHE = Path(os.getenv("PRIVATE_CACHE", "."))
    CHARTS_PATH = Path(os.getenv("OUTPUTS_PATH", "charts"))

    def __init__(
        self,
        client: AlpacaClient,
        brick_size: Decimal,
        symbol: str | None = None,
        order: Order | None = None,
    ):
        self.client = client
        self.order: Order | None = None
        self.qty = 0
        self.entry_price = Decimal()
        self.trac: RenkoTracker | None = None

        if order:
            self.order = order
            self.symbol = order.symbol
            self.qty = order.filled_qty
            self.entry_price = order.filled_avg_price
            self.entry_time = order.submitted_at
            self.trac = RenkoTracker(
                self.symbol, self.entry_price, self.entry_time, brick_size=brick_size
            )
            self.trac.read_from(self.CACHE)
        else:
            self.symbol = symbol

    def __str__(self) -> str:
        return f"*{self.symbol}*: {self.qty} x {self.trac.current_price:.2f} $ = *{self.market_value:.2f}* $"

    @property
    def market_value(self) -> Decimal:
        return self.qty * self.trac.current_price

    def formatted_value(self) -> str:
        return f"{self.qty} x {self.trac.current_price:.2f} $ = *{self.market_value:.2f}* $"

    def formatted_entry(self) -> str:
        return f"*{self.symbol}*: {self.qty} x {self.entry_price:.2f} $ = *{self.entry_cost:.2f}* $"

    @property
    def entry_cost(self) -> Decimal:
        return self.qty * self.entry_price

    def feed(self, data_points: list[dict]):
        new_bricks = self.trac.feed(data_points)
        chart_path = None
        if new_bricks:
            chart_path = self.trac.draw_chart(self.CHARTS_PATH)
            print("b" * len(new_bricks), end="")
            self.trac.write_to(self.CACHE)
        return chart_path

    async def buy(self, qty: int, price: Decimal):
        if self.order:
            await self.client.cancel_order(self.order.id)
        self.order = await self.client.limit_order(
            OrderSide.BUY, self.symbol, qty, price
        )

    async def sell(self, price: Decimal):
        if self.order:
            await self.client.cancel_order(self.order.id)
        self.order = await self.client.limit_order(
            OrderSide.SELL, self.symbol, self.qty, price
        )


if __name__ == "__main__":
    raise RuntimeError("This is a pure module, cannot be executed.")
