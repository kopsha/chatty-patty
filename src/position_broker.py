import os
from dataclasses import fields
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from alpaca_client import Bar, Order, OrderSide
from open_trader import CandleStick, MarketSignal, MarketTrend, OpenTrader


def to_stick(bar: Bar) -> CandleStick:
    valid_fields = {f.name: f.type for f in fields(CandleStick)}
    valid_data = dict()
    for k, v in vars(bar).items():
        if v and k in valid_fields:
            typed = valid_fields[k]
            typed_value = typed(v)
            valid_data[k] = typed_value
    return CandleStick(**valid_data)


class PositionBroker:
    CACHE = Path(os.getenv("PRIVATE_CACHE", "."))
    CHARTS_PATH = Path(os.getenv("OUTPUTS_PATH", "charts"))

    @classmethod
    def from_order(cls, order: Order):
        instance = cls(order.symbol, order.filled_qty, order.filled_avg_price)
        instance.trac.read_from(cls.CACHE)
        return instance

    def __init__(self, symbol: str, qty: int, price: Decimal):
        self.symbol = symbol
        self.qty = qty
        self.open_price = price
        self.stop_loss_limit = price * Decimal(".925")
        self.trac = OpenTrader(symbol=symbol)

    @property
    def current_price(self) -> Decimal:
        return self.trac.data[-1].close

    @property
    def current_time(self) -> datetime:
        ts = self.trac.data[-1].timestamp
        moment = datetime.fromtimestamp(ts, timezone.utc)
        return moment

    @property
    def market_value(self) -> Decimal:
        return self.qty * self.current_price

    @property
    def entry_cost(self) -> Decimal:
        return self.qty * self.open_price

    def formatted_value(self) -> str:
        return f"*{self.symbol}: {self.qty} x {self.current_price:.2f} $ = *{self.market_value:.2f}* $"

    def formatted_entry(self) -> str:
        return f"*{self.symbol}*: {self.qty} x {self.open_price:.2f} $ = *{self.entry_cost:.2f}* $"

    async def closing_args(self) -> dict:
        return dict(
            side=OrderSide.SELL,
            symbol=self.symbol,
            qty=self.qty,
            price=self.current_price,
        )

    async def react(self, bars: list[Bar]) -> list[MarketSignal]:
        """Exit positioon for stop-loss or detecting a downtrend"""

        signals = self.trac.feed(to_stick(bi) for bi in bars)
        self.trac.write_to(self.CACHE)

        price = Decimal(bars[-1].close)
        if price <= self.stop_loss_limit or self.trac.trend == MarketTrend.DOWN:
            # Kind of an emergency exit
            return [MarketSignal.SELL]

        return signals


if __name__ == "__main__":
    raise RuntimeError("This is a pure module, cannot be executed.")
