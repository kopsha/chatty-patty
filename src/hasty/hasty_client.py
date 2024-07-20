import ssl
from functools import cached_property, partial
from types import SimpleNamespace
from typing import Any

import certifi
from aiohttp import ClientSession, TCPConnector


class HastyClient:
    VERBS = {"get", "post", "put", "delete"}

    def __init__(self, auth_headers: dict):
        """Saves typical authentication header on session instance"""

        ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.session = ClientSession(
            connector=TCPConnector(ssl=ssl_context), headers=auth_headers
        )

    def __getattr__(self, attr):
        """Converts attribute access to REST call verb parameter"""

        if attr not in self.VERBS:
            raise AttributeError(f"Attribute '{attr}' does not exist.")

        return partial(self._rest_call, attr)

    @cached_property
    def _session_call_map(self):
        return dict(
            get=self.session.get,
            post=self.session.post,
            put=self.session.put,
            delete=self.session.delete,
        )

    async def _rest_call(
        self, verb: str, api_url: str, params: dict = {}, data: dict = {}
    ) -> SimpleNamespace | list[SimpleNamespace]:
        """Invokes selected session method"""
        session_verb = self._session_call_map[verb]

        async with session_verb(
            api_url, params=params, json=data or None, raise_for_status=True
        ) as response:
            response_data = await response.json()

        better_response = to_namespace(response_data)
        return better_response


def to_namespace(data: Any):
    """Recursively convert dictionary to SimpleNamespace."""

    if isinstance(data, dict):
        for key, value in data.items():
            data[key] = to_namespace(value)
        return SimpleNamespace(**data)
    elif isinstance(data, list):
        return [to_namespace(item) for item in data]

    return data


if __name__ == "__main__":
    raise RuntimeError("This is a pure module, it cannot be executed.")
