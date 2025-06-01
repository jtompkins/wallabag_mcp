from json import JSONDecodeError
from typing import Optional, List, Literal, Any, Dict
import httpx
import os
from datetime import datetime
from pydantic import BaseModel, Field


class WallabagError(Exception):
    """Base exception for Wallabag client errors."""

    pass


class WallabagConfigError(WallabagError):
    """Custom exception for configuration errors."""

    pass


class WallabagAuthError(WallabagError):
    """Custom exception for authentication failures."""

    pass


class WallabagApiError(WallabagError):
    """Custom exception for API interaction failures."""

    pass


class GetSingleArticleRequest(BaseModel):
    id: int = Field(description="The ID of the article to fetch")


class SearchArticlesRequest(BaseModel):
    search_term: str = Field(description="The text to search for")
    count: Optional[int] = Field(default=None, description="The number of results to return")


class GetArticlesRequest(BaseModel):
    is_archived: bool = Field(default=False, description="Get archived entries")
    since: Optional[datetime] = Field(default=None, description="Get entries since this date")
    domain: Optional[str] = Field(default=None, description="Filter by domain")
    count: Optional[int] = Field(default=None, description="Limit the number of entries returned")
    sort_order: Literal["asc", "desc"] = Field(
        default="desc",
        description="The order to sort the returned articles. Valid values are 'asc' and 'desc'.",
    )
    include_content: bool = Field(default=False, description="Return the article content. Metadata is always returned.")


class Article(BaseModel):
    id: int
    title: str
    url: str
    content: Optional[str]
    created_at: datetime
    updated_at: datetime
    reading_time: Optional[int] = None
    domain_name: Optional[str] = None
    preview_picture: Optional[str] = None
    http_status: Optional[str] = None
    is_archived: bool = False
    is_starred: bool = False

    class Config:
        populate_by_name = True
        validate_assignment = True


class WallabagClient:
    def __init__(self, base_url: Optional[str] = None, client: Optional[httpx.AsyncClient] = None):
        self.base_url = base_url or os.getenv("WALLABAG_BASE_URL")

        if not self.base_url:
            raise WallabagConfigError(
                "Wallabag base URL is not set. Provide it or set WALLABAG_BASE_URL environment variable."
            )

        self.access_token = None
        self._client = client

    async def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        """Helper method for making HTTP requests."""
        client = self._client or httpx.AsyncClient()

        try:
            response = await client.request(method, url, params=params, data=data, headers=headers)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            raise WallabagApiError(f"API request failed: {e.response.status_code} - {e.response.text}") from e
        except httpx.RequestError as e:
            raise WallabagApiError(f"Request failed: {e}") from e
        finally:
            if not self._client:
                await client.aclose()

    async def authenticate(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> bool:
        url = f"{self.base_url}/oauth/v2/token"

        data: dict[str, str | None] = {
            "grant_type": "password",
            "client_id": client_id or os.getenv("WALLABAG_CLIENT_ID"),
            "client_secret": client_secret or os.getenv("WALLABAG_CLIENT_SECRET"),
            "username": username or os.getenv("WALLABAG_USERNAME"),
            "password": password or os.getenv("WALLABAG_PASSWORD"),
        }

        if (
            data["client_id"] is None
            or data["client_secret"] is None
            or data["username"] is None
            or data["password"] is None
        ):
            raise WallabagConfigError(
                "Missing required authentication parameters. Please provide client_id, client_secret, username, and password or set corresponding WALLABAG_ environment variables."
            )

        try:
            response = await self._request("GET", url, params=data)
            token_data = response.json()
        except JSONDecodeError as e:
            raise WallabagAuthError(f"Failed to parse authentication response: {e}") from e
        except WallabagApiError as e:  # Catching the error from _request
            raise WallabagAuthError(f"Authentication failed: {e}") from e

        self.access_token = token_data.get("access_token")

        if not self.access_token:
            raise WallabagAuthError("Authentication successful, but no access token received.")

        return True

    async def search_articles(self, req: SearchArticlesRequest) -> List[Article]:
        if not self.access_token:
            raise WallabagAuthError("Access token is not set. Please authenticate first.")

        url = f"{self.base_url}/api/search"

        params = {
            "term": str(req.search_term),
            "perPage": str(req.count) if req.count else "100",
        }

        headers = {"Authorization": f"Bearer {self.access_token}"}

        try:
            response = await self._request("GET", url, headers=headers, params=params)
            response_data = response.json()
        except JSONDecodeError as e:
            raise WallabagApiError(f"Failed to parse articles response: {e}") from e
        except WallabagApiError:
            raise

        articles_data = response_data.get("_embedded", {}).get("items", [])

        return [Article(**article) for article in articles_data]

    async def get_single_article(self, req: GetSingleArticleRequest) -> Article:
        if not self.access_token:
            raise WallabagAuthError("Access token is not set. Please authenticate first.")

        url = f"{self.base_url}/api/entries/{req.id}"

        headers = {"Authorization": f"Bearer {self.access_token}"}

        try:
            response = await self._request("GET", url, headers=headers)
            response_data = response.json()
        except JSONDecodeError as e:
            raise WallabagApiError(f"Failed to parse article response: {e}") from e
        except WallabagApiError:
            raise

        return Article(**response_data)

    async def get_articles(self, req: GetArticlesRequest) -> List[Article]:
        if not self.access_token:
            raise WallabagAuthError("Access token is not set. Please authenticate first.")

        url = f"{self.base_url}/api/entries"

        params = {
            "archive": "1" if req.is_archived else "0",
            "perPage": str(req.count) if req.count else "100",
            "since": str(req.since.timestamp()) if req.since else "0",
            "order": req.sort_order,
            "detail": "full" if req.include_content else "metadata",
        }

        if req.domain:
            params["domain_name"] = req.domain

        headers = {"Authorization": f"Bearer {self.access_token}"}

        try:
            response = await self._request("GET", url, headers=headers, params=params)
            response_data = response.json()
        except JSONDecodeError as e:
            raise WallabagApiError(f"Failed to parse articles response: {e}") from e
        except WallabagApiError:
            raise

        articles_data = response_data.get("_embedded", {}).get("items", [])

        return [Article(**article) for article in articles_data]
