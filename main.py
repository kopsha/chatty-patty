#!/usr/bin/env python3

import asyncio
import certifi
import os
import ssl
from functools import wraps
from aiohttp import ClientSession, TCPConnector
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from configparser import ConfigParser

from tellypatty import TellyPatty
from alphaseek import AlphaSeek


CREDENTIALS_FILE = "credentials.ini"
ERR_TOLERANCE = 3


def error_resilient(fn):
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            return await fn(self, *args, **kwargs)
        except Exception as err:
            self.err_count += 1
            print("ERROR", self.err_count, "::", err)

            if self.err_count > ERR_TOLERANCE:
                print("That's too many, stopping...")
                self.keep_running = False

    return wrapper


class Seeker:
    def __init__(self, credentials):
        self.credentials = credentials
        self.session = None
        self.err_count = None
        self.keep_running = None
        self.patty: TellyPatty = None
        self.alpha: AlphaSeek = None

    async def on_start(self):
        self.alpha = AlphaSeek(
            **self.credentials["yahoofinance"], use_session=self.session
        )
        self.patty = TellyPatty(
            **self.credentials["telegram"],
            command_set=self.alpha.known_commands,
            use_session=self.session,
        )
        self.patty.load_internals()
        await self.patty.say("Hey!")

    async def on_stop(self):
        await self.patty.say("Bye!")

        self.patty.save_internals()
        self.patty = None
        self.alpha = None

    @error_resilient
    async def fast_task(self):
        print(".", end="", flush=True)

        changed_symbols = await self.alpha.watch()
        for symbol in changed_symbols:
            msg = "{}%0A{}".format(
                symbol,
                "%0A".join(AlphaSeek.pretty_q(self.alpha.quotes[symbol])),
            )
            await self.patty.say(msg)

    @error_resilient
    async def slow_task(self):
        print(".", end="", flush=True)

        data = await self.patty.get_updates()
        commands, errors = self.patty.digest_updates(data)
        if errors:
            reply = "I don't understand {}".format(", ".join(errors))
            await self.patty.say(reply)

        self.alpha.run_commands(commands)
        # TODO: maybe give some feedback on commands

    async def _open_session(self):
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.session = ClientSession(connector=TCPConnector(ssl=ssl_context))
        self.err_count = 0
        self.keep_running = True

        await self.on_start()

    async def _close_session(self):
        self.keep_running = False

        await self.on_stop()

        await self.session.close()
        self.session = None

    async def _loop(self):
        while self.keep_running:
            await self.slow_task()
            await asyncio.sleep(0.21)

    async def main(self):
        await self._open_session()

        scheduler = AsyncIOScheduler()
        scheduler.add_job(self.fast_task, "interval", seconds=21)
        scheduler.start()

        task = asyncio.create_task(self._loop())
        try:
            await task
        except (KeyboardInterrupt, SystemExit):
            pass

        scheduler.shutdown()

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
