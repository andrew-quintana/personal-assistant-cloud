from __future__ import annotations
import hashlib
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


def _url_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


class Listing(BaseModel):
    id: str = ""
    source: str  # "craigslist" or "facebook"
    title: str
    price: Optional[int] = None
    location: Optional[str] = None
    url: str
    description: Optional[str] = None
    image_urls: list[str] = Field(default_factory=list)
    posted_at: Optional[datetime] = None
    crawled_at: datetime = Field(default_factory=datetime.utcnow)
    notified: bool = False

    def model_post_init(self, __context):
        if not self.id:
            self.id = _url_id(self.url)


class SearchConfig(BaseModel):
    id: Optional[int] = None
    platform: str  # "craigslist" or "facebook"
    query: Optional[str] = None
    city: Optional[str] = None
    url_pattern: Optional[str] = None
    room_id: str = ""  # Matrix room to send results to
    active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
