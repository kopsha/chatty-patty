from aiohttp import ClientSession
from dataclasses import dataclass, fields
from datetime import datetime
from decimal import Decimal
from enum import StrEnum, auto
from functools import cached_property
from types import SimpleNamespace
from typing import Optional, Union, Type, Self
from uuid import UUID


def to_namespace(data):
    """Recursively convert dictionary to SimpleNamespace."""
    if isinstance(data, dict):
        for key, value in data.items():
            data[key] = to_namespace(value)
        return SimpleNamespace(**data)
    elif isinstance(data, list):
        return [to_namespace(item) for item in data]
    else:
        return data


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
                f"_{self.symbol}_:",
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


class AlpacaScavenger:
    API_ROOT = "https://{group}.alpaca.markets"

    def __init__(self, api_key: str, secret, use_session: ClientSession):
        self.auth_headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret,
        }
        self.session = use_session

        self.watchlist = set()
        self.quotes = dict()
        self.account = None
        self.is_market_open = False

    def as_opening_str(self) -> str:
        return "\n".join(
            (
                f"- market is open: {self.is_market_open}",
                f"- equity: {self.account.equity:.2f} $",
                f"- portfolio: {self.account.portfolio_value:.2f} $",
                f"- cash: {self.account.cash:.2f} $ / {self.account.buying_power:.2f} $",
            )
        )

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

    async def watch(self):
        has_changed = list()

        if self.is_market_open:
            watchlist = self.watchlist
        elif any(bool(x) is False for x in self.quotes.values()):
            # NOTE: market is closed but we miss some values
            watchlist = self.watchlist
        else:
            watchlist = []

        if watchlist:
            quotes = await self.fetch_quotes(self.watchlist)
            for current in quotes:
                previous = self.quotes[current.symbol]
                if current != previous:
                    has_changed.append(current.symbol)
                    self.quotes[current.symbol] = current

        return has_changed

    @cached_property
    def known_commands(self):
        return {func[4:] for func in dir(self) if func.startswith("cmd_")}

    def run_commands(self, commands):
        for cmd, params in commands:
            func = getattr(self, "cmd_" + cmd)
            func(params)

    def cmd_tail(self, params):
        clean_params = set(map(str.upper, params))
        self.watchlist.update(clean_params)
        for symbol in clean_params:
            self.quotes[symbol] = None

    def cmd_drop(self, params):
        clean_params = filter(lambda x: x.strip().upper(), params)
        self.watchlist.difference_update(clean_params)
        for symbol in clean_params:
            self.quotes.pop(symbol)


if __name__ == "__main__":
    raise RuntimeError("This is a pure module, cannot be executed.")
