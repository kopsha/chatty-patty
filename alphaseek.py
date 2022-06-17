from aiohttp import ClientSession


class AlphaSeek:
    """Seeking Alpha wrapper from https://www.yahoofinanceapi.com/"""

    api_root = "https://alpha.financeapi.net"

    def __init__(self, api_key: str, use_session: ClientSession):
        self.auth_headers = {"x-api-key": api_key}
        self.auth_headers["accept"] = "application/json"
        self.auth_headers["origin"] = "https://www.yahoofinanceapi.com"
        self.session = use_session

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

    async def get_chart_year(self, symbol):
        """OHLC prices for the past year"""

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
