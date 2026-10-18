from typing import Generic, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    total: int | None = None


class PaginationParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None
