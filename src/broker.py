import json
import math
import os
import sys
from collections import deque
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from functools import cached_property
from pathlib import Path
from statistics import mean
from typing import ClassVar, Self, Type
from types import SimpleNamespace

import pandas as pd
import pytz
from alpaca_client import AlpacaClient, Order, OrderSide
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from thinker import RenkoBrick, Trend

REVERSE = {Trend.UP: Trend.DOWN, Trend.DOWN: Trend.UP}
TREND_ICON = {Trend.UP: "↑", Trend.DOWN: "↓", None: "_"}



class ThoughtEncoder(json.JSONEncoder):
    def default(self, o):
        if is_dataclass(o):
            data_obj = asdict(o)
            data_obj["class_type"] = type(o).__name__
            return data_obj
        elif isinstance(o, Decimal):
            return float(o)
        elif isinstance(o, datetime):
            return dict(iso_datetime=o.isoformat())
        return super().default(o)

    @staticmethod
    def object_hook(obj):
        if iso_tm := obj.get("iso_datetime"):
            return datetime.fromisoformat(iso_tm)
        elif classname := obj.pop("class_type", None):
            cls = getattr(sys.modules[__name__], classname)
            for k, v in obj.items():
                if isinstance(v, float):
                    obj[k] = Decimal(v)
            return cls(**obj)
        if "brick_size" in obj:
            obj["brick_size"] = Decimal(obj["brick_size"])
        return obj


@dataclass
class CandleStick:
    AS_DTYPE: ClassVar[dict[str, str]] = dict(
        open="float",
        high="float",
        low="float",
        close="float",
        volume="float",
        trades="int",
        vw_price="float",
    )

    timestamp: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal()
    trades: int = 0
    vw_price: Decimal = Decimal()

    @classmethod
    def from_dict(cls: Type, obj: SimpleNamespace):
        valid_fields = {f.name: f.type for f in fields(cls)}
        valid_data = dict()
        for key, value in vars(obj).items():
            if value and key in valid_fields:
                typed = valid_fields[key]
                valid_data[key] = typed(value)
        return cls(**valid_data)

@dataclass
class RenkoState:
    high: Decimal
    low: Decimal
    abs_high: Decimal
    abs_low: Decimal
    last_index: datetime
    int_high: Decimal
    int_low: Decimal


