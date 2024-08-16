import math
import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import cached_property
from pathlib import Path

from alpaca_client import AlpacaClient, OrderSide, OrderStatus
from open_trader import MarketSignal, OpenTrader
from position_broker import PositionBroker


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
        self.account = await self.client.fetch_account_info()
        await self.refresh_positions()

    async def on_stop(self):
        await self.client.on_stop()

    async def update_market_clock(self):
        self.market_clock = await self.client.fetch_market_clock()

    def overview(self) -> list[str]:
        lines = list()
        market_status = "Open" if self.market_clock.is_open else "Closed"
        lines.append(f"Market is {market_status}.")
        lines.append("--- Open positions ---")
        lines.extend(bi.formatted_value() for bi in self.brokers)
        lines.append("--- Account totals ---")
        lines.append(f"Portfolio value: *{self.account.portfolio_value:9.2f}* $")
        lines.append(f"Cash:                  *{self.account.buying_power:9.2f}* $")
        lines.append(f"Day-trade count: *{self.account.daytrade_count:9}*")
        return lines

    async def select_affordable_stocks(self):
        if self.account.buying_power < Decimal(".5"):
            return

        weeks_ago = datetime.now(timezone.utc) - timedelta(days=7)
        friday = datetime.now(timezone.utc) - timedelta(days=3)

        affordable = list()
        most_active = await self.client.fetch_most_active()
        for symbol in most_active:
            bars = await self.client.fetch_bars(symbol, since=weeks_ago, interval="1D")
            last = bars[-1]
            if last.high < (self.account.buying_power * Decimal(".9")):
                affordable.append((symbol, bars))

        fresh_ups = list()
        for symbol, bars in affordable:
            strategist = OpenTrader(symbol)
            strategist.read_from(self.CACHE)

            signals = strategist.feed(bars)
            last, distance = OpenTrader.most_recent(signals)

            if distance < 3 and signal == MarketSignal.BUY:
                fresh_ups.append((symbol, bars))

        print()
        for symbol, bars in fresh_ups:
            price = bars[-1].price.quantize(Decimal(".001"))
            qty = int(self.account.buying_power / price)
            if qty > 0:
                # enter position
                order = await self.client.limit_order(OrderSide.BUY, symbol, qty, price)

                # make broker for it
                broker = PositionBroker.from_order(order)
                await broker.react(bars)
                self.brokers.append(broker)

                # update account
                self.account.buying_power -= broker.market_value

                print(
                    f"Ordered {qty} x {broker.symbol} @ {price:.3f} $ //"
                    f" {broker.trac.trend} x {broker.trac.strength} ({self.account.buying_power})"
                )

    async def make_brokers_for_open_positions(self):
        """Lookup orders for every open positions"""
        orders = await self.client.fetch_orders("closed")
        pending = await self.client.fetch_orders("open")

        entry_orders = list()

        positions = await self.client.fetch_open_positions()
        for pos in positions:
            qty = pos.qty
            related_orders = filter(
                lambda o: o.symbol == pos.symbol
                and o.status == OrderStatus.FILLED
                and o.side == OrderSide.BUY,
                orders,
            )
            related_pending = filter(
                lambda o: o.symbol == pos.symbol and o.side == OrderSide.SELL,
                pending,
            )
            while qty:
                order = next(related_orders)
                qty -= order.qty

                selling = next(related_pending, None)
                if not selling:
                    entry_orders.append(order)

        brokers = [PositionBroker.from_order(order=o) for o in entry_orders]
        return brokers

    async def track_and_trace(self):
        traces = list()

        for broker in self.brokers:
            bars = await self.client.fetch_bars(
                broker.symbol, broker.current_time, interval="1T"
            )

            signals, reason = await broker.react(bars)
            last, _ = OpenTrader.most_recent(signals)

            if last == MarketSignal.SELL:
                await self.client.limit_order(**broker.closing_args())

            if signals:
                chart = broker.trac.draw_chart(self.CHARTS_PATH)
                message = "_Trend_:{}, _Signals_: {}, _Reason_: {}".format(
                    f"{broker.trac.trend} x {broker.trac.strength} ({broker.trac.breakout})",
                    ",".join(map(str.format, signals)) or "-empty-",
                    reason,
                )
                traces.append((broker.formatted_value(), chart, message))

        return traces

    async def refresh_positions(self):
        self.account = await self.client.fetch_account_info()
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
