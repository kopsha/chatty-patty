#!/usr/bin/env python3

import asyncio

from tellypatty import TellyPatty


async def main():
    error_count = 0
    async with TellyPatty() as patty:
        while patty.keep_alive:
            try:
                data = await patty.get_updates()

                replies = patty.digest_updates(data)

                if replies:
                    await asyncio.wait(replies)

                error_count = 0

            except Exception as err:
                print("ERROR:", err)
                error_count += 1
                if error_count > 2:
                    print("Too many errors occured, stopping...")
                    return


if __name__ == "__main__":

    print("--- starting event loop ---")
    asyncio.run(main())
    print("---  event loop closed  ---")
