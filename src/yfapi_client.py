from hasty import HastyClient


class YahooFinanceClient(HastyClient):
    """Seeking Alpha wrapper from https://www.yahoofinanceapi.com/"""

    API_ROOT = "https://yfapi.net/{method}"

    def __init__(self, api_key: str):
        self.auth_headers = {"x-api-key": api_key}
        # self.auth_headers["accept"] = "application/json"
        # self.auth_headers["origin"] = "https://www.yahoofinanceapi.com"
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

    async def fetch_chart_for(self, symbol, period: str = "1Y"):
        """Past year OHLC prices for the given symbol"""
        api_url = self.API_ROOT.format(method="symbol/get-chart")
        query = dict(symbol=symbol, period=period)
        response = await self.client.get(api_url, params=query)
        return response
