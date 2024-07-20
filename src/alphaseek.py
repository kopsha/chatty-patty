from functools import cached_property
from collections import defaultdict
from types import SimpleNamespace
from aiohttp import ClientSession


class AlphaSeek:
    """Seeking Alpha wrapper from https://www.yahoofinanceapi.com/"""

    api_root = "https://yfapi.net"

    def __init__(self, api_key: str, use_session: ClientSession):
        self.auth_headers = {"x-api-key": api_key}
        self.auth_headers["accept"] = "application/json"
        self.auth_headers["origin"] = "https://www.yahoofinanceapi.com"
        self.session = use_session
        self.keep_alive = True

        self.watchlist = set()
        self.quotes = dict()

    async def get_quote(self, symbols):
        """Latest prices for given symbols"""

        querystring = dict(symbols=",".join(symbols))
        url = "{root}/v6/finance/quote".format(root=self.api_root)

        assert self.session, "Cannot make any request without a session"

        async with self.session.get(
            url, headers=self.auth_headers, params=querystring
        ) as response:
            response_data = await response.json()
            assert (
                response.status == 200
            ), f"Call to {url} has failed, reason: {response_data['message']}"
            response_data = response_data["quoteResponse"]
            assert not response_data[
                "error"
            ], f"Call to {url} has failed, reason: {response_data['error']}"

        return response_data["result"]

    async def get_chart_year(self, symbol):
        """Past year OHLC prices for the given symbol"""

        querystring = dict(symbol=symbol, period="1Y")
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

    @staticmethod
    def pretty_q(quote):
        lines = [f"{key}: {value}" for key, value in vars(quote).items()]
        return lines

    async def watch(self):
        if not self.watchlist:
            return []

        quotes = await self.get_quote(self.watchlist)
        changes = list()
        for quote in quotes:
            symbol = quote["symbol"]
            current = SimpleNamespace(
                name=quote["displayName"],
                ask=quote["ask"],
                price=quote["regularMarketPrice"],
                bid=quote["bid"],
                rating=quote["averageAnalystRating"],
            )
            print(symbol, current)
            previous = self.quotes.get(symbol)
            if previous != current:
                self.quotes[symbol] = current
                changes.append(symbol)

        return changes

    @cached_property
    def known_commands(self):
        return {func[4:] for func in dir(self) if func.startswith("cmd_")}

    def run_commands(self, commands):
        for cmd, params in commands:
            func = getattr(self, "cmd_" + cmd)
            func(params)

    def cmd_tail(self, params):
        clean_params = filter(lambda x: x.strip().upper(), params)
        self.watchlist.update(clean_params)

    def cmd_drop(self, params):
        clean_params = filter(lambda x: x.strip().upper(), params)
        self.watchlist.difference_update(clean_params)

    def cmd_bye(self, params):
        self.keep_alive = False
