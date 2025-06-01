import asyncio
import json

from dotenv import load_dotenv
from wallabag_client import WallabagClient, GetSingleArticleRequest, Article


async def main():
    load_dotenv()

    client = WallabagClient()

    await client.authenticate()

    request = GetSingleArticleRequest(id=59)

    await client.get_single_article(request)


if __name__ == "__main__":
    asyncio.run(main())
