import pytest
import pytest_asyncio
from pytest import MonkeyPatch
import httpx
from datetime import datetime, timezone

from respx import MockRouter

from src.wallabag_client import (
    WallabagClient,
    GetArticlesRequest,
    Article,
    WallabagConfigError,
    WallabagAuthError,
)

MOCK_BASE_URL = "http://test-wallabag.com"
MOCK_API_URL = f"{MOCK_BASE_URL}/api"
MOCK_OAUTH_URL = f"{MOCK_BASE_URL}/oauth/v2/token"


@pytest.fixture
def mock_env_vars(monkeypatch: MonkeyPatch):
    monkeypatch.setenv("WALLABAG_CLIENT_ID", "test_client_id_env")
    monkeypatch.setenv("WALLABAG_CLIENT_SECRET", "test_client_secret_env")
    monkeypatch.setenv("WALLABAG_USERNAME", "test_user_env")
    monkeypatch.setenv("WALLABAG_PASSWORD", "test_pass_env")
    monkeypatch.setenv("WALLABAG_BASE_URL", MOCK_BASE_URL)


@pytest.fixture
def client_with_url():
    return WallabagClient(base_url=MOCK_BASE_URL)


@pytest_asyncio.fixture
async def authenticated_client(respx_mock: MockRouter, client_with_url: WallabagClient):
    respx_mock.get(MOCK_OAUTH_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "test_access_token", "expires_in": 3600, "token_type": "Bearer"},
        )
    )
    await client_with_url.authenticate("id", "secret", "user", "pass")
    return client_with_url


@pytest.mark.asyncio
class TestWallabagClientInitialization:
    def test_init_with_base_url(self):
        client = WallabagClient(base_url="http://example.com")
        assert client.base_url == "http://example.com"
        assert client._client is None  # Verifies default internal state

    def test_init_with_env_variable(self, monkeypatch: MonkeyPatch):
        monkeypatch.setenv("WALLABAG_BASE_URL", "http://env-example.com")
        client = WallabagClient()
        assert client.base_url == "http://env-example.com"

    def test_init_no_base_url_raises_config_error(self, monkeypatch: MonkeyPatch):
        monkeypatch.delenv("WALLABAG_BASE_URL", raising=False)
        with pytest.raises(WallabagConfigError, match="Wallabag base URL is not set"):
            WallabagClient()

    def test_init_with_external_httpx_client(self):
        mock_httpx_client = httpx.AsyncClient()
        client = WallabagClient(base_url="http://example.com", client=mock_httpx_client)
        assert client._client == mock_httpx_client  # Verifies passed client is stored


