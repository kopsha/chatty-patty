#!/usr/bin/env python3

import asyncio

from tellypatty import TellyPatty


async def main():

    async with TellyPatty() as patty:
        while patty.keep_alive:
            await patty.get_updates()
            await asyncio.sleep(0.1)


if __name__ == "__main__":

    print(". starting event loop .")
    asyncio.run(main())
