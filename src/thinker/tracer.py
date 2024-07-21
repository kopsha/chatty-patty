import os
from collections import deque, namedtuple
from datetime import datetime
from decimal import Decimal
from functools import cached_property
from types import SimpleNamespace

import mplfinance as mpf
import pandas as pd
from matplotlib import dates as mdates
from matplotlib import pyplot as plt
from matplotlib.patches import Patch, Rectangle
from metaflip import (
    FIBONACCI,
    HALF_DAY_CYCLE,
    QUARTER_DAY_CYCLE,
    CandleStick,
    MarketSignal,
)
from ta.volatility import average_true_range
from ta.volume import on_balance_volume

RenkoBrick = namedtuple("RenkoBrick", ["timestamp", "open", "close"])


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
            window=FIBONACCI[self.wix + 1],
        )

        return df

    def compute_renko_bricks(self, df: pd.DataFrame):
        size = round(df["atr"].iloc[-1], 2)  # TODO: Find a smarter rounding

        first_brick = RenkoBrick(df.index[0], df["open"].iloc[0], df["close"].iloc[0])

        if first_brick.open < first_brick.close:
            renko_high = round(first_brick.close, 2)
            renko_low = min(round(first_brick.open, 2), renko_high - size)
        else:
            renko_high = round(first_brick.open, 2)
            renko_low = min(round(first_brick.close, 2), renko_high - size)

        bricks = list()
        for row in df.itertuples():
            if row.close >= renko_high + size:
                while row.close >= renko_high + size:
                    new_brick = RenkoBrick(row.Index, renko_high, renko_high + size)
                    renko_low = renko_high
                    renko_high += size
                    bricks.append(new_brick)
            elif row.close <= renko_low - size:
                while row.close <= renko_low - size:
                    new_brick = RenkoBrick(row.Index, renko_low, renko_low - size)
                    renko_high = renko_low
                    renko_low -= size
                    bricks.append(new_brick)

        return pd.DataFrame(bricks), size

    def compute_triggers(self, df: pd.DataFrame):
        return MarketSignal.HOLD

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

        # TODO: deal with paths later
        filename = f"{self.symbol}-{chart_type}-mpf.png"
        filepath = os.path.join(path, filename)
        plt.savefig(filepath, bbox_inches="tight", dpi=300)
        plt.close()
        print("saved", filepath)

    def save_renko_chart(self, renko_df: pd.DataFrame, size: float, path: str):
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
        ax.set_xlim([0, renko_df.shape[0]])
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
            if i % 5 == 0:
                major_ticks.append(i)
                major_labels.append(ts.strftime("%H:%M"))
            else:
                minor_ticks.append(i)

        ax.set_xticks(major_ticks)
        ax.set_xticklabels(major_labels)
        ax.set_xticks(minor_ticks, minor=True)
        ax.grid()

        up_patch = Patch(color="forestgreen", label=f"Up Brick ({size:.2f} $)")
        down_patch = Patch(color="tomato", label=f"Down Brick ({size:.2f} $)")
        ax.legend(handles=[up_patch, down_patch], loc="lower left")

        # TODO: deal with paths later
        filename = f"{self.symbol}-renko.png"
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


def main():
    import json

    with open("sample-bitf-1m.json") as datafile:
        raw_data = json.loads(datafile.read())

    data = to_namespace(raw_data["chart"]["result"][0])
    points = from_yfapi(data)

    print("starting over...")
    tracer = PinkyTracker(symbol=data.meta.symbol, wix=5, maxlen=HALF_DAY_CYCLE)
    tracer.feed(points)
    df = tracer.make_indicators()
    renko_df, size = tracer.compute_renko_bricks(df)
    tracer.save_renko_chart(renko_df, size, path="charts")

    print("done")


if __name__ == "__main__":
    main()
