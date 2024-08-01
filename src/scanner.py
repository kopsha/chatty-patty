#!/usr/bin/env python3

import asyncio
import os
from configparser import ConfigParser
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alpaca_client import AlpacaClient
from thinker import FAST_CYCLE, FULL_CYCLE, PinkyTracker

CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.ini")
CACHE = Path(os.getenv("PRIVATE_CACHE", "."))


async def main(credentials):
    a_client = AlpacaClient(**credentials["alpaca"])
    await a_client.on_start()
    market_clock = await a_client.fetch_market_clock()

    await digest_orders(a_client)
    # # get most active stocks
    # active_symbols = await a_client.fetch_most_active(limit=21)
    # print("Most active symbols", active_symbols)
    #
    # # pick first
    # assert active_symbols
    # for symbol in active_symbols:
    #     await analyze(symbol, a_client, market_clock)

    await a_client.on_stop()
    print("gone")

async def digest_orders(client: AlpacaClient):
    pos = await client.fetch_open_positions()
    print(pos)
    # orders = await client.fetch_orders("open")
    # for order in orders:
    #     print("-", order.side, order.symbol, order.status, order.qty)


async def analyze(symbol, client, market_clock, cycle=FULL_CYCLE):
    tracer = PinkyTracker(symbol=symbol, wix=5, maxlen=cycle)
    tracer.read_from(CACHE)

    now = datetime.now(timezone.utc)
    a_month_ago = now - timedelta(days=90)
    since = max(tracer.last_timestamp, a_month_ago)
    delta = now - since

    if (market_clock.is_open and delta >= timedelta(minutes=30)) or (
        not market_clock.is_open and delta >= timedelta(days=2)
    ):
        print("Fetching most recent data, reason:", delta)
        bars = await client.fetch_bars(symbol, since)
        tracer.feed(map(asdict, bars))

    tracer.write_to(CACHE)

    df = tracer.make_indicators()
    renko_df, size = tracer.compute_renko_bricks(df)
    events = tracer.run_mariashi_strategy(renko_df)

    charts_path = os.getenv("OUTPUTS_PATH", "charts")
    tracer.save_renko_chart(renko_df, events, size, path=charts_path)


def read_credentials():
    ini_file = ConfigParser()
    if os.path.isfile(CREDENTIALS_FILE):
        ini_file.read(CREDENTIALS_FILE)
    else:
        with open(CREDENTIALS_FILE, "wt") as storage:
            ini_file["telegram"] = dict(token="", chat_id="")
            ini_file["yahoofinance"] = dict(api_key="")
            ini_file.write(storage)
        raise RuntimeError(
            f"Created empty {CREDENTIALS_FILE}, please fill in and run again."
        )

    credentials = dict()
    for section in ini_file.sections():
        credentials[section] = dict(ini_file[section])

    return credentials


if __name__ == "__main__":
    credentials = read_credentials()
    asyncio.run(main(credentials))
