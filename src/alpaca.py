import math
import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import cached_property
from pathlib import Path

from alpaca_client import AlpacaClient, OrderSide, OrderStatus
from broker import PositionBroker, Trend


class AlpacaScavenger:
    CACHE = Path(os.getenv("PRIVATE_CACHE", "."))
    CHARTS_PATH = Path(os.getenv("OUTPUTS_PATH", "charts"))

    def __init__(self, api_key: str, secret):
        self.client = AlpacaClient(api_key, secret)

        self.account = None
        self.market_clock = None
        self.positions = list()
        self.brokers = list()

    async def on_start(self):
        await self.client.on_start()
        await self.update_market_clock()

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
            chart, events = await broker.feed_and_act(bars)
            if chart:
                message = "\n".join(
                    (broker.formatted_value(), ",".join(map(str, events)))
                )
                traces.append((broker.formatted_value(), chart, message))

        return traces

    def overview(self) -> list[str]:
        lines = list()
        market_status = "Open" if self.market_clock.is_open else "Closed"
        lines.append(f"Market is {market_status}.")
        lines.append("--- Open positions ---")
        lines.extend(str(bi) for bi in self.brokers)
        lines.append("--- Account totals ---")
        lines.append(f"Portfolio value: *{self.account.portfolio_value:9.2f}* $")
        lines.append(f"Cash:                  *{self.account.buying_power:9.2f}* $")
        return lines

    async def select_affordable_stocks(self):
        if self.account.buying_power < Decimal(".5"):
            return

        weeks_ago = datetime.now(timezone.utc) - timedelta(days=7)
        friday = datetime.now(timezone.utc) - timedelta(days=3)

        affordable = list()
        most_active = await self.client.fetch_most_active()
        for symbol in most_active:
            bars = await self.client.fetch_bars(symbol, since=weeks_ago, interval="30T")
            last = bars[-1]
            if last.high < (self.account.buying_power * Decimal(".9")):
                affordable.append((symbol, bars))

        fresh_ups = list()
        skip = {"HUGE"}
        for symbol, bars in affordable:
            if symbol in skip:
                continue

            # read at least a full day of open market
            minute_bars = await self.client.fetch_bars(symbol, friday, interval="1T")
            broker, last_event, distance = PositionBroker.from_bars(
                self.client, symbol, minute_bars
            )
            if distance < 3 and last_event == Trend.UP:
                fresh_ups.append(broker)
                broker.trac.draw_chart(self.CHARTS_PATH)

        print()
        for broker in fresh_ups:
            price = broker.trac.current_price.quantize(Decimal(".001"))
            qty = int(self.account.buying_power / price)
            if qty > 0:
                await broker.buy(qty, price)
                self.account.buying_power -= broker.market_value
                self.account.buying_power = self.account.buying_power.quantize(
                    Decimal(".001")
                )
                self.brokers.append(broker)
                print(
                    f"Ordered {qty} x {broker.symbol} @ {price:.3f} $ //"
                    f" {broker.trac.trend} x {broker.trac.strength} ({self.account.buying_power})"
                )

    async def refresh_positions(self):
        self.account = await self.client.fetch_account_info()
        self.positions = await self.client.fetch_open_positions()
        self.brokers = await self.make_brokers_for_open_positions()

    @cached_property
    def known_commands(self):
        return {func[4:] for func in dir(self) if func.startswith("cmd_")}

    async def run_commands(self, commands):
        for cmd, params in commands:
            func = getattr(self, "cmd_" + cmd)
            await func(params)


if __name__ == "__main__":
    raise RuntimeError("This is a pure module, cannot be executed.")
