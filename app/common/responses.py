from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """
    Standard API response wrapper.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True
    )

    success: bool = True
    message: str | None = None
    data: T | None = None