#!/usr/bin/env python3

import asyncio
import os
from functools import wraps
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from configparser import ConfigParser

from tellypatty import TellyPatty
# from alpaca import AlpacaScavenger

CREDENTIALS_FILE = "credentials.ini"
ERR_TOLERANCE = 1


def error_resilient(fn):
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            return await fn(self, *args, **kwargs)
        except Exception as err:
            self.err_count += 1
            print("ERROR", self.err_count, "::", repr(err))

            if self.err_count >= ERR_TOLERANCE:
                await self._stop_all_tasks()

    return wrapper


class Seeker:
    def __init__(self, credentials):
        self.err_count = None
        self.keep_running = None
        self.scheduler = AsyncIOScheduler()

        self.patty = TellyPatty(
            **credentials["telegram"],
            command_set=set(["expose", "bye"]),
        )

    async def on_start(self):
        await self.patty.on_start()

        # await self.alpaca.fetch_account_info()
        # await self.alpaca.fetch_market_clock()
        # await self.alpaca.setup_watchlists()

        message = "\n".join(
            (
                "Telepathy channel is up and running...",
                # self.alpaca.as_opening_str(),
            )
        )
        await self.patty.say(message)

    async def on_stop(self):
        await self.patty.say("Telepathy channel is closed.")
        await self.patty.on_stop()

    @error_resilient
    async def fast_task(self):
        print(".", end="", flush=True)

        # changed_symbols = await self.alpaca.watch()
        # for symbol in changed_symbols:
        #     msg = str(self.alpaca.quotes[symbol])
        #     await self.patty.say(msg)

    @error_resilient
    async def background_task(self):
        print(":", end="", flush=True)

        data = await self.patty.get_updates(timeout=34)
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
        # await self.alpaca.run_commands(commands)

    @error_resilient
    async def hourly(self):
        self.alpaca.fetch_market_clock()
        self.alpaca.fetch_most_active()

    async def _open_session(self):
        self.err_count = 0
        self.keep_running = True
        await self.on_start()

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
        await self._open_session()

        self.scheduler.add_job(self.fast_task, "interval", seconds=2)
        self.scheduler.add_job(self.hourly, "interval", hours=1)
        self.scheduler.start()

        print("starting main task")
        task = asyncio.create_task(self._loop())
        try:
            await task
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            pass

        print("\nstopped main task")
        if self.scheduler.running:
            self.scheduler.shutdown()

        await self._close_session()


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
    asyncio.run(seeker.main())
