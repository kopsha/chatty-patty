#!/usr/bin/env python3

import aiohttp
import asyncio
import certifi
import os
import ssl
import time
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from configparser import ConfigParser

from tellypatty import TellyPatty
from alphaseek import AlphaSeek


CREDENTIALS_FILE = "credentials.ini"


class Seeker:
    def __init__(self, credentials):
        self.credentials = credentials
        self.session = None
        self.patty: TellyPatty = None
        self.alpha: AlphaSeek = None
        self.last_time = None

    async def start_session(self):
        ssl_context = ssl.create_default_context(cafile=certifi.where())

        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=ssl_context)
        )
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

    async def stop_session(self):
        await self.patty.say("Bye!")

        self.save_internals()
        self.patty = None
        self.alpha = None
        await self.session.close()
        self.session = None

    async def patty_updates(self):
        if not (self.patty and self.alpha):
            return

        print(".", end="", flush=True)

        data = await self.patty.get_updates()
        commands, errors = self.patty.digest_updates(data)
        if errors:
            reply = "I don't understand {}".format(", ".join(errors))
            await self.patty.say(reply)

        self.alpha.run_commands(commands)
        # TODO: maybe give some feedback on commands

    async def fast_task(self):
        now = time.clock_gettime_ns(time.CLOCK_MONOTONIC)

        if self.last_time:
            delta = float(now - self.last_time) / 1_000_000
            print(f"took {delta:,.6f} seconds")

        self.last_time = now

    async def slow_task(self):
        error_count = 0
        while self.alpha.keep_alive:
            try:
                await self.patty_updates()
                await asyncio.sleep(0.21)

                if error_count:
                    error_count -= 1
            except Exception as err:
                error_count += 1
                print(err, "happened", error_count)

                if error_count > 2:
                    print("Too many errors occurred, stopping...")
                    self.alpha.keep_alive = False

    async def main(self):
        await self.start_session()

        scheduler = AsyncIOScheduler()
        scheduler.add_job(self.fast_task, "interval", seconds=13)
        scheduler.start()

        task = asyncio.create_task(self.slow_task())
        try:
            await task
        except (KeyboardInterrupt, SystemExit):
            pass

        scheduler.shutdown()

        self.patty.save_internals()
        await self.stop_session()


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