class OpenTrader:
    MAXLEN = 15 * 30  # Minutes of typical market day
    PRECISION = 3

    @classmethod
    def from_bars(cls: Type, symbol: str, bars: list):
        sticks = [CandleStick.from_bar(bi) for bi in bars]
        entry_time = datetime.fromtimestamp(sticks[0].timestamp)
        instance = cls(symbol, sticks[0].open, entry_time)
        instance.update_brick_size(sticks)

        # find last trend reversal
        events = instance.feed(sticks)
        last_event, distance = events[0], len(events)
        for i, ev in enumerate(reversed(events)):
            if ev is not None:
                last_event = ev
                distance = i
                break

        return instance, last_event, distance

    def __init__(
        self, symbol: str, entry_price: Decimal, entry_time: datetime, interval="1m"
    ):
        self.symbol = symbol
        self.interval = interval
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

    def update_brick_size(self, from_sticks: list) -> Decimal:
        absolute_range = list(x.high - x.low for x in from_sticks[-9:])
        half_average = max(mean(absolute_range) / 2, 0.001)
        self.brick_size = Decimal(half_average).quantize(Decimal(".001"))
        return self.brick_size

    def feed(self, sticks: list[CandleStick]) -> list[Trend | None]:
        current_ts = int(self.current_time.timestamp())
        newer_sticks = [sti for sti in sticks if sti.timestamp > current_ts]
        if not newer_sticks:
            return []

        events = list()
        new_bricks = self.renko_feed(newer_sticks)
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
            self.breakout += 1

        allowed = zone_log(self.strength)
        if self.breakout > allowed:
            self.trend = REVERSE[self.trend]
            self.strength = self.breakout
            self.breakout = 0
            event = self.trend
        else:
            event = None

        return event

    def renko_feed(self, new_data: list[CandleStick]) -> list[RenkoBrick]:
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

    def digest_data_point(self, row: CandleStick):
        new_bricks = list()

        self.renko_state.int_high = max(self.renko_state.int_high, Decimal(row.high))
        self.renko_state.int_low = min(self.renko_state.int_low, Decimal(row.low))
        self.renko_state.abs_high = max(
            self.renko_state.int_high, self.renko_state.abs_high
        )
        self.renko_state.abs_low = min(
            self.renko_state.int_low, self.renko_state.abs_low
        )

        if row.close >= self.renko_state.high + self.brick_size:
            # build bullish brick
            brick_diff = (
                int((Decimal(row.close) - self.renko_state.high) / self.brick_size)
                * self.brick_size
            )
            new_bricks.append(
                RenkoBrick(
                    timestamp=self.renko_state.last_index,
                    open=self.renko_state.high,
                    high=self.renko_state.int_high,
                    low=self.renko_state.int_low,
                    close=self.renko_state.high + brick_diff,
                    direction=Trend.UP,
                )
            )
            self.renko_state.low = self.renko_state.high
            self.renko_state.high += brick_diff
            self.renko_state.last_index = row.Index
            self.renko_state.int_high = Decimal(row.close)
            self.renko_state.int_low = Decimal(row.close)

        elif row.close <= self.renko_state.low - self.brick_size:
            # build bearish brick
            brick_diff = Decimal(
                int((float(self.renko_state.low) - row.close) / float(self.brick_size))
                * self.brick_size
            )
            new_bricks.append(
                RenkoBrick(
                    timestamp=self.renko_state.last_index,
                    open=self.renko_state.low,
                    high=self.renko_state.int_high,
                    low=self.renko_state.int_low,
                    close=self.renko_state.low - brick_diff,
                    direction=Trend.DOWN,
                )
            )
            self.renko_state.high = self.renko_state.low
            self.renko_state.low -= brick_diff
            self.renko_state.last_index = row.Index
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
                self.renko_state.abs_low - self.brick_size,
                self.renko_state.abs_high + self.brick_size,
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

    def __init__(self, client: AlpacaClient, symbol: str):
        self.client = client
        self.order = None
        self.symbol = symbol
        self.qty: int = 0
        self.entry_price = Decimal()
        self.trac = None

    @classmethod
    def from_bars(cls, client: AlpacaClient, symbol: str, bars: list):
        instance = cls(client, symbol)
        instance.symbol = symbol
        instance.trac, last_event, distance = RenkoTracker.from_bars(symbol, bars)
        return instance, last_event, distance

    @classmethod
    def from_order(cls, client: AlpacaClient, order: Order) -> Self:
        instance = cls(client, order.symbol)
        instance.order = order
        instance.symbol = order.symbol
        instance.qty = order.filled_qty
        instance.entry_price = order.filled_avg_price
        instance.trac = RenkoTracker(
            instance.symbol, instance.entry_price, order.submitted_at
        )
        instance.trac.read_from(instance.CACHE)
        return instance

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

    @property
    def stop_loss_limit(self) -> Decimal:
        return self.entry_price * Decimal(".925")

    async def feed_and_act(
        self, bars: list[SimpleNamespace]
    ) -> tuple[list, Path | None, bool]:
        """Exit positioon for stop-loss or detecting a downtrend"""
        if not self.trac.data:
            self.trac, _, _ = RenkoTracker.from_bars(self.symbol, bars)

        events = self.trac.feed(CandleStick.from_bar(bi) for bi in bars)
        self.trac.write_to(self.CACHE)

        price = self.trac.current_price
        if price <= self.stop_loss_limit or self.trac.trend == Trend.DOWN:
            await self.sell(price)

        chart = None
        if any(events):
            chart = self.trac.draw_chart(self.CHARTS_PATH)

        return chart, events

    async def buy(self, qty: int, price: Decimal):
        price = Decimal(price).quantize(Decimal(".001"))
        self.qty = qty
        self.order = await self.client.limit_order(
            OrderSide.BUY, self.symbol, qty, price
        )
        self.trac.write_to(self.CACHE)

    async def sell(self, price: Decimal):
        price = Decimal(price).quantize(Decimal(".001"))
        self.order = await self.client.limit_order(
            OrderSide.SELL, self.symbol, self.qty, price
        )
        self.trac.write_to(self.CACHE)


if __name__ == "__main__":
    raise RuntimeError("This is a pure module, cannot be executed.")