@pytest.mark.asyncio
class TestWallabagClientAuthentication:
    async def test_authenticate_success_with_args(self, respx_mock: MockRouter, client_with_url: WallabagClient):
        respx_mock.get(url__regex=rf"{MOCK_OAUTH_URL}\?.*").mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "test_token_args", "expires_in": 3600, "token_type": "Bearer"},
            )
        )

        result = await client_with_url.authenticate(
            client_id="cid", client_secret="csecret", username="user", password="pw"
        )
        assert result is True
        assert client_with_url.access_token == "test_token_args"

        called_request = respx_mock.calls.last.request
        assert called_request is not None
        assert (
            called_request.url.query.decode()
            == "grant_type=password&client_id=cid&client_secret=csecret&username=user&password=pw"
        )

    async def test_authenticate_success_with_env_vars(self, respx_mock: MockRouter, mock_env_vars: None):  # type: ignore
        respx_mock.get(url__regex=rf"{MOCK_OAUTH_URL}\?.*").mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "test_token_env", "expires_in": 3600, "token_type": "Bearer"},
            )
        )
        # Instantiate client AFTER env vars are set by mock_env_vars
        # This client will use WALLABAG_BASE_URL from the mocked environment.
        client = WallabagClient()
        result = await client.authenticate()  # Uses env vars for credentials
        assert result is True
        assert client.access_token == "test_token_env"

        called_request = respx_mock.calls.last.request
        assert called_request is not None
        query_params_str = called_request.url.query.decode()
        assert "grant_type=password" in query_params_str
        assert "client_id=test_client_id_env" in query_params_str
        assert "client_secret=test_client_secret_env" in query_params_str
        assert "username=test_user_env" in query_params_str
        assert "password=test_pass_env" in query_params_str

    async def test_authenticate_missing_args_raises_config_error(
        self, client_with_url: WallabagClient, monkeypatch: MonkeyPatch
    ):
        # Ensure no relevant env vars are set that could satisfy the requirements
        monkeypatch.delenv("WALLABAG_CLIENT_ID", raising=False)
        monkeypatch.delenv("WALLABAG_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("WALLABAG_USERNAME", raising=False)
        monkeypatch.delenv("WALLABAG_PASSWORD", raising=False)

        with pytest.raises(WallabagConfigError, match="Missing required authentication parameters"):
            # Missing other args, and env vars are cleared
            await client_with_url.authenticate(client_id="cid")

        with pytest.raises(WallabagConfigError, match="Missing required authentication parameters"):
            # All args missing, env vars also missing
            await client_with_url.authenticate()

    async def test_authenticate_api_failure_raises_auth_error(
        self, respx_mock: MockRouter, client_with_url: WallabagClient
    ):
        respx_mock.get(url__regex=rf"{MOCK_OAUTH_URL}\?.*").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises(WallabagAuthError, match="Authentication failed: API request failed: 500"):
            await client_with_url.authenticate("id", "secret", "user", "pass")

    async def test_authenticate_json_decode_error_raises_auth_error(
        self, respx_mock: MockRouter, client_with_url: WallabagClient
    ):
        respx_mock.get(url__regex=rf"{MOCK_OAUTH_URL}\?.*").mock(return_value=httpx.Response(200, text="not json"))
        with pytest.raises(WallabagAuthError, match="Failed to parse authentication response"):
            await client_with_url.authenticate("id", "secret", "user", "pass")

    async def test_authenticate_no_access_token_raises_auth_error(
        self, respx_mock: MockRouter, client_with_url: WallabagClient
    ):
        respx_mock.get(url__regex=rf"{MOCK_OAUTH_URL}\?.*").mock(
            return_value=httpx.Response(200, json={"message": "success but no token"})
        )
        with pytest.raises(WallabagAuthError, match="Authentication successful, but no access token received"):
            await client_with_url.authenticate("id", "secret", "user", "pass")


@pytest.mark.asyncio
class TestWallabagClientGetArticles:
    MOCK_ARTICLES_PAYLOAD = {  # type: ignore
        "_embedded": {
            "items": [
                {
                    "id": 1,
                    "title": "Article 1",
                    "url": "http://example.com/1",
                    "content": "Content 1",
                    "created_at": "2023-01-01T10:00:00Z",
                    "updated_at": "2023-01-01T11:00:00Z",
                    "is_archived": False,
                    "is_starred": True,
                    "reading_time": 5,
                    "domain_name": "example.com",
                    "preview_picture": "http://img.com/1.jpg",
                    "http_status": "200",
                },
                {
                    "id": 2,
                    "title": "Article 2",
                    "url": "http://example.com/2",
                    "content": "Content 2",
                    "created_at": "2023-01-02T12:00:00Z",
                    "updated_at": "2023-01-02T13:00:00Z",
                    "reading_time": 10,
                    "domain_name": "example.org",
                    "preview_picture": None,
                    "http_status": None,
                    "is_archived": True,
                    "is_starred": False,
                },
            ]
        }
    }

    async def test_get_articles_success(self, respx_mock: MockRouter, authenticated_client: WallabagClient):
        req = ArticlesRequest()

        respx_mock.get(url__regex=rf"{MOCK_API_URL}/entries\?.*").mock(
            return_value=httpx.Response(200, json=self.MOCK_ARTICLES_PAYLOAD)  # type: ignore
        )

        articles = await authenticated_client.get_articles(req)

        assert len(articles) == 2
        assert isinstance(articles[0], Article)
        assert articles[0].id == 1
        assert articles[0].title == "Article 1"
        assert articles[0].is_starred is True
        assert articles[0].is_archived is False
        assert articles[0].domain_name == "example.com"
        assert articles[0].created_at == datetime(2023, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

        assert isinstance(articles[1], Article)
        assert articles[1].id == 2
        assert articles[1].title == "Article 2"
        assert articles[1].is_archived is True
        assert articles[1].domain_name == "example.org"
        assert articles[1].created_at == datetime(2023, 1, 2, 12, 0, 0, tzinfo=timezone.utc)

        called_request = respx_mock.calls.last.request
        assert called_request is not None
        assert called_request.headers["Authorization"] == "Bearer test_access_token"
        query_params = called_request.url.query.decode()
        assert "archive=0" in query_params
        assert "order=desc" in query_params
        assert "perPage=100" in query_params
        assert "since=0" in query_params

    async def test_get_articles_with_custom_request_params(
        self, respx_mock: MockRouter, authenticated_client: WallabagClient
    ):
        since_dt = datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        req = ArticlesRequest(is_archived=True, since=since_dt, domain="test.dev", count=5, sort_order="asc")

        respx_mock.get(url__regex=rf"{MOCK_API_URL}/entries\?.*").mock(
            return_value=httpx.Response(200, json={"_embedded": {"items": []}})  # Empty for this test
        )

        await authenticated_client.get_articles(req)

        called_request = respx_mock.calls.last.request
        assert called_request is not None
        query_params_str = called_request.url.query.decode()

        assert "archive=1" in query_params_str
        assert f"since={int(since_dt.timestamp())}" in query_params_str
        assert "domain_name=test.dev" in query_params_str
        assert "perPage=5" in query_params_str
        assert "order=asc" in query_params_str

    async def test_get_articles_req_count_is_none_uses_default_perpage(
        self, respx_mock: MockRouter, authenticated_client: WallabagClient
    ):
        # ArticlesRequest.count defaults to None
        req = ArticlesRequest(count=None)  # Explicitly None, though default
        respx_mock.get(url__regex=rf"{MOCK_API_URL}/entries\?.*").mock(
            return_value=httpx.Response(200, json={"_embedded": {"items": []}})
        )
        await authenticated_client.get_articles(req)
        called_request = respx_mock.calls.last.request
        assert called_request is not None
        # Your client code defaults to "100" if req.count is None or 0
