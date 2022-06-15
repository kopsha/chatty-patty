import configparser
import os
import aiohttp
from typing import TypeVar, Type

T = TypeVar('T', bound='TellyPatty')


class TellyPatty:
    CREDENTIALS_CACHE = "credentials.ini"
    INTERNAL_CACHE = "internals.ini"

    def __init__(self):

        # questionable coupling with config

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

        self.session = None
        self.keep_alive = True

        internals = configparser.ConfigParser()
        if os.path.isfile(self.INTERNAL_CACHE):
            internals.read(self.INTERNAL_CACHE)
        else:
            internals["private"] = dict(last_update_id=0)

        self.last_update_id = int(internals["private"]["last_update_id"])

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_type:
            print("Something bad happened", exc_type, exc_value)

        await self.session.close()

        internals = configparser.ConfigParser()
        with open(self.INTERNAL_CACHE, "wt") as storage:
            internals["private"] = dict(last_update_id=self.last_update_id)
            internals.write(storage)


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
            assert response.status == 200, f"Call to getUpdates failed with {response.status}, {response.reason}."
            response_data = await response.json()
            assert response_data["ok"], f"Call to getUpdates failed with {response_data['error_code']}, {response_data['description']}"
            for update in response_data["result"]:
                self.last_update_id = update["update_id"]

                sender = update["message"]["from"]["username"]
                message = update["message"]["text"]
                chat_id = update["message"]["chat"]["id"]
                if chat_id == self.chat_id:
                    print(sender, "says", message, ".")
                    if message.lower() in ["/bye"]:
                        self.keep_alive = False

    def say(self, message):
        url = (
            "https://api.telegram.org/bot{token}/sendMessage?"
            "chat_id={chat_id}&text={message}"
            "&parse_mode=Markdown&disable_web_page_preview=true"
        ).format(token=self.token, chat_id=self.chat_id, message=message)

        print(url)
        # response = requests.get(url)
        # data = response.json()
        # if not data["ok"]:
        #     print(
        #         "Notification error {code}: {description}".format(
        #             code=data["error_code"],
        #             description=data["description"],
        #         )
        #     )

        # return data
