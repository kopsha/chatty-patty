#!/usr/bin/env python3

import asyncio
import os
from configparser import ConfigParser
from functools import partial, wraps
from signal import SIGINT, SIGTERM

from alpaca import AlpacaScavenger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from tellypatty import TellyPatty
from yfapi_client import YahooFinanceClient

CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.ini")
ERR_TOLERANCE = 3


def error_resilient(fn):
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            return await fn(self, *args, **kwargs)
        except asyncio.CancelledError as err:
            await self._stop_all_tasks()
        except Exception as err:
            self.err_count += 1
            print("ERROR", self.err_count, "::", repr(err))

            if self.err_count >= ERR_TOLERANCE:
                await self._stop_all_tasks()

    return wrapper


class Seeker:
    def __init__(self, credentials):
        self.err_count = int()
        self.keep_running = False
        self.scheduler = AsyncIOScheduler()
        self.tasks = list()

        # self.yfapi = YahooFinanceClient(**credentials["yahoofinance"])
        self.alpaca = AlpacaScavenger(**credentials["alpaca"])
        self.patty = TellyPatty(
            **credentials["telegram"],
            command_set=self.alpaca.known_commands,
        )

    def asked_to_stop(self):
        print()
        print("\t..: Received shutdown signal")
        self.keep_running = False
        self.scheduler.shutdown()

    async def on_start(self):
        await self.patty.on_start()
        # await self.yfapi.on_start()
        await self.alpaca.on_start()

        message = "\n".join(
            (
                "Telepathy channel is up and running...",
                self.alpaca.as_opening_str(),
            )
        )
        await self.patty.say(message)

        # await self.alpaca.scan_most_active()

    async def on_stop(self):
        await self.alpaca.on_stop()
        # await self.yfapi.on_stop()

        await self.patty.say("Telepathy channel is closed.")
        await self.patty.on_stop()

    @error_resilient
    async def fast_task(self):
        print(":", end="", flush=True)

        news = await self.alpaca.update_positions()

        if news:
            message = "\n".join(
                (
                    "Something happened",
                    *(f"{symbol} > {event} <" for symbol, event in news),
                )
            )
            await self.patty.say(message)

    @error_resilient
    async def background_task(self):
        print(".", end="", flush=True)

        data = await self.patty.get_updates(timeout=8)
        commands, system_commands, errors = self.patty.digest_updates(data)

        if errors:
            reply = "{}, really?!? Are you high?".format(", ".join(errors))
            await self.patty.say(reply)

        for cmd in system_commands:
            reply = f"Sure, I will do {cmd}."
            await self.patty.say(reply)
            if cmd == "bye":
                await self._stop_all_tasks()

        # TODO: maybe give some feedback on commands
        await self.alpaca.run_commands(commands)

    @error_resilient
    async def hourly(self):
        await self.alpaca.client.fetch_market_clock()
        await self.alpaca.client.fetch_most_active()

    async def _open_session(self):
        self.err_count = 0
        try:
            await self.on_start()
            self.keep_running = True
        except Exception as err:
            print(err.__class__.__name__, "happened during start-up.")
            print(err)

    async def _close_session(self):
        self.keep_running = False
        await self.on_stop()

    async def _loop(self):
        while self.keep_running:
            await self.background_task()
            await asyncio.sleep(0.21)

    async def _stop_all_tasks(self):
        self.keep_running = False
        self.scheduler.shutdown()

    async def main(self):
        print("initializing...")

        loop = asyncio.get_running_loop()
        for sign in (SIGTERM, SIGINT):
            loop.add_signal_handler(sign, self.asked_to_stop)

        await self._open_session()
        self.scheduler.add_job(self.fast_task, "interval", minutes=5)
        self.scheduler.add_job(self.hourly, "interval", hours=1)
        self.scheduler.start()

        task = asyncio.create_task(self._loop())
        print("starting main task")
        await task

        print("shutting down...")
        if self.scheduler.running:
            self.scheduler.shutdown()

        await self._close_session()

        print("main task was gracefully stopped")


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
    seeker = Seeker(credentials)

    try:
        asyncio.run(seeker.main())
    except KeyboardInterrupt:
        print("Can we stop nicely?")
