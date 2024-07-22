import json
import os
from typing import Any
from dataclasses import asdict, is_dataclass
from functools import cached_property
from pathlib import Path
from types import SimpleNamespace

from alpaca_client import AlpacaClient, Bar
from thinker import PinkyTracker


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
        self.quotes = dict()
        self.account = None
        self.is_market_open = False

    async def on_start(self):
        await self.client.on_start()

        self.account = await self.client.fetch_account_info()
        await self.update_market_clock()
        await self.pull_watchlist()

    async def update_market_clock(self):
        response = await self.client.fetch_market_clock()
        self.is_market_open = response.is_open

    async def on_stop(self):
        await self.client.on_stop()

    def as_opening_str(self) -> str:
        flat_watchlist = ",".join(self.watchlist.symbols) or "(empty)"
        return "\n".join(
            (
                f"- market is open: {self.is_market_open}",
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
            self.quotes[ass.symbol] = dict()

    async def push_watchlist(self):
        await self.client.update_watchlist(self.watchlist.name, self.watchlist.symbols)

    async def watch(self):
        has_changed = list()

        if self.is_market_open:
            watchlist = self.watchlist.symbols
        elif any(bool(x) is False for x in self.quotes.values()):
            # NOTE: market is closed but we miss some values
            watchlist = self.watchlist.symbols
        else:
            watchlist = []

        if watchlist:
            quotes = await self.client.fetch_quotes(watchlist)
            for current in quotes:
                previous = self.quotes.get(current.symbol, [])
                if current != previous:
                    has_changed.append(current.symbol)
                    self.quotes[current.symbol] = current

        return has_changed

    async def scan_most_active(self):
        active_symbols = await self.client.fetch_most_active(limit=13)

        print("Most active symbols", active_symbols)

        all_bars = dict()
        for symbol in active_symbols:
            # attempt to read from local cache
            filepath = self.CACHE / f"{symbol}-1h.json"

            if filepath.exists():
                with open(filepath, "rt") as datafile:
                    bars_data = json.loads(datafile.read())
                    bars = [Bar.from_json(data) for data in bars_data]
                print("loaded from cache", filepath)
            else:
                bars = await self.client.fetch_bars(symbol)
                with open(filepath, "wt") as datafile:
                    datafile.write(json.dumps(bars, indent=4, cls=DataclassEncoder))
                print("saved to cache", filepath)

            all_bars[symbol] = bars

        print("retrieved", len(all_bars), "charts data")
        for symbol, bars in all_bars.items():
            tracer = PinkyTracker(symbol=symbol, wix=5)

            tracer.feed(map(asdict, bars))
            df = tracer.make_indicators()

            renko_df, size = tracer.compute_renko_bricks(df)
            events = tracer.run_mariashi_strategy(renko_df)

            charts_path = os.getenv("OUTPUTS_PATH", "charts")
            tracer.save_renko_chart(renko_df, events, size, path=charts_path, suffix="1h")
            # tracer.save_mpf_chart(df, path=charts_path, suffix="1h")
            # tracer.save_mpf_chart(df, path=charts_path, suffix="1h", chart_type="renko")

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
