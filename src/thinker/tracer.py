import json
import math
import os
from collections import deque, namedtuple
from datetime import datetime
from decimal import Decimal
from functools import cached_property
from types import SimpleNamespace
from pathlib import Path

import mplfinance as mpf
import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.patches import Patch, Rectangle
from metaflip import (
    FIBONACCI,
    HALF_DAY_CYCLE,
    QUARTER_DAY_CYCLE,
    CandleStick,
)
from ta.volatility import average_true_range
from ta.volume import on_balance_volume

RenkoBrick = namedtuple("RenkoBrick", ["timestamp", "open", "close", "kind"])


class PinkyTracker:
    """Keeps track of a single symbol"""

    def __init__(self, symbol: str, wix: int = 6, maxlen: int = QUARTER_DAY_CYCLE):
        self.symbol = symbol
        self.wix = wix  # WindowIndex
        self.maxlen = maxlen
        self.data: deque[CandleStick] = deque(maxlen=maxlen)
        self.price: Decimal = Decimal()
        self.pre_signal = None

    def feed(self, data_points: list[dict]):
        if not data_points:
            print("Provided feed seems empty, skipped.")
            return

        self.data.extend(CandleStick(**x) for x in data_points)
        self.price = self.data[-1].close

        # TODO: maybe trigger some analysis

    @cached_property
    def window(self):
        return FIBONACCI[self.wix]

    def make_indicators(self) -> pd.DataFrame:
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

        return df

    def compute_renko_bricks(self, df: pd.DataFrame):
        print(df["atr"].tail())
        size = round(df["atr"].iloc[-1], 3)  # TODO: Find a smarter rounding
        print(size)

        first_open = df["open"].iloc[0]
        first_close = df["close"].iloc[0]

        if first_open < first_close:
            renko_high = round(first_close, 2)
            renko_low = min(round(first_open, 2), renko_high - size)
        else:
            renko_high = round(first_open, 2)
            renko_low = min(round(first_close, 2), renko_high - size)

        bricks = list()
        for row in df.itertuples():
            if row.close >= renko_high + size:
                while row.close >= renko_high + size:
                    new_brick = RenkoBrick(
                        row.Index, renko_high, renko_high + size, "bulls"
                    )
                    renko_low = renko_high
                    renko_high += size
                    bricks.append(new_brick)
            elif row.close <= renko_low - size:
                while row.close <= renko_low - size:
                    new_brick = RenkoBrick(
                        row.Index, renko_low, renko_low - size, "bears"
                    )
                    renko_high = renko_low
                    renko_low -= size
                    bricks.append(new_brick)

        return pd.DataFrame(bricks), size

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

        return events

    def save_mpf_chart(self, df: pd.DataFrame, path: str, chart_type: str = "renko"):
        mavs = sorted([10] + list(FIBONACCI[self.wix - 1 : self.wix + 1]))
        fig, axes = mpf.plot(
            df,
            type=chart_type,
            mav=mavs,
            style="yahoo",
            tight_layout=True,
            xrotation=0,
            figsize=(21, 13),
            title=self.symbol,
            volume=True,
            returnfig=True,
        )
        axes[0].legend([self.symbol, *(f"SMA{x}" for x in mavs)])

        for ax in axes:
            ax.yaxis.tick_left()

        filename = f"{self.symbol}-{chart_type}-mpf.png"
        filepath = os.path.join(path, filename)
        plt.savefig(filepath, bbox_inches="tight", dpi=300)
        plt.close()
        print("saved", filepath)

    def save_renko_chart(
        self, renko_df: pd.DataFrame, events: list, size: float, path: str, suffix: str
    ):
        fig, ax = plt.subplots(figsize=(21, 13))

        timestamps = list()
        for i, brick in enumerate(renko_df.itertuples()):
            if brick.open < brick.close:
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
        for i, ts in enumerate(timestamps):
            if i % 10 == 0:
                major_ticks.append(i)
                major_labels.append(ts.strftime("%H:%M"))
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
                i + 1.75,
                ax.get_ylim()[1] * 0.999,
                event,
                rotation=90,
                verticalalignment="top",
                color=color,
            )

        up_patch = Patch(color="forestgreen", label=f"Up Brick ({size:.2f} $)")
        down_patch = Patch(color="tomato", label=f"Down Brick ({size:.2f} $)")
        window_patch = Patch(color="royalblue", label=f"ATR window {self.window}")
        ax.legend(handles=[up_patch, down_patch, window_patch], loc="lower left")

        filename = f"{self.symbol}-renko-{suffix}.png"
        filepath = os.path.join(path, filename)
        plt.savefig(filepath, bbox_inches="tight", dpi=300)
        plt.close()
        print("saved", filepath)


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
    for ts, o, h, l, c, v in zip(timestamps, opens, highs, lows, closes, volumes):
        point = dict(
            timestamp=datetime.fromtimestamp(ts),
            open=o,
            high=h,
            low=l,
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

    tracer = PinkyTracker(symbol=data.meta.symbol, wix=5, maxlen=HALF_DAY_CYCLE)
    tracer.feed(points)
    df = tracer.make_indicators()

    renko_df, size = tracer.compute_renko_bricks(df)
    events = tracer.run_mariashi_strategy(renko_df)

    charts_path = os.getenv("OUTPUTS_PATH", "charts")
    name = Path(filename).stem
    tracer.save_renko_chart(renko_df, events, size, path=charts_path, suffix=name)


def main():
    for sample in Path().glob("*.json"):
        digest_sample(sample)
    print("done")


if __name__ == "__main__":
    main()
