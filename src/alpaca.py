from functools import cached_property
from types import SimpleNamespace

from alpaca_client import AlpacaClient

class AlpacaScavenger:

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
