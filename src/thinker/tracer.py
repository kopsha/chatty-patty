import json
import math
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import cached_property
from pathlib import Path
from types import SimpleNamespace

import mplfinance as mpf
import pandas as pd
import pytz
from matplotlib import pyplot as plt
from matplotlib.patches import Patch, Rectangle
from ta.volatility import average_true_range
from ta.volume import on_balance_volume

from .metaflip import (
    FIBONACCI,
    QUARTER_RANGE,
    CandleStick,
    ThinkEncoder,
    RenkoBrick,
    DAY_RANGE,
)


class PinkyTracker:
    """Keeps track of a single symbol"""

    def __init__(
        self, symbol: str, wix: int = 6, interval: int = 30, maxlen: int = QUARTER_RANGE
    ):
        self.symbol = symbol
        self.wix = wix  # WindowIndex
        self.maxlen = maxlen
        self.data: deque[CandleStick] = deque(maxlen=maxlen)
        self.price: Decimal = Decimal()
        self.pre_signal = None
        self.last_timestamp = datetime.now(timezone.utc) - timedelta(days=100)
        self.last_event = None
        self.interval = interval

    def feed(self, data_points: list[dict]):
        self.data.extend(CandleStick(**x) for x in data_points)
        if self.data:
            self.price = self.data[-1].close

        ts = datetime.utcfromtimestamp(self.data[-1].timestamp)
        self.last_timestamp = pytz.utc.localize(ts)

    @cached_property
    def data_filename(self) -> str:
        return f"{self.symbol}-{self.interval}m-{self.maxlen}p.json"

    def read_from(self, cache: Path):
        filepath = cache / self.data_filename
        if not filepath.exists():
            print(f"Symbol {self.symbol} has no cached data")
            return

        with open(filepath, "rt") as datafile:
            data_points = json.loads(datafile.read())

        self.feed(data_points)

    def write_to(self, cache: Path):
        if not self.data:
            print("Nothing to write")
            return

        filepath = cache / self.data_filename
        with open(filepath, "wt") as datafile:
            data = list(self.data)
            datafile.write(json.dumps(data, indent=4, cls=ThinkEncoder))

    @cached_property
    def window(self):
        return FIBONACCI[self.wix]

    def analyze(self) -> pd.DataFrame:
        if not self.data:
            print("Cannot analyze anything, data feed is empty.")
            return pd.DataFrame()

        df = pd.DataFrame(self.data).astype(CandleStick.AS_DTYPE)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        df.set_index("timestamp", inplace=True)

        df["velocity"] = df["close"].diff()
        df["high_velocity"] = df["high"].diff()
        df["low_velocity"] = df["low"].diff()

        df["mavg"] = df["close"].rolling(self.window).mean()
        df["stdev"] = df["close"].rolling(self.window).std()
        df["avg_price"] = (df["close"] + df["low"] + df["high"]) / 3

        df["obv"] = on_balance_volume(close=df["close"], volume=df["volume"])
        df["obv_velocity"] = df["obv"].diff()

        df["atr"] = average_true_range(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            window=self.window,
        )
        df["ar"] = df["high"] - df["low"]
        df["mar"] = df["ar"].rolling(self.window).mean()

        self.precision = 3
        self.brick_size = round(df["mar"].max() / 2, self.precision)

        return df

    def compute_renko_data(self, df: pd.DataFrame):
        size = self.brick_size

        first_open = df["open"].iloc[0]
        first_close = df["close"].iloc[0]
        if first_open < first_close:
            renko_high = round(first_close, self.precision)
            renko_low = min(round(first_open, self.precision), renko_high - size)
        else:
            renko_high = round(first_open, self.precision)
            renko_low = min(round(first_close, self.precision), renko_high - size)

        bricks = list()
        for row in df.itertuples():
            if row.close >= renko_high + size:
                while row.close >= renko_high + size:
                    new_brick = RenkoBrick(
                        row.Index, renko_high, renko_high + size, "up"
                    )
                    renko_low = renko_high
                    renko_high += size
                    bricks.append(new_brick)
            elif row.close <= renko_low - size:
                while row.close <= renko_low - size:
                    new_brick = RenkoBrick(
                        row.Index, renko_low, renko_low - size, "down"
                    )
                    renko_high = renko_low
                    renko_low -= size
                    bricks.append(new_brick)

        return pd.DataFrame(bricks)

    def run_mariashi_strategy(self, renko_df: pd.DataFrame):
        def zone_log(x: int):
            return int(math.log(x - 1, 3)) if x > 1 else 0

        bulls = 0
        bears = 0

        events = list()
        previous_side = side = None

        for i, action in enumerate(renko_df.itertuples()):
            if action.kind == "bulls":
                bulls += 1
            else:
                bears += 1

            if action.kind != previous_side:
                if previous_side == "bulls":
                    zone = zone_log(bulls)
                    if bears > zone:
                        side = "bears"
                else:
                    zone = zone_log(bears)
                    if bulls > zone:
                        side = "bulls"

            if previous_side != side:
                events.append((i, f"{side} trend"))
                if side == "bulls":
                    bears = 0
                else:
                    bulls = 0
            else:
                if side == action.kind:
                    if side == "bulls":
                        bears = max(0, bears - 1)
                    else:
                        bulls = max(0, bulls - 1)

            if action.kind == "bulls" and bulls == 3:
                if events and events[-1][0] == i:
                    events.pop()
                events.append((i, "confirmed bulls"))
            elif action.kind == "bears" and bears == 3:
                if events and events[-1][0] == i:
                    events.pop()
                events.append((i, "confirmed bears"))

            previous_side = side

        has_changed = events[-1][1] != self.last_event
        self.last_event = events[-1][1]

        return events, has_changed

    def save_renko_chart(self, renko_df: pd.DataFrame, events: list, path: str):
        fig, ax = plt.subplots(figsize=(21, 13))

        timestamps = list()
        for i, brick in enumerate(renko_df.itertuples()):
            if brick.direction == "up":
                rect = Rectangle(
                    (i + 1, brick.open),
                    1,
                    brick.close - brick.open,
                    facecolor="forestgreen",
                    edgecolor="forestgreen",
                    alpha=0.7,
                )
            else:
                rect = Rectangle(
                    (i + 1, brick.close),
                    1,
                    brick.open - brick.close,
                    facecolor="tomato",
                    edgecolor="tomato",
                    alpha=0.7,
                )
            ax.add_patch(rect)
            timestamps.append(brick.timestamp)

        # humanize the axes
        ax.set_xlim([1, renko_df.shape[0] + 2])
        ax.set_ylim(
            [
                min(min(renko_df["open"]), min(renko_df["close"])),
                max(max(renko_df["open"]), max(renko_df["close"])),
            ]
        )

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
        ax.grid()

        color_map = {
            "bulls trend": "forestgreen",
            "bears trend": "tomato",
            "confirmed bulls": "darkgreen",
            "confirmed bears": "darkred",
        }
        for i, event in events:
            color = color_map[event]
            ax.axvline(x=i + 2, color=color, linestyle="--", linewidth=1, alpha=0.8)
            ax.text(
                i + 2,
                ax.get_ylim()[1] * 0.999,
                event,
                rotation=90,
                verticalalignment="top",
                color=color,
            )

        up_patch = Patch(color="forestgreen", label=f"Size {self.brick_size:.2f} $")
        window_patch = Patch(color="royalblue", label=f"Range {self.window}")
        ax.legend(handles=[up_patch, window_patch], loc="lower left")

        filename = f"{self.symbol}-{self.interval}m-{self.maxlen}p-renko.png"
        filepath = os.path.join(path, filename)
        plt.savefig(filepath, bbox_inches="tight", dpi=300)
        plt.close()

        return filepath

    def save_mpf_chart(
        self, df: pd.DataFrame, path: str, suffix: str, chart_type: str = "candle"
    ):
        half_df = df.tail(self.maxlen // 2)
        fig, axes = mpf.plot(
            half_df,
            type=chart_type,
            mav=[self.window],
            style="yahoo",
            tight_layout=True,
            xrotation=0,
            figsize=(21, 13),
            title=self.symbol,
            volume=True,
            returnfig=True,
        )

        for ax in axes:
            ax.yaxis.tick_left()

        axes[0].legend([f"SMA{self.window}", self.symbol])

        filename = f"{self.symbol}-{chart_type}-mpf-{suffix}.png"
        filepath = os.path.join(path, filename)
        plt.savefig(filepath, bbox_inches="tight", dpi=300)
        plt.close()


def to_namespace(data):
    """Recursively convert dictionary to SimpleNamespace."""

    if isinstance(data, dict):
        for key, value in data.items():
            data[key] = to_namespace(value)
        return SimpleNamespace(**data)
    elif isinstance(data, list):
        return [to_namespace(item) for item in data]

    return data


def from_yfapi(data):
    timestamps = data.timestamp
    opens = data.indicators.quote[0].open
    highs = data.indicators.quote[0].high
    lows = data.indicators.quote[0].low
    closes = data.indicators.quote[0].close
    volumes = data.indicators.quote[0].volume

    points = list()
    for ts, o, h, lo, c, v in zip(timestamps, opens, highs, lows, closes, volumes):
        point = dict(
            timestamp=datetime.fromtimestamp(ts),
            open=o,
            high=h,
            low=lo,
            close=c,
            volume=v,
        )
        if all(point.values()):
            points.append(point)

    return points


def digest_sample(filename: str):
    print(f"========================= {filename} ===")
    with open(filename) as datafile:
        raw_data = json.loads(datafile.read())

    data = to_namespace(raw_data["chart"]["result"][0])
    points = from_yfapi(data)

    tracer = PinkyTracker(symbol=data.meta.symbol, wix=5, maxlen=DAY_RANGE)
    tracer.feed(points)
    df = tracer.analyze()

    renko_df, size = tracer.compute_renko_data(df)
    events = tracer.run_mariashi_strategy(renko_df)

    charts_path = os.getenv("OUTPUTS_PATH", "charts")
    name = Path(filename).stem
    tracer.save_renko_chart(renko_df, events, size, path=charts_path, suffix=name)


def main():
    data_folder = Path(os.getenv("PRIVATE_CACHE"))
    for sample in data_folder.glob("*.json"):
        print(sample)
        # digest_sample(sample)

    print("done")


if __name__ == "__main__":
    main()
