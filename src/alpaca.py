import json
import os
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from functools import cached_property
from pathlib import Path
from typing import Any

from alpaca_client import AlpacaClient, OrderStatus
from broker import PositionBroker


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
        self.positions = list()
        self.brokers = list()

    async def on_start(self):
        await self.client.on_start()

        await self.update_market_clock()
        self.account = await self.client.fetch_account_info()
        self.positions = await self.client.fetch_open_positions()
        self.brokers = await self.make_brokers_for_open_positions()

        for one in self.brokers:
            await self.replay_broker(one)

    async def on_stop(self):
        await self.client.on_stop()

    async def update_market_clock(self):
        self.market_clock = await self.client.fetch_market_clock()

    async def make_brokers_for_open_positions(self):
        """
        just a little back tracking:
        lookup orders and positions
        """
        orders = await self.client.fetch_orders("closed")

        entry_orders = list()
        positions = deepcopy(self.positions)
        for pos in positions:
            qty = pos.qty
            related_orders = filter(
                lambda o: o.symbol == pos.symbol and o.status == OrderStatus.FILLED,
                orders,
            )
            while qty:
                order = next(related_orders)
                entry_orders.append(order)
                qty -= order.qty

        bs = dict(NCNC=Decimal(0.015), SERV=Decimal(0.859))
        brokers = [
            PositionBroker(self.client, order=o, brick_size=bs[o.symbol])
            for o in entry_orders
        ]
        return brokers

    async def replay_broker(self, broker: PositionBroker):
        print("---\n", broker.entry_time)
        bars = await self.client.fetch_bars(broker.symbol, broker.entry_time, interval="1T")

        print("got", len(bars), "points")
        for bar in bars:
            broker.feed([asdict(bar)])

    def overview(self) -> str:
        lines = list()

        market_status = "Open" if self.market_clock.is_open else "Closed"
        lines.append(f"Market is {market_status}.")
        lines.append("--- Open positions ---")

        lines.extend(str(bi) for bi in self.brokers)

        lines.append("--- Account totals ---")
        lines.append(f"Portfolio value: *{self.account.portfolio_value:9.2f}* $")
        lines.append(f"Cash:                  *{self.account.cash:9.2f}* $")

        return lines

    @cached_property
    def known_commands(self):
        return {func[4:] for func in dir(self) if func.startswith("cmd_")}

    async def run_commands(self, commands):
        for cmd, params in commands:
            func = getattr(self, "cmd_" + cmd)
            await func(params)


if __name__ == "__main__":
    raise RuntimeError("This is a pure module, cannot be executed.")
