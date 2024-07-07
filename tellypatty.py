import os
import pickle
from urllib.parse import quote_plus
from aiohttp import ClientSession


class TellyPatty:
    PRIVATE_CACHE = "internals.dat"

    def __init__(self, token, chat_id, command_set, use_session: ClientSession):
        self.token = token
        self.chat_id = int(chat_id)
        self.session = use_session
        self.command_set = command_set

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

    async def get_updates(self, polling_window=15):
        """Get bot update using long polling strategy"""
        url = (
            "https://api.telegram.org/bot{token}/getUpdates?"
            "timeout={timeout}&offset={offset}"
        ).format(
            token=self.token,
            timeout=polling_window,
            offset=self.last_update_id + 1,
        )
        assert self.session, "Cannot make any request without a session"
        async with self.session.get(url) as response:
            response_data = await response.json()
            assert response_data.get(
                "ok"
            ), f"Call to getUpdates failed with {response_data['error_code']}, {response_data['description']}"

        return response_data["result"]

    async def say(self, message):
        url = "https://api.telegram.org/bot{token}/sendMessage".format(token=self.token)
        query = dict(
            chat_id=self.chat_id,
            text=message,
            parse_mode="markdown",
            disable_web_page_preview="true",
        )
        async with self.session.get(
            url,
            params=query,
            raise_for_status=True,
        ) as response:
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
        errors = list()
        for update in data:
            self.last_update_id = update["update_id"]
            message = update["message"]["text"]
            chat_id = update["message"]["chat"]["id"]

            if chat_id == self.chat_id:
                first, *params = message.split()
                if (cmd := first.lower()) in self.command_set:
                    commands.append((cmd, params))
                else:
                    errors.append(first)

        return commands, errors
