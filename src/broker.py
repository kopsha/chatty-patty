import json
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import cached_property
from pathlib import Path

import pandas as pd
import pytz
from alpaca_client import AlpacaClient, Order, OrderSide
from matplotlib import pyplot as plt
from matplotlib.patches import Patch, Rectangle
from thinker import FIBONACCI, CandleStick, DataclassEncoder, RenkoBrick


class RenkoTracker:
    MAXLEN = 15 * 30  # Minutes of typical market hours
    PRECISION = 3

    def __init__(
        self,
        symbol: str,
        entry_price: Decimal,
        entry_time: datetime,
        brick_size: Decimal,
        wix: int = 6,
    ):
        self.symbol = symbol
        self.entry_price = entry_price
        self.wix = wix  # WindowIndex
        self.data: deque[CandleStick] = deque(maxlen=self.MAXLEN)
        self.current_price = Decimal()
        self.current_time = entry_time
        self.brick_size = brick_size

    def feed(self, data_points: list[dict]):
        """Trust incoming data"""
        self.data.extend(CandleStick(**x) for x in data_points)
        if self.data:
            self.current_price = self.data[-1].close
            ts = datetime.fromtimestamp(self.data[-1].timestamp)
            self.current_time = pytz.utc.localize(ts)

    @cached_property
    def data_filename(self) -> str:
        return f"{self.symbol}-1m-{self.MAXLEN}p.json"

    @cached_property
    def chart_filename(self) -> str:
        return f"{self.symbol}-1m-{self.MAXLEN}p-renko.png"

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
            datafile.write(json.dumps(data, indent=4, cls=DataclassEncoder))

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

        df["mavg"] = df["close"].rolling(self.window).mean()
        df["stdev"] = df["close"].rolling(self.window).std()
        df["avg_price"] = df[["open", "close", "low", "high"]].mean(axis=1)
        df["absolute_range"] = df["high"] - df["low"]
        df["avg_absolute_range"] = df["absolute_range"].rolling(self.window).mean()

        return df

    def compute_bricks(self, df: pd.DataFrame):
        size = self.brick_size
        renko_high = self.entry_price
        renko_low = self.entry_price - size

        bricks = list()
        last_index = df.index[0]
        for row in df.itertuples():
            if row.close >= renko_high + size:
                while row.close >= renko_high + size:
                    new_brick = RenkoBrick(
                        last_index, renko_high, renko_high + size, "up"
                    )
                    bricks.append(new_brick)
                    last_index = row.Index
                    renko_low = renko_high
                    renko_high += size

            elif row.close <= renko_low - size:
                while row.close <= renko_low - size:
                    new_brick = RenkoBrick(
                        last_index, renko_low, renko_low - size, "down"
                    )
                    bricks.append(new_brick)
                    last_index = row.Index
                    renko_high = renko_low
                    renko_low -= size

        return pd.DataFrame(bricks)

    def draw_chart(self, renko_df: pd.DataFrame, to_folder: Path):
        fig, ax = plt.subplots(figsize=(21, 13))

        timestamps = list()
        for i, brick in enumerate(renko_df.itertuples()):
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
        ax.set_ylim(
            [
                min(min(renko_df["open"]), min(renko_df["close"])) - self.brick_size / 3,
                max(max(renko_df["open"]), max(renko_df["close"])) + self.brick_size / 3,
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

        up_patch = Patch(color="forestgreen", label=f"Size {self.brick_size:.2f} $")
        down_patch = Patch(color="tomato", label=f"Size {self.brick_size:.2f} $")
        window_patch = Patch(color="royalblue", label=f"Range {self.window}")
        ax.legend(handles=[up_patch, down_patch, window_patch], loc="lower left")

        filepath = to_folder / self.chart_filename
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
        else:
            self.symbol = symbol

    def __str__(self) -> str:
        return f"*{self.symbol}* {self.qty} x {self.entry_price:.2f} $ = {self.entry_cost:.2f} $"

    @property
    def entry_cost(self) -> Decimal:
        return self.qty * self.entry_price

    def feed(self, data_points: list[dict]):
        self.trac.feed(data_points)
        df = self.trac.analyze()
        bricks_df = self.trac.compute_bricks(df)
        if bricks_df.size:
            # self.trac.draw_chart(bricks_df, self.CHARTS_PATH)
            print(len(self.trac.data), "points, and", len(bricks_df.index), "bricks.")
        else:
            print(len(self.trac.data), "points, but no bricks.")


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
