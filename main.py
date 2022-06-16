#!/usr/bin/env python3

import asyncio
import os
from configparser import ConfigParser

from tellypatty import TellyPatty


CREDENTIALS_FILE = "credentials.ini"


async def main(credentials):
    error_count = 0
    keep_alive = True
    async with TellyPatty(**credentials["telegram"]) as patty:
        while keep_alive:
            try:
                data = await patty.get_updates()

                commands = patty.digest_updates(data)

                if commands:
                    print(commands)

                for cmd, _ in commands:
                    if cmd == "bye":
                        keep_alive = False

                error_count = 0

            except Exception as err:
                print("Exception occured:", str(err))
                error_count += 1
                if error_count > 2:
                    print("Too many errors occured, stopping...")
                    keep_alive = False


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

    print("--- starting event loop ---")
    asyncio.run(main(credentials))
    print("---  event loop closed  ---")
