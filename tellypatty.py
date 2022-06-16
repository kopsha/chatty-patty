import configparser
import os
import pickle
import aiohttp
import asyncio
from collections import deque


class TellyPatty:
    CREDENTIALS_CACHE = "credentials.ini"
    INTERNAL_CACHE = "internals.dat"

    def __init__(self):
        self.session = None
        self.keep_alive = True
        self.cmd_queue = deque()
        self.watchlist = set()

        self.read_credentials()
        self.load_internals()

    def read_credentials(self):
        """questionable coupling with config"""

        credentials = configparser.ConfigParser()
        if os.path.isfile(self.CREDENTIALS_CACHE):
            credentials.read(self.CREDENTIALS_CACHE)
        else:
            empty = dict(token="", chat_id="")
            with open(self.CREDENTIALS_CACHE, "wt") as storage:
                credentials["telegram"] = empty
                credentials.write(storage)
            raise RuntimeError(
                f"Created empty {self.CREDENTIALS_CACHE}, please fill in and run again."
            )

        self.token = credentials["telegram"]["token"]
        self.chat_id = int(credentials["telegram"]["chat_id"])

    def load_internals(self):
        """for now, just last_update_id"""
        if os.path.isfile(self.INTERNAL_CACHE):
            with open(self.INTERNAL_CACHE, "rb") as datafile:
                internals = pickle.load(datafile)
        else:
            internals = dict()

        self.last_update_id = internals.get("last_update_id", 0)

    def save_internals(self):
        """for now, just last_update_id"""
        internals = dict(last_update_id=self.last_update_id)
        with open(self.INTERNAL_CACHE, "wb") as datafile:
            pickle.dump(internals, datafile)

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_type:
            print("Something bad happened", exc_type, exc_value)

        self.save_internals()
        await self.session.close()

    async def get_updates(self):
        url = (
            "https://api.telegram.org/bot{token}/getUpdates?"
            "timeout={timeout}&offset={offset}"
        ).format(
            token=self.token,
            timeout=15,
            offset=self.last_update_id + 1,
        )
        assert self.session, "Cannot make any request without a session"
        async with self.session.get(url) as response:
            response_data = await response.json()
            assert response_data[
                "ok"
            ], f"Call to getUpdates failed with {response_data['error_code']}, {response_data['description']}"

        return response_data["result"]

    async def say(self, message):
        url = (
            "https://api.telegram.org/bot{token}/sendMessage?"
            "chat_id={chat_id}&text={message}"
            "&parse_mode=Markdown&disable_web_page_preview=true"
        ).format(token=self.token, chat_id=self.chat_id, message=message)

        assert self.session, "Cannot make any request without a session"
        async with self.session.get(url) as response:
            response_data = await response.json()
            assert response_data[
                "ok"
            ], "send_message failed with {code}: {description}".format(
                code=response_data["error_code"],
                description=response_data["description"],
            )
        return response_data

    def digest_updates(self, data):
        replies = list()
        for update in data:
            self.last_update_id = update["update_id"]

            sender = update["message"]["from"]["username"]
            message = update["message"]["text"]
            chat_id = update["message"]["chat"]["id"]

            if chat_id == self.chat_id:
                reply = self.parse_command(message)
                if reply:
                    replies.append(asyncio.create_task(self.say(reply)))

        return replies

    def parse_command(self, message):
        reply_message = None
        cmd, *params = message.split()

        if cmd == "/bye":
            self.keep_alive = False
        elif cmd == "/show":
            print("watchlist", self.watchlist)
            reply_message = ", ".join(sorted(self.watchlist)) or "Empty"
        elif cmd == "/tail":
            if params:
                print("following", params)
                self.watchlist.update(params)
            else:
                reply_message = "Nothing to follow."
        elif cmd == "/drop":
            if params:
                print("dropping", params)
                self.watchlist.difference_update(params)
            else:
                reply_message = "Nothing to drop."
        else:
            reply_message = f"I don't understand {cmd}"

        return reply_message
