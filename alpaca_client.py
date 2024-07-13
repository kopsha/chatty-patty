from dataclasses import dataclass, fields
from datetime import datetime
from decimal import Decimal
from enum import StrEnum, auto
from functools import cached_property
from types import SimpleNamespace
from typing import Optional, Union, Type, Self
from uuid import UUID

from hasty import HastyClient


class AlpacaScavenger:
    API_ROOT = "https://{group}.alpaca.markets"

    def __init__(self, api_key: str, secret: str):
        self.auth_headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret,
        }
        self.client = None

        self.watchlist = SimpleNamespace(name="Hidden Multiplier", symbols=set())
        self.quotes = dict()
        self.account = None
        self.is_market_open = False

    async def on_start(self):
        self.client = HastyClient(auth_headers=self.auth_headers)

    async def on_stop(self):
        self.client = None

    async def fetch_account_info(self):
        url = f"{self.API_ROOT}/v2/account".format(group="api")

        async with self.session.get(
            url,
            headers=self.auth_headers,
            raise_for_status=True,
        ) as response:
            response_data = await response.json()

        self.account = Account.from_alpaca(data=response_data)

    async def fetch_market_clock(self):
        url = f"{self.API_ROOT}/v2/clock".format(group="api")
        async with self.session.get(
            url,
            headers=self.auth_headers,
            raise_for_status=True,
        ) as response:
            response_data = await response.json()

        self.is_market_open = response_data["is_open"]

    async def fetch_orders(self):
        url = f"{self.API_ROOT}/v2/orders".format(group="api")
        query = dict(
            status="all",
            limit=500,
            direction="asc",
        )

        async with self.session.get(
            url,
            headers=self.auth_headers,
            params=query,
            raise_for_status=True,
        ) as response:
            response_data = await response.json()

        orders = [from_alpaca(Cls=Order, data=data) for data in response_data]
        return orders

    async def setup_watchlists(self):
        watchlist = await self.fetch_watchlist()
        if hasattr(watchlist, "assets"):
            print("Watchlist already exist, refreshing assets...")
            for ass in watchlist.assets:
                self.watchlist.symbols.add(ass.symbol)
                self.quotes[ass.symbol] = dict()
        else:
            print("Watchlist does not exist, creating one...")
            await self.create_watchlist()

    async def fetch_watchlists(self):
        url = f"{self.API_ROOT}/v2/watchlists".format(group="api")
        async with self.session.get(
            url,
            headers=self.auth_headers,
            params=dict(name=self.watchlist.name),
            raise_for_status=True,
        ) as response:
            response_data = await response.json()
        return to_namespace(response_data)

    async def create_watchlist(self):
        url = f"{self.API_ROOT}/v2/watchlists".format(group="api")
        data = dict(name=self.watchlist.name)
        if self.watchlist.symbols:
            data["symbols"] = ",".join(self.watchlist.symbols)

        async with self.session.post(
            url,
            headers=self.auth_headers,
            raise_for_status=True,
            json=data,
        ) as response:
            response_data = await response.json()

        return to_namespace(response_data)

    async def fetch_watchlist(self):
        url = f"{self.API_ROOT}/v2/watchlists:by_name".format(group="api")
        async with self.session.get(
            url,
            headers=self.auth_headers,
            params=dict(name=self.watchlist.name),
        ) as response:
            if response.status == 200:
                response_data = await response.json()
            else:
                response_data = dict()
        return to_namespace(response_data)

    async def update_watchlist(self):
        url = f"{self.API_ROOT}/v2/watchlists:by_name".format(group="api")
        data = dict(
            name=self.watchlist.name,
            symbols=list(self.watchlist.symbols),
        )
        async with self.session.put(
            url,
            headers=self.auth_headers,
            params=dict(name=self.watchlist.name),
            raise_for_status=True,
            json=data,
        ) as response:
            response_data = await response.json()

        return to_namespace(response_data)

    async def delete_watchlist(self, by_id):
        url = f"{self.API_ROOT}/v2/watchlists/{by_id}".format(group="api")
        await self.session.delete(
            url,
            headers=self.auth_headers,
            raise_for_status=True,
        )

    async def fetch_quotes(self, symbols):
        url = f"{self.API_ROOT}/v2/stocks/quotes/latest".format(group="data")
        query = dict(feed="iex", symbols=",".join(symbols))

        async with self.session.get(
            url,
            headers=self.auth_headers,
            params=query,
            raise_for_status=True,
        ) as response:
            response_data = await response.json()

        quotes = [
            Quote.from_alpaca(data=data, symbol=symbol)
            for symbol, data in response_data["quotes"].items()
        ]
        return quotes

    async def fetch_most_active(self):
        url = f"{self.API_ROOT}/v1beta1/screener/stocks/most-actives".format(
            group="data"
        )
        query = dict(top=34, by="volume")

        async with self.session.get(
            url,
            headers=self.auth_headers,
            params=query,
            raise_for_status=True,
        ) as response:
            response_data = await response.json()

        symbols = [to_namespace(data).symbol for data in response_data["most_actives"]]
        return symbols

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
            quotes = await self.fetch_quotes(watchlist)
            for current in quotes:
                previous = self.quotes.get(current.symbol, [])
                if current != previous:
                    has_changed.append(current.symbol)
                    self.quotes[current.symbol] = current

        return has_changed

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
        await self.update_watchlist()

    async def cmd_drop(self, params):
        clean_params = set(map(str.upper, params))
        self.watchlist.symbols.difference_update(clean_params)
        for symbol in clean_params:
            self.quotes.pop(symbol)
        await self.update_watchlist()

    async def cmd_reload(self, params):
        for sym in self.watchlist.symbols:
            self.quotes[sym] = dict()


