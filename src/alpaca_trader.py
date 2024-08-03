import os
from decimal import Decimal
from pathlib import Path

from alpaca_client import AlpacaClient, Order, OrderSide, Position


class AlpacaTrader:
    CACHE = Path(os.getenv("PRIVATE_CACHE", "."))

    def __init__(
        self,
        client: AlpacaClient,
        symbol: str | None = None,
        position: Position | None = None,
        order: Order | None = None,
    ):
        self.client = client
        self.position: Position | None = None
        self.order: Order | None = None
        self.qty = 0

        if order:
            self.order = order
            self.symbol = order.symbol
            self.qty = order.filled_qty
        elif position:
            self.position = position
            self.symbol = position.symbol
            self.qty = position.qty
        else:
            self.symbol = symbol

    async def buy(self, qty: int, price: Decimal):
        if self.order:
            await self.client.cancel_order(self.order.id)
        self.order = await self.client.limit_order(OrderSide.BUY, self.symbol, qty, price)

    async def sell(self, price: Decimal):
        if self.order:
            await self.client.cancel_order(self.order.id)
        self.order = await self.client.limit_order(
            OrderSide.SELL, self.symbol, self.qty, price
        )


if __name__ == "__main__":
    raise RuntimeError("This is a pure module, cannot be executed.")
