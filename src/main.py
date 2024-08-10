#!/usr/bin/env python3

import asyncio
import os
import sys
import traceback
from configparser import ConfigParser
from contextlib import asynccontextmanager
from functools import wraps
from signal import SIGINT, SIGTERM

from alpaca import AlpacaScavenger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from tellypatty import TellyPatty

CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.ini")
ERR_TOLERANCE = 3
ISATTY = sys.stdout.isatty()


def error_resilient(fn):
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            return await fn(self, *args, **kwargs)
        except asyncio.CancelledError:
            await self._stop_all_tasks()
        except Exception as err:
            self.err_count += 1
            print(flush=True)
            print("ERROR", self.err_count, "::", repr(err))
            print(traceback.format_exc())

            if self.err_count >= ERR_TOLERANCE:
                await self._stop_all_tasks()

    return wrapper


@asynccontextmanager
async def pretty_go(message):
    cols, _ = os.get_terminal_size() if ISATTY else (80, 0)
    print(f"> {message:{cols - 10}}", flush=True, end="")
    try:
        yield
        print("[ok]")
    except Exception as e:
        print("[failed]", e)


class Seeker:
    def __init__(self, credentials):
        self.err_count = int()
        self.keep_running = False
        self.scheduler = AsyncIOScheduler()
        self.tasks = list()

        self.alpaca = AlpacaScavenger(**credentials["alpaca"])
        self.patty = TellyPatty(
            **credentials["telegram"],
            command_set=self.alpaca.known_commands,
        )

    def asked_to_stop(self):
        print()
        print("\t..: Received shutdown signal")
        self.keep_running = False
        self.scheduler.shutdown(wait=False)

    async def on_start(self):
        await self.patty.on_start()
        await self.alpaca.on_start()

        message = "\n".join(
            (
                "Telepathy channel is up.",
                *self.alpaca.overview(),
            )
        )
        await self.patty.say(message)

    async def on_stop(self):
        await self.alpaca.on_stop()
        await self.patty.on_stop()

    @error_resilient
    async def fast_task(self):
        print(".", end="", flush=True)
        traces = await self.alpaca.track_and_trace()
        for caption, chart, close_message in traces:
            print(caption, chart, close_message)
            await self.patty.selfie(chart, caption=caption)
            if close_message:
                await self.patty.say(close_message)

    @error_resilient
    async def background_task(self):
        data = await self.patty.get_updates(timeout=3)
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

    async def _open_session(self):
        self.err_count = 0
        try:
            await self.on_start()
            self.keep_running = True
        except Exception:
            print(flush=True)
            print(traceback.format_exc())

    async def _close_session(self):
        self.keep_running = False
        await self.on_stop()

    async def _loop(self):
        while self.keep_running:
            await self.background_task()
            await asyncio.sleep(0.55)

    async def _stop_all_tasks(self):
        self.keep_running = False
        self.scheduler.shutdown()

    async def main(self):
        async with pretty_go("install signal handlers"):
            loop = asyncio.get_running_loop()
            for sign in (SIGTERM, SIGINT):
                loop.add_signal_handler(sign, self.asked_to_stop)

        async with pretty_go("create tcp sessions"):
            await self._open_session()

        async with pretty_go("setup async tasks"):
            self.scheduler.add_job(self.fast_task, "interval", minutes=1)
            self.scheduler.add_job(self.hourly, "interval", hours=1)
            task = asyncio.create_task(self._loop())
            self.scheduler.start()

        print("> running")
        await self.hourly()
        await self.fast_task()
        await task

        async with pretty_go("shutdown"):
            await self._close_session()
            if self.scheduler.running:
                self.scheduler.shutdown()


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
