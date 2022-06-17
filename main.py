#!/usr/bin/env python3

import asyncio
import aiohttp
import aioschedule as schedule
import os
import time
from configparser import ConfigParser

from tellypatty import TellyPatty
from alphaseek import AlphaSeek


CREDENTIALS_FILE = "credentials.ini"


class Seeker:
    def __init__(self, credentials):
        self.credentials: dict = credentials
        self.session: aiohttp.ClientSession = None
        self.patty: TellyPatty = None
        self.alpha: AlphaSeek = None

    async def start_session(self):
        self.session = aiohttp.ClientSession()
        self.alpha = AlphaSeek(
            **self.credentials["yahoofinance"], use_session=self.session
        )
        self.patty = TellyPatty(
            **self.credentials["telegram"],
            command_set=self.alpha.known_commands,
            use_session=self.session,
        )
        await self.patty.say("Hey, I'm all hyped up!")

    async def stop_session(self):
        await self.patty.say("Bye!")
        self.patty = None
        self.alpha = None
        await self.session.close()
        self.session = None

    async def update_patty(self):
        if not (self.patty and self.alpha):
            return

        print(".", end="", flush=True)

        data = await self.patty.get_updates(polling_window=1)
        commands, errors = self.patty.digest_updates(data)
        if errors:
            reply = "I don't understand {}".format(", ".join(errors))
            await self.patty.say(reply)

        replies = self.alpha.run_commands(commands)
        if replies:
            await self.patty.say("\n".join(replies))

    async def start(self):
        error_count = 0
        await self.start_session()

        schedule.every(10).seconds.do(self.alpha.update_charts)
        while self.alpha.keep_alive:
            try:
                await asyncio.gather(schedule.run_pending(), self.update_patty())
                time.sleep(0.61803398875)

                error_count = 0

            except Exception as err:
                print(err, type(err), err.__dict__)
                print("Exception occured:", str(err))
                error_count += 1
                if error_count > 2:
                    print("Too many errors occured, stopping...")
                    self.alpha.keep_alive = False

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

    print("--- starting event loop ---")
    asyncio.run(seeker.start())
    print("---  event loop closed  ---")
