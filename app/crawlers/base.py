from __future__ import annotations
from abc import ABC, abstractmethod

from app.models import Listing, SearchConfig


class BaseCrawler(ABC):
    @abstractmethod
    async def crawl(self, config: SearchConfig) -> list[Listing]:
        ...

    async def close(self):
        pass
