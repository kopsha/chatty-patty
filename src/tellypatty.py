import os
import pickle
from types import SimpleNamespace

from hasty import HastyClient


class TellyPatty:
    """Telepathic Bot"""

    PRIVATE_CACHE = "internals.dat"
    API_ROOT = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: str, chat_id: str | int, command_set: set):
        self.token = token
        self.chat_id = int(chat_id)
        self.command_set = command_set  # Maybe this is not the best place for it

        self.client: HastyClient = None
        self.last_update_id = None

    async def on_start(self):
        self.client = HastyClient(auth_headers={})
        self._load_internals()

    async def on_stop(self):
        self._save_internals()
        await self.client.session.close()
        self.client = None

    def _load_internals(self):
        if os.path.isfile(self.PRIVATE_CACHE):
            with open(self.PRIVATE_CACHE, "rb") as datafile:
                internals = pickle.load(datafile)
        else:
            internals = dict()

        self.last_update_id = internals.get("last_update_id", 0)

    def _save_internals(self):
        internals = dict(last_update_id=self.last_update_id)
        with open(self.PRIVATE_CACHE, "wb") as datafile:
            pickle.dump(internals, datafile)

    async def get_updates(self, timeout=15):
        api_url = self.API_ROOT.format(token=self.token, method="getUpdates")
        query = dict(
            timeout=timeout,
            offset=self.last_update_id + 1,
        )
        response = await self.client.get(api_url, params=query)
        assert hasattr(
            response, "ok"
        ), f"getUpdates failed with {response.error_code}, {response.description}"

        return response.result

    def digest_updates(self, data: list[SimpleNamespace]):
        commands = list()
        system_commands = list()
        errors = list()

        for update in data:
            self.last_update_id = update.update_id
            message = update.message.text
            chat_id = update.message.chat.id

            if chat_id == self.chat_id:
                first, *params = message.split()
                print(first, params)
                if (cmd := first.lower()) in self.command_set:
                    commands.append((cmd, params))
                elif first.startswith("/"):
                    system_commands.append(first.lower()[1:])
                else:
                    errors.append(first)

        return commands, system_commands, errors

    async def say(self, message):
        api_url = self.API_ROOT.format(token=self.token, method="sendMessage")
        query = dict(
            chat_id=self.chat_id,
            text=message,
            parse_mode="markdown",
            disable_web_page_preview="true",
        )
        response = await self.client.get(api_url, params=query)
        assert hasattr(
            response, "ok"
        ), f"getUpdates failed with {response.error_code}, {response.description}"

        return response