@dataclass
class Quote:
    symbol: str
    bid_price: Decimal
    bid_size: int
    ask_price: Decimal
    ask_size: int
    ts: str

    def __str__(self) -> str:
        return "\n".join(
            (
                f"_{self.symbol}_",
                f"bid: {self.bid_price:7.2f} $ (x {self.bid_size})",
                f"ask: {self.ask_price:7.2f} $ (x {self.ask_size})",
            )
        )

    @staticmethod
    def from_alpaca(symbol: str, data: dict):
        return Quote(
            symbol=symbol,
            ts=data["t"],
            ask_price=data["ap"],
            ask_size=data["as"],
            bid_price=data["bp"],
            bid_size=data["bs"],
        )


class OrderStatus(StrEnum):
    NEW = auto()
    PARTIALLY_FILLED = auto()
    FILLED = auto()
    DONE_FOR_DAY = auto()
    CANCELED = auto()
    EXPIRED = auto()
    REPLACED = auto()
    PENDING_CANCEL = auto()
    PENDING_REPLACE = auto()

    # NOTE: less common states
    ACCEPTED = auto()
    PENDING_NEW = auto()
    ACCEPTED_FOR_BIDDING = auto()
    STOPPED = auto()
    REJECTED = auto()
    SUSPENDED = auto()
    CALCULATED = auto()


class OrderType(StrEnum):
    MARKET = auto()
    LIMIT = auto()
    STOP = auto()
    STOP_LIMIT = auto()
    TRAILING_STOP = auto()


class OrderClass(StrEnum):
    SIMPLE = auto()
    BRACKET = auto()
    OCO = auto()
    OTO = auto()


class OrderSide(StrEnum):
    BUY = auto()
    SELL = auto()


@dataclass
class Order:
    id: UUID
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime
    symbol: str
    order_class: OrderClass
    type: OrderType
    side: OrderSide
    status: OrderStatus

    notional: Optional[Union[Decimal, str]] = None
    qty: Optional[Union[int, str]] = None
    filled_qty: Union[int, str] = 0
    filled_avg_price: Optional[Union[Decimal, str]] = None
    limit_price: Optional[Union[Decimal, str]] = None
    stop_price: Optional[Union[Decimal, str]] = None
    extended_hours: bool = False
    trail_percent: Optional[Union[Decimal, str]] = None
    trail_price: Optional[Union[Decimal, str]] = None


@dataclass
class Account:
    equity: Decimal
    buying_power: Decimal
    cash: Decimal
    portfolio_value: Decimal
    currency: str
    account_number: str

    @classmethod
    def from_alpaca(Cls, data) -> Self:
        converted_data = dict()
        decimal_fields = {"equity", "buying_power", "cash", "portfolio_value"}
        string_fields = {"currency", "account_number"}

        for key, value in data.items():
            if key in decimal_fields:
                converted_data[key] = Decimal(value)
            elif key in string_fields:
                converted_data[key] = value

        return Cls(**converted_data)


def from_alpaca(Cls: Type, data: dict):
    """Create dataclass instance from data"""
    valid_fields = {f.name for f in fields(Cls)}
    valid_data = {k: v for k, v in data.items() if k in valid_fields}
    return Cls(**valid_data)


if __name__ == "__main__":
    raise RuntimeError("This is a pure module, cannot be executed.")
