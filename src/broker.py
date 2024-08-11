import json
import math
import os
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime
from decimal import Decimal
from functools import cached_property
from pathlib import Path

import pandas as pd
import pytz
from alpaca_client import AlpacaClient, Order, OrderSide
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from thinker import CandleStick, RenkoBrick, RenkoState, ThinkEncoder, Trend

REVERSE = {Trend.UP: Trend.DOWN, Trend.DOWN: Trend.UP}
TREND_ICON = {Trend.UP: "↑", Trend.DOWN: "↓", None: "_"}


class OpenPositionTracker(ABC):
    """Follows with minute candlesticks an open position, until exit sale"""

    @abstractmethod
    def feed(self, data_points: list[dict]) -> list[Trend | None]:
        """Given a list of candlestick, applies the strategy and return events"""
        pass


class RenkoTracker(OpenPositionTracker):
    MAXLEN = 15 * 30  # Minutes of typical market day
    PRECISION = 3

    def __init__(
        self, symbol: str, entry_price: Decimal, entry_time: datetime, interval="1m"
    ):
        self.symbol = symbol
        self.interval = interval
        self.entry_price = entry_price
        self.current_price = entry_price
        self.data: deque[CandleStick] = deque(maxlen=self.MAXLEN)
        self.current_time = entry_time
        self.brick_size = 0
        self.renko_state = RenkoState(
            high=entry_price,
            abs_high=entry_price,
            low=entry_price,
            abs_low=entry_price,
            last_index=entry_time,
            int_high=entry_price,
            int_low=entry_price,
        )
        self.bricks = list()
        self.trend = None
        self.strength = 0
        self.breakout = 0

    def update_brick_size(self, from_data: list[dict], window: int = 13) -> float:
        absolute_range = max(x["high"] - x["low"] for x in from_data[-window:])
        self.brick_size = Decimal(absolute_range / 2.0).quantize(Decimal(".001"))
        return self.brick_size

    def feed(self, data_points: list[dict]) -> list[Trend | None]:
        events = list()
        new_bricks = self.renko_feed(data_points)

        for brick in new_bricks:
            self.bricks.append(brick)
            event = self.strategy_eval(brick)
            events.append(event)
        return events

    def strategy_eval(self, brick: RenkoBrick) -> Trend | None:
        def zone_log(x: int):
            return int(math.log(x - 1, 3)) if x > 1 else 0

        if self.trend is None:
            self.trend = brick.direction

        if brick.direction == self.trend:
            self.strength += 1
            self.breakout = 0
        else:
            self.strength -= 1
            self.breakout += 1

        event = None
        if self.breakout:
            needed = zone_log(self.strength)
            if self.breakout > needed:
                self.trend = REVERSE[self.trend]
                self.strength = self.breakout
                event = self.trend

        return event

    def renko_feed(self, data_points: list[dict]) -> list[RenkoBrick]:
        last_ts = int(self.current_time.timestamp())
        new_data = list(
            CandleStick(**x) for x in data_points if x["timestamp"] > last_ts
        )

        if not new_data:
            return []

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
            new_bricks = self.digest_data_point(row)
            bricks.extend(new_bricks)

        return bricks

    def digest_data_point(self, row: tuple):
        new_bricks = list()

        self.renko_state.int_high = max(self.renko_state.int_high, Decimal(row.high))
        self.renko_state.int_low = min(self.renko_state.int_low, Decimal(row.low))

        if row.close >= self.renko_state.high + self.brick_size:
            # build bullish bricks
            while row.close >= self.renko_state.high + self.brick_size:
                new_bricks.append(
                    RenkoBrick(
                        timestamp=self.renko_state.last_index,
                        open=self.renko_state.high,
                        high=self.renko_state.int_high,
                        low=self.renko_state.int_low,
                        close=self.renko_state.high + self.brick_size,
                        direction=Trend.UP,
                    )
                )
                self.renko_state.last_index = row.Index
                self.renko_state.low = self.renko_state.high
                self.renko_state.high += self.brick_size
                self.renko_state.abs_high = max(
                    self.renko_state.int_high, self.renko_state.abs_high
                )
            self.renko_state.int_high = Decimal(row.close)
            self.renko_state.int_low = Decimal(row.close)

        elif row.close <= self.renko_state.low - self.brick_size:
            # build bearish bricks
            while row.close <= self.renko_state.low - self.brick_size:
                new_bricks.append(
                    RenkoBrick(
                        timestamp=self.renko_state.last_index,
                        open=self.renko_state.low,
                        high=self.renko_state.int_high,
                        low=self.renko_state.int_low,
                        close=self.renko_state.low - self.brick_size,
                        direction=Trend.DOWN,
                    )
                )
                self.renko_state.last_index = row.Index
                self.renko_state.high = self.renko_state.low
                self.renko_state.low -= self.brick_size
                self.renko_state.abs_low = min(
                    self.renko_state.int_low, self.renko_state.abs_low
                )
            self.renko_state.int_high = Decimal(row.close)
            self.renko_state.int_low = Decimal(row.close)

        return new_bricks

    @cached_property
    def filename(self) -> str:
        return f"{self.symbol}-{self.interval}-{self.MAXLEN}p"

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

    def draw_chart(self, to_folder: Path):
        if not self.data:
            print("No data to chart")
            return None

        fig, ax = plt.subplots(figsize=(21, 13))
        timestamps = list()

        for i, brick in enumerate(self.bricks):
            line = Line2D(
                [i + 0.5, i + 0.5],
                [brick.low, brick.high],
                color="blue",
                alpha=0.34,
                linewidth=1,
            )
            ax.add_line(line)

            if brick.direction == Trend.UP:
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

        # Humanize the axes
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
                self.renko_state.abs_low - self.brick_size / Decimal("3"),
                self.renko_state.abs_high + self.brick_size / Decimal("3"),
            ]
        )

        # Add the legend
        up_patch = Patch(color="forestgreen", label=f"Size {self.brick_size:.2f} $")
        down_patch = Patch(color="tomato", label=f"Size {self.brick_size:.2f} $")
        ax.legend(handles=[up_patch, down_patch], loc="lower left")
        ax.grid()

        # Save the chart
        filepath = to_folder / (self.filename + "-renko.png")
        plt.savefig(filepath, bbox_inches="tight", dpi=300)
        plt.close()

        return filepath


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
        order: Order,
    ):
        self.client = client
        self.order = order
        self.symbol = order.symbol
        self.qty = order.filled_qty
        self.entry_price = order.filled_avg_price
        self.exit_price = None
        self.entry_time = order.submitted_at
        self.trac = RenkoTracker(self.symbol, self.entry_price, self.entry_time)
        self.trac.read_from(self.CACHE)

    def __str__(self) -> str:
        return f"*{self.symbol}*: {self.qty} x {self.trac.current_price:.2f} $ = *{self.market_value:.2f}* $"

    @property
    def current_time(self):
        return self.trac.current_time

    @property
    def market_value(self) -> Decimal:
        return self.qty * self.trac.current_price

    def formatted_value(self) -> str:
        return f"*{self.symbol}: {self.qty} x {self.trac.current_price:.2f} $ = *{self.market_value:.2f}* $"

    def formatted_entry(self) -> str:
        return f"*{self.symbol}*: {self.qty} x {self.entry_price:.2f} $ = *{self.entry_cost:.2f}* $"

    @property
    def entry_cost(self) -> Decimal:
        return self.qty * self.entry_price

    async def feed_and_act(
        self, data_points: list[dict]
    ) -> tuple[list, Path | None, bool]:
        events = self.trac.feed(data_points)

        chart_path = None
        closed = False
        if events:
            chart_path = self.trac.draw_chart(self.CHARTS_PATH)
            self.trac.write_to(self.CACHE)

            last_event = None
            for ev in filter(lambda x: x, events):
                last_event = ev

            if last_event == Trend.DOWN:
                print()
                print(
                    "Downtrend breakout, exiting position at",
                    self.trac.current_price,
                    "$",
                )
                closed = await self.sell(self.trac.current_price)

        return events, chart_path, closed

    async def buy(self, qty: int, price: Decimal):
        if self.order:
            await self.client.cancel_order(self.order.id)
        self.order = await self.client.limit_order(
            OrderSide.BUY, self.symbol, qty, price
        )

    async def sell(self, price: Decimal):
        print("faking sell", price)
        self.exit_price = price
        return True
        if self.order:
            await self.client.cancel_order(self.order.id)
        self.order = await self.client.limit_order(
            OrderSide.SELL, self.symbol, self.qty, price
        )


if __name__ == "__main__":
    raise RuntimeError("This is a pure module, cannot be executed.")
