import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from functools import cached_property
from pathlib import Path
from typing import Any

from alpaca_client import AlpacaClient
from alpaca_trader import AlpacaTrader
from thinker import FULL_CYCLE, PinkyTracker


class DataclassEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if is_dataclass(o):
            return asdict(o)
        return super().default(o)


class AlpacaScavenger:
    CACHE = Path(os.getenv("PRIVATE_CACHE", "."))

    def __init__(self, api_key: str, secret):
        self.client = AlpacaClient(api_key, secret)

        self.account = None
        self.market_clock = None
        self.trackers = dict()
        self.positions = list()

    async def on_start(self):
        await self.client.on_start()

        await self.update_market_clock()
        self.account = await self.client.fetch_account_info()
        self.positions = await self.client.fetch_open_positions()

    async def on_stop(self):
        await self.client.on_stop()

    async def update_market_clock(self):
        self.market_clock = await self.client.fetch_market_clock()

    def overview(self) -> str:
        lines = list()

        market_status = "Open" if self.market_clock.is_open else "Closed"
        lines.append(f"Market is {market_status}.")

        lines.append(f"Cash: {self.account.cash:.2f}")
        lines.append(f"Portfolio total: *{self.account.portfolio_value:.2f}* $")

        for pos in self.positions:
            lines.append(
                f"*{pos.symbol}*: "
                f"{pos.qty} x {pos.current_price:.2f} $ = {pos.market_value:.2f} $"
            )
            lines.append(
                f"return: {pos.unrealized_pl:.2f} $ ({pos.unrealized_plpc * 100:.2f} %)"
            )

        return lines

    async def track_open_positions(self):
        self.positions = await self.client.fetch_open_positions()
        news = list()
        for pos in self.positions:
            if pos.symbol not in self.trackers:
                tracker = self.make_tracker(pos.symbol)
                self.trackers[pos.symbol] = tracker
            else:
                tracker = self.trackers[pos.symbol]

            await self.update_tracker(tracker)
            event, is_new, image = self.strategic_run(tracker)
            if is_new:
                news.append((tracker.symbol, event, image))

                trader = AlpacaTrader(self.client, position=pos)
                if event == "confirmed bears":
                    await trader.sell(pos.current_price)

        return news

    def make_tracker(self, symbol: str, cycle=FULL_CYCLE) -> PinkyTracker:
        tracker = PinkyTracker(symbol=symbol, wix=5, interval=30, maxlen=cycle)
        tracker.read_from(self.CACHE)
        return tracker

    async def update_tracker(self, tracker: PinkyTracker):
        now = datetime.now(timezone.utc)
        a_month_ago = now - timedelta(days=90)
        since = max(tracker.last_timestamp, a_month_ago)
        delta = now - since
        interval = tracker.interval
        if (self.market_clock.is_open and (delta >= timedelta(minutes=interval))) or (
            not self.market_clock.is_open and (delta >= timedelta(hours=16))
        ):
            bars = await self.client.fetch_bars(
                tracker.symbol, since, interval=f"{interval}Min"
            )
            tracker.feed(map(asdict, bars))
            tracker.write_to(self.CACHE)

    def strategic_run(self, tracker: PinkyTracker):
        df = tracker.analyze()
        renko_df = tracker.compute_renko_data(df)

        events, is_new = tracker.run_mariashi_strategy(renko_df)
        if is_new:
            charts_path = os.getenv("OUTPUTS_PATH", "charts")
            image = tracker.save_renko_chart(renko_df, events, path=charts_path)
        else:
            image = None

        return tracker.last_event, is_new, image

    @cached_property
    def known_commands(self):
        return {func[4:] for func in dir(self) if func.startswith("cmd_")}

    async def run_commands(self, commands):
        for cmd, params in commands:
            func = getattr(self, "cmd_" + cmd)
            await func(params)


if __name__ == "__main__":
    raise RuntimeError("This is a pure module, cannot be executed.")
