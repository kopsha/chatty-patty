from dataclasses import dataclass, fields
from datetime import datetime
from decimal import Decimal
from enum import StrEnum, auto
from types import SimpleNamespace
from typing import Self
from uuid import UUID

from hasty import HastyClient


@dataclass
class Account:
    equity: Decimal
    buying_power: Decimal
    cash: Decimal
    portfolio_value: Decimal
    currency: str
    account_number: str

    @classmethod
    def from_alpaca(cls: Self, response: SimpleNamespace) -> Self:
        converted_data = dict()
        decimal_fields = {"equity", "buying_power", "cash", "portfolio_value"}
        string_fields = {"currency", "account_number"}

        for key, value in response.__dict__.items():
            if key in decimal_fields:
                converted_data[key] = Decimal(value)
            elif key in string_fields:
                converted_data[key] = value

        return cls(**converted_data)


@dataclass
class Quote:
    bid_price: Decimal
    bid_size: int
    ask_price: Decimal
    ask_size: int
    ts: str

    @staticmethod
    def from_alpaca(data: SimpleNamespace):
        return Quote(
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
    type: OrderType
    side: OrderSide
    status: OrderStatus
    qty: int = 0
    filled_qty: int = 0
    filled_avg_price: Decimal = Decimal()
    limit_price: Decimal = Decimal()
    stop_price: Decimal = Decimal()
    order_class: OrderClass = OrderClass.SIMPLE

    @classmethod
    def from_alpaca(cls: Self, data: SimpleNamespace):
        valid_fields = {f.name: f.type for f in fields(cls)}
        valid_data = dict()
        for k, v in vars(data).items():
            if v and k in valid_fields:
                typed = valid_fields[k]
                if k.endswith("_at"):
                    typed_value = datetime.fromisoformat(v)
                else:
                    typed_value = typed(v)
                valid_data[k] = typed_value
        return cls(**valid_data)


@dataclass
class Bar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    trades: int
    vw_price: float

    @classmethod
    def from_alpaca(cls, data: SimpleNamespace) -> Self:
        return cls(
            timestamp=int(datetime.fromisoformat(data.t).timestamp()),
            open=float(data.o),
            high=float(data.h),
            low=float(data.l),
            close=float(data.c),
            volume=float(data.v),
            trades=int(data.n),
            vw_price=float(data.vw),
        )

    @classmethod
    def from_json(cls, data: dict) -> Self:
        return cls(**data)


@dataclass
class Position:
    asset_id: UUID
    symbol: str
    side: str
    qty: int
    qty_available: int
    market_value: Decimal
    current_price: Decimal
    lastday_price: Decimal
    unrealized_pl: Decimal
    unrealized_plpc: Decimal

    @classmethod
    def from_alpaca(cls: Self, data: SimpleNamespace):
        valid_fields = {f.name: f.type for f in fields(cls)}
        valid_data = {
            k: valid_fields[k](v) for k, v in vars(data).items() if k in valid_fields
        }
        return cls(**valid_data)


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

    async def fetch_orders(self, status="all"):
        api_url = self.API_ROOT.format(group="api", method="v2/orders")
        query = dict(
            status=status,
            limit=500,
            direction="desc",
        )
        response = await self.client.get(api_url, params=query)
        orders = [Order.from_alpaca(data) for data in response]
        return orders

    async def limit_order(self, side: OrderSide, symbol: str, qty: int, price: Decimal):
        api_url = self.API_ROOT.format(group="api", method="v2/orders")
        intentions = {
            OrderSide.SELL: "sell_to_close",
            OrderSide.BUY: "buy_to_open",
        }
        payload = dict(
            symbol=symbol,
            qty=str(qty),
            side=str(side),
            type=str(OrderType.LIMIT),
            time_in_force="gtc",
            limit_price=str(price),
            position_intent=intentions[side],
        )
        response = await self.client.post(api_url, data=payload)
        return Order.from_alpaca(response)

    async def cancel_order(self, by_id: UUID):
        api_url = self.API_ROOT.format(group="api", method="v2/orders")
        await self.client.delete(api_url + "/" + str(by_id))

    async def fetch_open_positions(self):
        api_url = self.API_ROOT.format(group="api", method="v2/positions")
        response = await self.client.get(api_url)
        positions = [Position.from_alpaca(data) for data in response]
        return positions

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

    async def fetch_most_active(self, limit: int = 34):
        api_url = self.API_ROOT.format(
            group="data", method="v1beta1/screener/stocks/most-actives"
        )
        query = dict(top=limit, by="trades")
        response = await self.client.get(api_url, params=query)
        symbols = [data.symbol for data in response.most_actives]
        return symbols

    async def fetch_quotes(self, symbol: str, since: datetime):
        api_url = self.API_ROOT.format(group="data", method="v2/stocks/quotes")
        query = dict(
            feed="iex",
            symbols=symbol,
            start=since.isoformat(),
        )
        quotes = list()
        next_token = True
        count = 0
        while next_token:
            response = await self.client.get(api_url, params=query)
            next_token = response.next_page_token
            query["page_token"] = next_token

            if vars(response.quotes):
                quotes_data = getattr(response.quotes, symbol)
                quotes.extend(Quote.from_alpaca(data) for data in quotes_data)
            count += 1

        return quotes

    async def fetch_latest_quote(self, symbol: str):
        api_url = self.API_ROOT.format(group="data", method="v2/stocks/quotes/latest")
        query = dict(
            feed="iex",
            symbols=symbol,
        )
        response = await self.client.get(api_url, params=query)
        quotes = list()
        if vars(response.quotes):
            data = getattr(response.quotes, symbol)
            quotes.append(Quote.from_alpaca(data))

        return quotes

    async def fetch_bars(self, symbol: str, since: datetime, interval: str = "30T"):
        api_url = self.API_ROOT.format(group="data", method="v2/stocks/bars")
        query = dict(
            feed="iex",
            symbols=symbol,
            timeframe=interval,
            start=since.isoformat(),
        )

        bars = list()
        next_token = True

        count = 0
        while next_token:
            response = await self.client.get(api_url, params=query)
            next_token = response.next_page_token
            query["page_token"] = next_token

            bars_data = getattr(response.bars, symbol)
            bars.extend(Bar.from_alpaca(data) for data in bars_data)
            count += 1

        return bars

    async def fetch_snapshot(self, symbol: str):
        api_url = self.API_ROOT.format(group="data", method=f"v2/stocks/snapshots")
        query = dict(
            feed="iex",
            symbols=symbol,
        )
        response = await self.client.get(api_url, params=query)
        return response


if __name__ == "__main__":
    raise RuntimeError("This is a pure module, cannot be executed.")
