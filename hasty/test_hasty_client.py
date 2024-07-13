import pytest
from unittest.mock import AsyncMock, patch
from aiohttp import ClientSession
from .hasty_client import HastyClient


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer yourtoken"}


@pytest.fixture
def client(auth_headers):
    with patch.object(ClientSession, "__init__", return_value=None):
        client = HastyClient(auth_headers)
        client.session.get = AsyncMock()
        client.session.post = AsyncMock()
        client.session.put = AsyncMock()
        client.session.delete = AsyncMock()
        return client


@pytest.mark.asyncio
async def test_get(client):
    client.session.get.return_value.__aenter__.return_value.json = AsyncMock(
        return_value={}
    )

    response = await client.get("http://example.com/api")

    client.session.get.assert_called_once_with(
        "http://example.com/api", params={}, json={}, raise_for_status=True
    )


@pytest.mark.asyncio
async def test_post(client):
    client.session.post.return_value.__aenter__.return_value.json = AsyncMock(
        return_value={}
    )

    response = await client.post("http://example.com/api", params=dict(one=1))

    client.session.post.assert_called_once_with(
        "http://example.com/api", params={}, json={}, raise_for_status=True
    )


def test_invalid_verb(client):
    with pytest.raises(AttributeError) as exc_info:
        client.invalidverb
    assert "Attribute 'invalidverb' does not exist" in str(exc_info.value)


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
    client.session.get.return_value.__aenter__.side_effect = RuntimeError("Failed")

    with pytest.raises(RuntimeError) as exc_info:
        await client.get("http://example.com/error")

    assert "Error" in str(exc_info.value)
