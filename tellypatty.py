import os
import pickle
import aiohttp
from collections import deque


class TellyPatty:
    PRIVATE_CACHE = "internals.dat"

    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = int(chat_id)

        self.session = None

        self.load_internals()

    def load_internals(self):
        """for now, just last_update_id"""
        if os.path.isfile(self.PRIVATE_CACHE):
            with open(self.PRIVATE_CACHE, "rb") as datafile:
                internals = pickle.load(datafile)
        else:
            internals = dict()

        self.last_update_id = internals.get("last_update_id", 0)

    def save_internals(self):
        """for now, just last_update_id"""
        internals = dict(last_update_id=self.last_update_id)
        with open(self.PRIVATE_CACHE, "wb") as datafile:
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
        commands = list()
        for update in data:
            self.last_update_id = update["update_id"]

            sender = update["message"]["from"]["username"]
            message = update["message"]["text"]
            chat_id = update["message"]["chat"]["id"]

            if chat_id == self.chat_id:
                commands.append(self.parse_command(message))

        return commands

    def parse_command(self, message):
        first, *params = message.split()

        if first in {"/bye", "/show", "/tail", "/drop"}:
            command = first[1:], params
        else:
            command = "error", (f"I don't understand {first}",)

        return command
