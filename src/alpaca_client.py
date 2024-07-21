from dataclasses import dataclass, fields
from datetime import datetime
from decimal import Decimal
from enum import StrEnum, auto
from types import SimpleNamespace
from typing import Optional, Union, Type, Self
from uuid import UUID

from hasty import HastyClient


class AlpacaClient:
    API_ROOT = "https://{group}.alpaca.markets/{method}"

    def __init__(self, api_key: str, secret: str):
        self.auth_headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret,
        }
        self.client = None

    async def on_start(self):
        self.client = HastyClient(auth_headers=self.auth_headers)

    async def on_stop(self):
        await self.client.session.close()
        self.client = None

    async def fetch_account_info(self):
        api_url = self.API_ROOT.format(group="api", method="v2/account")
        response = await self.client.get(api_url)
        return Account.from_alpaca(response)

    async def fetch_market_clock(self):
        api_url = self.API_ROOT.format(group="api", method="v2/clock")
        response = await self.client.get(api_url)
        return response

    async def fetch_orders(self):
        api_url = self.API_ROOT.format(group="api", method="v2/orders")
        query = dict(
            status="all",
            limit=500,
            direction="asc",
        )
        response = await self.client.get(api_url, params=query)
        orders = [from_alpaca(Cls=Order, data=data) for data in response]
        return orders

    async def find_watchlist(self, named: str):
        api_url = self.API_ROOT.format(group="api", method="v2/watchlists")
        response = await self.client.get(api_url)
        result = next(filter(lambda x: x.name == named, response), None)
        return result

    async def fetch_watchlist(self, named: str):
        api_url = self.API_ROOT.format(group="api", method="v2/watchlists:by_name")
        query = dict(name=named)
        response = await self.client.get(api_url, params=query)
        return response

    async def create_watchlist(self, named: str, symbols: list[str] = []):
        api_url = self.API_ROOT.format(group="api", method="v2/watchlists")
        data = dict(name=named)
        if symbols:
            data["symbols"] = ",".join(symbols)
        response = await self.client.post(api_url, data=data)
        return response

    async def update_watchlist(self, named: str, symbols: list[str]):
        api_url = self.API_ROOT.format(group="api", method="v2/watchlists:by_name")
        query = dict(name=named)
        data = dict(name=named, symbols=list(symbols))
        response = await self.client.put(api_url, params=query, data=data)
        return response

    async def delete_watchlist(self, named: str):
        api_url = self.API_ROOT.format(group="api", method="v2/watchlists:by_name")
        query = dict(name=named)
        response = await self.client.delete(api_url, params=query)
        return response

    async def fetch_quotes(self, symbols: list[str]):
        api_url = self.API_ROOT.format(group="data", method="v2/stocks/quotes/latest")
        query = dict(feed="iex", symbols=",".join(symbols))
        response = await self.client.get(api_url, params=query)

        quotes = [
            Quote.from_alpaca(data=data, symbol=symbol)
            for symbol, data in response.quotes.__dict__.items()
        ]
        return quotes

    async def fetch_most_active(self):
        api_url = self.API_ROOT.format(
            group="data", method="v1beta1/screener/stocks/most-actives"
        )
        query = dict(top=34, by="volume")
        response = await self.client.get(api_url, params=query)
        symbols = [data.symbol for data in response.most_actives]
        return symbols


@dataclass
class Account:
    equity: Decimal
    buying_power: Decimal
    cash: Decimal
    portfolio_value: Decimal
    currency: str
    account_number: str

    @classmethod
    def from_alpaca(Cls, response: SimpleNamespace) -> Self:
        converted_data = dict()
        decimal_fields = {"equity", "buying_power", "cash", "portfolio_value"}
        string_fields = {"currency", "account_number"}

        for key, value in response.__dict__.items():
            if key in decimal_fields:
                converted_data[key] = Decimal(value)
            elif key in string_fields:
                converted_data[key] = value

        return Cls(**converted_data)


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
    def from_alpaca(symbol: str, data: SimpleNamespace):
        return Quote(
            symbol=symbol,
            ts=data.t,
            ask_price=data.ap,
            ask_size=getattr(data, "as"),
            bid_price=data.bp,
            bid_size=data.bs,
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


def from_alpaca(Cls: Type, data: dict):
    """Create dataclass instance from data"""
    valid_fields = {f.name for f in fields(Cls)}
    valid_data = {k: v for k, v in data.items() if k in valid_fields}
    return Cls(**valid_data)


if __name__ == "__main__":
    raise RuntimeError("This is a pure module, cannot be executed.")
