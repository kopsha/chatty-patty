from aiohttp import ClientSession
import requests


class AlphaSeek:
    api_root = "https://alpha.financeapi.net"

    def __init__(self, api_key: str, use_session: ClientSession):
        self.auth_headers = {"x-api-key": api_key}
        self.auth_headers["accept"] = "application/json"
        self.auth_headers["origin"] = "https://www.yahoofinanceapi.com"
        self.session = use_session

    async def get_realtime_prices(self, symbols):
        querystring = dict(symbols=",".join(symbols))
        url = "{root}/market/get-realtime-prices".format(root=self.api_root)

        assert self.session, "Cannot make any request without a session"

        async with self.session.get(url, headers=self.auth_headers, params=querystring) as response:
            response_data = await response.json()
            assert response.status == 200, f"Call to get-realtime-prices failed with {response.reason}, {response_data['message']}"

        return response_data["data"]
