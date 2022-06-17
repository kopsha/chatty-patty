import asyncio
from functools import cached_property
from aiohttp import ClientSession
from datetime import datetime


class AlphaSeek:
    """Seeking Alpha wrapper from https://www.yahoofinanceapi.com/"""

    api_root = "https://alpha.financeapi.net"

    def __init__(self, api_key: str, use_session: ClientSession):
        self.auth_headers = {"x-api-key": api_key}
        self.auth_headers["accept"] = "application/json"
        self.auth_headers["origin"] = "https://www.yahoofinanceapi.com"
        self.session = use_session
        self.keep_alive = True
        self.watchlist = set()

    async def get_realtime_prices(self, symbols):
        """Latest prices for given symbols"""

        querystring = dict(symbols=",".join(symbols))
        url = "{root}/market/get-realtime-prices".format(root=self.api_root)

        assert self.session, "Cannot make any request without a session"

        async with self.session.get(
            url, headers=self.auth_headers, params=querystring
        ) as response:
            response_data = await response.json()
            assert (
                response.status == 200
            ), f"Call to get-realtime-prices failed with {response.reason}, {response_data['message']}"

        return response_data["data"]

    async def get_recent_chart(self, symbol):
        """Past year OHLC prices for the given symbol"""

        querystring = dict(symbol=symbol, period="5D")
        url = "{root}/symbol/get-chart".format(root=self.api_root)

        assert self.session, "Cannot make any request without a session"

        async with self.session.get(
            url, headers=self.auth_headers, params=querystring
        ) as response:
            response_data = await response.json()
            assert (
                response.status == 200
            ), f"Call to get-chart failed with {response.reason}, {response_data['message']}"

        return response_data

    @cached_property
    def known_commands(self):
        return {"/" + func[4:] for func in dir(self) if func.startswith("cmd_")}

    def run_commands(self, commands):
        replies = list()
        for cmd, params in commands:
            func = getattr(self, "cmd_" + cmd)
            reply = func(params)
            if reply:
                replies.append(reply)
        return replies

    def cmd_tail(self, params):
        clean_params = filter(None, (p.strip().upper() for p in params))
        self.watchlist.update(clean_params)
        print("following", self.watchlist)

    def cmd_drop(self, params):
        clean_params = filter(None, (p.strip().upper() for p in params))
        self.watchlist.difference_update(clean_params)

    def cmd_bye(self, params):
        self.keep_alive = False

    def cmd_show(self, params):
        return "Following {}".format(", ".join(self.watchlist))

    async def update_charts(self):
        now = datetime.now()
        print("\n *** update charts", now.isoformat(), flush=True)

        if self.watchlist:
            results = await asyncio.gather(*(self.get_recent_chart(s) for s in self.watchlist))
            self.watchlist = list()
            for data in results:
                print(data["id"])
                for k, v in data["attributes"].items():
                    print(k, v["close"])

