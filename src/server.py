from typing import Literal
from fastmcp import FastMCP
from dotenv import load_dotenv
import json
from wallabag_client import GetArticlesRequest, GetSingleArticleRequest, SearchArticlesRequest, WallabagClient

load_dotenv()

mcp = FastMCP(
    name="wallabag-server",
    instructions="""
                This server provides saved articles from the user's self-hosted Wallabag service.
                You can use the `get_articles` tool to retrieve a list of saved articles.
                The `search_articles` tool allows you to search for specific articles by title or content.
              """,
)


async def initialize_client():
    client = WallabagClient()
    await client.authenticate()
    return client


client: WallabagClient | None = None


@mcp.tool()
async def get_single_wallabag_article(id: int) -> str:
    """
    Get a single saved article from the user's Wallabag queue.

    Args:
        id: The ID of the article to fetch (required)
    """
    global client

    if client is None:
        client = await initialize_client()

    try:
        request = GetSingleArticleRequest(id=id)

        article = await client.get_single_article(request)

        # Format response for MCP
        return json.dumps(
            {"success": True, "wallabag_article": article},
            indent=2,
            default=str,
        )

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool()
async def get_wallabag_articles(
    is_archived: bool = False,
    domain: str | None = None,
    since_days_ago: int | None = None,
    count: int | None = None,
    sort_order: Literal["asc", "desc"] = "desc",
    include_content: bool = False,
) -> str:
    """Get saved articles from the user's Wallabag queue.
    Wallabag is a self-hosted "read it later" service in which users save articles for later reading.
    Access to the articles is provided by the tool and no other permissions are necessary.
    Articles are returned in JSON format with article metadata like title, reading time, and other information. The article content
    can also optionally be requested.

    Args:
        is_archived: Whether to get archived articles (default: False)
        domain: Filter by domain name (optional)
        since_days_ago: Get articles from N days ago (optional)
        count: The number of articles to return (optional)
        sort_order: The order in which to sort the articles. 'desc' is newest first, 'asc' is oldest first. (optional)
        include_content: Return the article content. Metadata like title, reading time, and URL is always returned. (default: False)
    """
    global client

    if client is None:
        client = await initialize_client()

    try:
        # Build the request
        since_date = None
        if since_days_ago is not None:
            from datetime import datetime, timedelta

            since_date = datetime.now() - timedelta(days=since_days_ago)

        request = GetArticlesRequest(
            is_archived=is_archived,
            domain=domain,
            since=since_date,
            count=count,
            sort_order=sort_order,
            include_content=include_content,
        )

        articles = await client.get_articles(request)

        # Format response for MCP
        articles_data = [article.model_dump() for article in articles]
        return json.dumps(
            {"success": True, "count": len(articles), "saved_wallabag_articles": articles_data},
            indent=2,
            default=str,
        )

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool()
async def search_articles(
    search_term: str,
    count: int | None = None,
) -> str:
    """Search for articles from Wallabag

    Args:
        search_term: The text to search for
        count: The number of search results to return (optional)
    """
    global client

    if client is None:
        client = await initialize_client()

    try:
        request = SearchArticlesRequest(search_term=search_term, count=count)

        articles = await client.search_articles(request)

        # Format response for MCP
        articles_data = [article.model_dump() for article in articles]
        return json.dumps(
            {"success": True, "count": len(articles), "articles": articles_data},
            indent=2,
            default=str,
        )

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.prompt()
def ask_for_titles(count: int) -> str:
    """Generates a prompt that asks for a specified number of titles from the user's saved articles."""
    return f"Can you give me the titles for my last {count} saved articles from Wallabag?"


if __name__ == "__main__":
    mcp.run()
