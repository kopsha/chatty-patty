from hasty import HastyClient


class YahooFinanceClient:
    """Seeking Alpha wrapper from https://www.yahoofinanceapi.com/"""

    API_ROOT = "https://yfapi.net/{method}"

    def __init__(self, api_key: str):
        self.auth_headers = {"x-api-key": api_key}
        self.client: HastyClient = None

    async def on_start(self):
        self.client = HastyClient(auth_headers=self.auth_headers)

    async def on_stop(self):
        await self.client.session.close()
        self.client = None

    async def fetch_quote(self, symbols):
        """Latest prices for given symbols"""
        api_url = self.API_ROOT.format(method="v6/finance/quote")
        query = dict(symbols=",".join(symbols))
        response = await self.client.get(api_url, params=query)
        return response

    async def fetch_chart(self, symbol):
        """Past year OHLC prices for the given symbol"""
        api_url = self.API_ROOT.format(method=f"v8/finance/chart/{symbol}")
        query = dict(
            range="1mo",
            interval="1d",
            lang="en",
            region="US",
        )
        response = await self.client.get(api_url, params=query)
        return response
