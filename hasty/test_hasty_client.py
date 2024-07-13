import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock, AsyncMock, ANY
from types import SimpleNamespace

from aiohttp import ClientSession, ClientResponse
from .hasty_client import HastyClient


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer yourtoken"}


@pytest_asyncio.fixture
async def client(auth_headers):
    """Setup mock client with async context manager support"""

    with patch.object(ClientSession, "__init__", return_value=None):
        client = HastyClient(auth_headers)

        for method in client.VERBS:
            response_mock = MagicMock(spec=ClientResponse)
            response_mock.json = AsyncMock(return_value=dict(message="ok"))

            session_verb_mock = MagicMock(spec=getattr(ClientSession, method))
            session_verb_mock.return_value.__aenter__ = AsyncMock(
                return_value=response_mock
            )
            session_verb_mock.return_value.__aexit__ = AsyncMock(return_value=None)
            setattr(client.session, method, session_verb_mock)

        return client


def test_invalid_verb(client):
    with pytest.raises(AttributeError) as exc_info:
        client.invalidverb
    assert "Attribute 'invalidverb' does not exist" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get(client):
    response = await client.get("http://example.com/api")

    client.session.get.assert_called_once()
    assert response.message == "ok"


@pytest.mark.asyncio
async def test_post(client):
    response = await client.post("http://example.com/api", data=dict(one=1))

    client.session.post.assert_called_once()
    assert response.message == "ok"


@pytest.mark.asyncio
async def test_response_conversion_to_namespace(client):
    sample_data = {"key": "value"}
    client.session.get.return_value.__aenter__.return_value.json = AsyncMock(
        return_value=sample_data
    )

    response = await client.get("http://example.com/api")

    assert isinstance(response, SimpleNamespace)
    assert response.key == "value"


@pytest.mark.asyncio
async def test_error_handling(client):
    client.session.get.return_value.__aenter__.side_effect = RuntimeError(
        "Expected Failure"
    )

    with pytest.raises(RuntimeError) as exc_info:
        await client.get("http://example.com/error")

    assert "Expected Failure" in str(exc_info.value)
