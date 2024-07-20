import os
from collections import deque
from datetime import datetime
from decimal import Decimal
from functools import cached_property
from types import SimpleNamespace

import mplfinance as mpf
import pandas as pd
from matplotlib import pyplot as plt
from metaflip import FIBONACCI, FULL_CYCLE, CandleStick, MarketSignal
from ta.volatility import BollingerBands
from ta.volume import money_flow_index, volume_weighted_average_price


class PinkyTracker:
    """Keeps track of a single symbol"""

    def __init__(self, symbol: str, wix: int = 6, maxlen: int = FULL_CYCLE):
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

        bb = BollingerBands(close=df["close"], window=self.window)
        df["bb_high"] = bb.bollinger_hband()
        df["bb_low"] = bb.bollinger_lband()

        df["stdev"] = df["close"].rolling(self.window).std()
        df["vwap"] = volume_weighted_average_price(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            volume=df["volume"],
            window=self.window,
        )
        # df["vwap_vhigh"] = df["vwap"] + 2 * df["stdev"]
        df["vwap_high"] = df["vwap"] + 1.618 * df["stdev"]
        df["vwap_low"] = df["vwap"] - 1.618 * df["stdev"]
        # df["vwap_vlow"] = df["vwap"] - 2 * df["stdev"]

        return df

    def compute_triggers(self, df: pd.DataFrame):
        # TODO: why not use bollinger bands
        high = df["bb_high"].iloc[-1]
        low = df["bb_low"].iloc[-1]

        return MarketSignal.HOLD

    def save_chart(self, df: pd.DataFrame, path: str):
        extras = [
            mpf.make_addplot(df["bb_high"], color="blue", panel=0, secondary_y=False),
            mpf.make_addplot(df["bb_low"], color="red", panel=0, secondary_y=False),
            mpf.make_addplot(
                df["vwap"], color="blueviolet", panel=0, secondary_y=False
            ),
            # mpf.make_addplot(
            #     df["vwap_vhigh"], color="royalblue", panel=0, secondary_y=False
            # ),
            mpf.make_addplot(
                df["vwap_high"], color="deepskyblue", panel=0, secondary_y=False
            ),
            mpf.make_addplot(
                df["vwap_low"], color="darkorange", panel=0, secondary_y=False
            ),
            # mpf.make_addplot(
            #     df["vwap_vlow"], color="orangered", panel=0, secondary_y=False
            # ),
        ]

        fig, axes = mpf.plot(
            df,
            type="candle",
            addplot=extras,
            title=self.symbol,
            volume=True,
            figsize=(21, 13),
            tight_layout=True,
            xrotation=0,
            returnfig=True,
        )

        for ax in axes:
            ax.yaxis.tick_left()
            ax.yaxis.label.set_visible(False)
            ax.margins(x=0.1, y=0.1, tight=True)

        # TODO: deal with paths later
        filename = f"{self.symbol}.png"
        filepath = os.path.join(path, filename)
        plt.savefig(filepath, bbox_inches="tight", pad_inches=0.3, dpi=300)
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

    with open("sample-xcur-5m.json") as datafile:
        raw_data = json.loads(datafile.read())

    data = to_namespace(raw_data["chart"]["result"][0])
    points = from_yfapi(data)

    print("testing")
    tracer = PinkyTracker(symbol="XCUR", wix=4)
    tracer.feed(points)
    df = tracer.make_indicators()
    tracer.save_chart(df, path="charts")

    print("done")


if __name__ == "__main__":
    main()
