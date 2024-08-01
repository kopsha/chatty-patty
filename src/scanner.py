#!/usr/bin/env python3

import asyncio
import os
from dataclasses import asdict
from configparser import ConfigParser
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alpaca_client import AlpacaClient, Bar
from thinker import FAST_CYCLE, PinkyTracker

CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.ini")
CACHE = Path(os.getenv("PRIVATE_CACHE", "."))


async def main(credentials):

    a_client = AlpacaClient(**credentials["alpaca"])
    await a_client.on_start()

    # get most active stocks
    # active_symbols = await a_client.fetch_most_active(limit=3)
    active_symbols = ["NVDA", "AMD", "TSLA"]
    print("Most active symbols", active_symbols)
    cycle = FAST_CYCLE

    # pick first
    assert active_symbols
    symbol = active_symbols[0]
    tracer = PinkyTracker(symbol=symbol, wix=5, maxlen=cycle)
    tracer.read_from(CACHE)

    now = datetime.now(timezone.utc)
    a_month_ago = now - timedelta(days=30)
    since = max(tracer.last_timestamp, a_month_ago)
    delta = now - since

    if delta >= timedelta(minutes=30):
        # fetch recent bars
        bars = await a_client.fetch_bars(symbol, since)
        tracer.feed(map(asdict, bars))

    tracer.write_to(CACHE)


    # all_bars = dict()
    # for symbol in active_symbols:
    #
    #     else:
    #
    #     all_bars[symbol] = bars

    # print("retrieved", len(all_bars), "charts data")
    # for symbol, bars in all_bars.items():
    #     tracer = PinkyTracker(symbol=symbol, wix=5)
    #
    #     tracer.feed(map(asdict, bars))
    #     df = tracer.make_indicators()
    #
    #     renko_df, size = tracer.compute_renko_bricks(df)
    #     events = tracer.run_mariashi_strategy(renko_df)
    #
    #     charts_path = os.getenv("OUTPUTS_PATH", "charts")
    #     tracer.save_renko_chart(renko_df, events, size, path=charts_path, suffix="1h")
    #     # tracer.save_mpf_chart(df, path=charts_path, suffix="1h")
    #     # tracer.save_mpf_chart(df, path=charts_path, suffix="1h", chart_type="renko")

    # read local files
    # request latest for each
    # run analysis for each

    await a_client.on_stop()
    print("gone")


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
