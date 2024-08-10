import math
import os
from copy import deepcopy
from dataclasses import asdict
from functools import cached_property
from pathlib import Path

from alpaca_client import AlpacaClient, OrderSide, OrderStatus, Position
from broker import TREND_ICON, PositionBroker


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

    async def on_stop(self):
        await self.client.on_stop()

    async def refresh_spreads(self):
        print()
        for pos in self.positions:
            if quote := await self.client.fetch_latest_quote(pos.symbol):
                if quote.ask_size and quote.bid_size:
                    spread = (quote.ask_price - quote.bid_price) * 100 / quote.ask_price
                else:
                    spread = math.inf

                print(f"{pos.symbol}: Spread {spread:.2f} %, {quote}")
            else:
                print(f"\t{pos.symbol}: no quote")

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
        positions = [Position(symbol="SERV", qty=1)]

        for pos in positions:
            qty = pos.qty
            related_orders = filter(
                lambda o: o.symbol == pos.symbol
                and o.status == OrderStatus.FILLED
                and o.side == OrderSide.BUY,
                orders,
            )
            while qty:
                order = next(related_orders)
                entry_orders.append(order)
                qty -= order.qty

        brokers = [PositionBroker(self.client, order=o) for o in entry_orders]
        return brokers

    async def track_and_trace(self):
        traces = list()

        for broker in self.brokers:
            bars = await self.client.fetch_bars(
                broker.symbol, broker.current_time, interval="1T"
            )

            broker.trac.update_brick_size(list(map(asdict, bars))[:30])

            events, chart, closed = await broker.feed_and_act(map(asdict, bars))
            for event in events:
                print(TREND_ICON[event], end="")

            message = (
                f"Downtrend breakout triggered exit at {broker.exit_price}"
                if closed
                else None
            )
            if chart:
                traces.append((broker.formatted_value(), chart, message))

        return traces

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
