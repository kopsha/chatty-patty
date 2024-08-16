import math
from collections import deque
from dataclasses import field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum, auto
from functools import cached_property
from pathlib import Path
from statistics import mean
from typing import ClassVar, Deque, Iterable, List, Optional

from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from pydantic import BaseModel


class MarketSignal(StrEnum):
    HOLD = auto()
    BUY = auto()
    SELL = auto()


class MarketTrend(StrEnum):
    UP = auto()
    DOWN = auto()

    def as_signal(self) -> MarketSignal:
        return MarketSignal.BUY if self == self.UP else MarketSignal.SELL


REVERSE = {MarketTrend.UP: MarketTrend.DOWN, MarketTrend.DOWN: MarketTrend.UP}
TREND_ICON = {MarketTrend.UP: "↑", MarketTrend.DOWN: "↓", None: "_"}
MAXLEN: int = 15 * 30  # Minutes of typical market day times 15
PRECISION: Decimal = Decimal(".0001")


class Serializable(BaseModel):
    class Config:
        json_encoders = {
            Decimal: lambda val: val.quantize(PRECISION),
            datetime: lambda val: val.isoformat(),
        }


class CandleStick(Serializable):
    AS_DTYPE: ClassVar[dict[str, str]] = dict(
        open="float",
        high="float",
        low="float",
        close="float",
        volume="float",
        trades="int",
    )

    timestamp: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal()
    trades: int = 0

    @property
    def time(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp, timezone.utc)


class RenkoBrick(Serializable):
    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    direction: MarketTrend


class RenkoState(Serializable):
    last_index: datetime = datetime.now(timezone.utc)
    high: Decimal = Decimal()
    low: Decimal = Decimal()
    int_high: Decimal = Decimal()
    int_low: Decimal = Decimal()
    abs_high: Decimal = Decimal()
    abs_low: Decimal = Decimal()


class OpenTrader(Serializable):
    """Follows symbol candlesticks and issues market signals"""

    symbol: str
    data: Deque[CandleStick] = field(default_factory=lambda: deque(maxlen=MAXLEN))
    brick_size: Decimal = PRECISION
    renko_state: RenkoState = field(default_factory=RenkoState)
    bricks: List[RenkoBrick] = []
    trend: Optional[MarketTrend] = None
    strength: int = 0
    breakout: int = 0
    interval: str = "1m"

    @cached_property
    def filename(self) -> str:
        return f"{self.symbol}-{self.interval}-{MAXLEN}p"

    def read_from(self, cache: Path):
        filepath = cache / (self.filename + ".json")
        if not filepath.exists():
            return

        with open(filepath, "rt") as datafile:
            json_data = datafile.read()
            new = OpenTrader.model_validate_json(json_data)
            self.__dict__.update(new.__dict__)

    def write_to(self, cache: Path):
        if not self.data:
            print("Nothing to cache for", self.symbol)
            return

        filepath = cache / (self.filename + ".json")
        with open(filepath, "wt") as datafile:
            datafile.write(self.model_dump_json(indent=4))

    def feed(self, sticks: Iterable[CandleStick]) -> list[MarketSignal]:
        if self.data:
            last_time = self.data[-1].timestamp
            new_sticks = [sti for sti in sticks if sti.timestamp > last_time]
        else:
            new_sticks = list(sticks)

            # NOTE: compute brick size only at start
            absolute_range = list(x.high - x.low for x in new_sticks)
            half_average = max(mean(absolute_range) / 2, PRECISION)
            self.brick_size = Decimal(half_average).quantize(PRECISION)

            # NOTE: update renko state from first candle
            first = new_sticks[0]
            self.renko_state = RenkoState(
                high=first.close,
                low=first.close,
                int_high=first.close,
                int_low=first.close,
                abs_high=first.high,
                abs_low=first.low,
                last_index=datetime.fromtimestamp(first.timestamp, timezone.utc),
            )

        if not new_sticks:
            return []

        self.data.extend(new_sticks)

        signals = list()
        new_bricks = self.make_renko_bricks(new_sticks)
        for brick in new_bricks:
            self.bricks.append(brick)
            event = self.strategy_eval(brick)
            signals.append(event)

        return signals

    def make_renko_bricks(self, sticks: list[CandleStick]) -> list[RenkoBrick]:
        bricks = list()
        for stick in sticks:
            new_bricks = self.digest_data_point(stick)
            bricks.extend(new_bricks)
        return bricks

    @staticmethod
    def most_recent(signals: list[MarketSignal]):
        last_signal = MarketSignal.HOLD
        distance = 0
        for i, signal in enumerate(reversed(signals)):
            if signal != MarketSignal.HOLD:
                last_signal = signal
                distance = i
                break
        return last_signal, distance

    def strategy_eval(self, brick: RenkoBrick) -> MarketSignal:
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
            signal = self.trend.as_signal()
        else:
            signal = MarketSignal.HOLD

        return signal

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
                    time=self.renko_state.last_index,
                    open=self.renko_state.high,
                    high=self.renko_state.int_high,
                    low=self.renko_state.int_low,
                    close=self.renko_state.high + brick_diff,
                    direction=MarketTrend.UP,
                )
            )
            self.renko_state.low = self.renko_state.high
            self.renko_state.high += brick_diff
            self.renko_state.last_index = row.time
            self.renko_state.int_high = Decimal(row.close)
            self.renko_state.int_low = Decimal(row.close)

        elif row.close <= self.renko_state.low - self.brick_size:
            # build bearish brick
            brick_diff = Decimal(
                int((self.renko_state.low - Decimal(row.close)) / self.brick_size)
                * self.brick_size
            )
            new_bricks.append(
                RenkoBrick(
                    time=self.renko_state.last_index,
                    open=self.renko_state.low,
                    high=self.renko_state.int_high,
                    low=self.renko_state.int_low,
                    close=self.renko_state.low - brick_diff,
                    direction=MarketTrend.DOWN,
                )
            )
            self.renko_state.high = self.renko_state.low
            self.renko_state.low -= brick_diff
            self.renko_state.last_index = row.time
            self.renko_state.int_high = Decimal(row.close)
            self.renko_state.int_low = Decimal(row.close)

        return new_bricks

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

            if brick.direction == MarketTrend.UP:
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
            timestamps.append(brick.time)

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
        up_patch = Patch(color="forestgreen", label=f"Size {self.brick_size} $")
        down_patch = Patch(color="tomato", label=f"Size {self.brick_size} $")
        ax.legend(handles=[up_patch, down_patch], loc="lower left")
        ax.grid()

        # Save the chart
        filepath = to_folder / (self.filename + "-renko.png")
        plt.savefig(filepath, bbox_inches="tight", dpi=300)
        plt.close()

        return filepath


def test_main():
    import os

    CACHE = Path(os.getenv("PRIVATE_CACHE", "."))
    one = OpenTrader(symbol="DPROo")

    one.read_from(CACHE)


if __name__ == "__main__":
    test_main()
