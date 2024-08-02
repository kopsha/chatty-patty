import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from functools import cached_property
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from alpaca_client import AlpacaClient, Bar
from thinker import FAST_CYCLE, FULL_CYCLE, PinkyTracker


class DataclassEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if is_dataclass(o):
            return asdict(o)
        return super().default(o)


class AlpacaScavenger:
    CACHE = Path(os.getenv("PRIVATE_CACHE", "."))

    def __init__(self, api_key: str, secret):
        self.client = AlpacaClient(api_key, secret)

        self.watchlist = SimpleNamespace(name="Hidden Multiplier", symbols=set())
        self.account = None
        self.market_clock = None
        self.trackers = dict()

    async def on_start(self):
        await self.client.on_start()

        self.account = await self.client.fetch_account_info()
        await self.update_market_clock()
        await self.pull_watchlist()

    async def on_stop(self):
        await self.client.on_stop()

    async def update_market_clock(self):
        self.market_clock = await self.client.fetch_market_clock()

    def as_opening_str(self) -> str:
        flat_watchlist = ",".join(self.watchlist.symbols) or "(empty)"
        return "\n".join(
            (
                f"- market is open: {self.market_clock.is_open}",
                f"- equity: {self.account.equity:.2f} $",
                f"- portfolio: {self.account.portfolio_value:.2f} $",
                f"- cash: {self.account.cash:.2f} $ / {self.account.buying_power:.2f} $",
                f"- watchlist: {flat_watchlist}",
            )
        )

    async def pull_watchlist(self):
        found = await self.client.find_watchlist(named=self.watchlist.name)
        if not found:
            print("Remote watch list does not exist, creating one...")
            await self.client.create_watchlist(named=self.watchlist.name)

        watchlist = await self.client.fetch_watchlist(named=self.watchlist.name)
        for ass in watchlist.assets:
            self.watchlist.symbols.add(ass.symbol)

    async def push_watchlist(self):
        await self.client.update_watchlist(self.watchlist.name, self.watchlist.symbols)

    async def update_positions(self):
        positions = await self.client.fetch_open_positions()

        news = list()
        for pos in positions:
            if pos.symbol not in self.trackers:
                tracker = self.make_tracker(pos.symbol)
                self.trackers[pos.symbol] = tracker
            else:
                tracker = self.trackers[pos.symbol]

            await self.update_tracker(tracker)
            event, is_new = self.strategic_run(tracker)
            if is_new:
                news.append((tracker.symbol, event))

        return news

    def make_tracker(self, symbol: str, cycle=FULL_CYCLE) -> PinkyTracker:
        tracker = PinkyTracker(symbol=symbol, wix=5, maxlen=cycle)
        tracker.read_from(self.CACHE)
        return tracker

    async def update_tracker(self, tracker: PinkyTracker):
        now = datetime.now(timezone.utc)
        a_month_ago = now - timedelta(days=90)
        since = max(tracker.last_timestamp, a_month_ago)
        delta = now - since

        if (self.market_clock.is_open and (delta >= timedelta(minutes=30))) or (
            not self.market_clock.is_open and (delta >= timedelta(hours=16))
        ):
            print(f"Fetching most recent data for {tracker.symbol}, reason:", delta)
            bars = await self.client.fetch_bars(tracker.symbol, since)
            tracker.feed(map(asdict, bars))
            tracker.write_to(self.CACHE)

    def strategic_run(self, tracker: PinkyTracker):
        df = tracker.make_indicators()
        renko_df, size = tracker.compute_renko_bricks(df)
        # print(tracker.symbol, "brick size:", size)

        events, is_new = tracker.run_mariashi_strategy(renko_df)

        if is_new:
            charts_path = os.getenv("OUTPUTS_PATH", "charts")
            tracker.save_renko_chart(renko_df, events, size, path=charts_path)

        return tracker.last_event, is_new

    @cached_property
    def known_commands(self):
        return {func[4:] for func in dir(self) if func.startswith("cmd_")}

    async def run_commands(self, commands):
        for cmd, params in commands:
            func = getattr(self, "cmd_" + cmd)
            await func(params)

    async def cmd_tail(self, params):
        clean_params = set(map(str.upper, params))
        self.watchlist.symbols.update(clean_params)
        for symbol in clean_params:
            self.quotes[symbol] = None
        await self.push_watchlist()

    async def cmd_drop(self, params):
        clean_params = set(map(str.upper, params))
        self.watchlist.symbols.difference_update(clean_params)

        for symbol in clean_params:
            self.quotes.pop(symbol, None)
        await self.push_watchlist()

    async def cmd_reload(self, params):
        for sym in self.watchlist.symbols:
            self.quotes[sym] = dict()


if __name__ == "__main__":
    raise RuntimeError("This is a pure module, cannot be executed.")
