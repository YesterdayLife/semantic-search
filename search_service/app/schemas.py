"""Request and response models for the local search API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_QUERY_LENGTH = 500
MAX_TOP_K = 105


class FilterSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crop_id: str | None = Field(default=None, pattern=r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
    year_ce: int | None = Field(default=None, ge=1900, le=2100)
    region_code: str | None = Field(default=None, pattern=r"^[A-Z]{2,8}$")
    season: str | None = Field(default=None, pattern=r"^[a-z]{2,16}$")
    spatial_level: str | None = Field(default=None, pattern=r"^[a-z_]{3,16}$")
    source_id: str | None = Field(default=None, pattern=r"^[A-Z0-9][A-Z0-9_-]{0,31}$")


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    top_k: int = Field(default=5, ge=1, le=MAX_TOP_K)
    filters: FilterSet | None = None

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("query must not be empty")
        if len(text) > MAX_QUERY_LENGTH:
            raise ValueError("query must be at most 500 characters")
        return text

    def effective_filters(self) -> FilterSet:
        return self.filters or FilterSet()


class CompareRequest(BaseModel):
    """A comparison request. It does not change the /search contract."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    top_k: int = Field(default=5, ge=1, le=MAX_TOP_K)
    filters: FilterSet | None = None
    mode: Literal["dictionary", "semantic", "compare", "semantic-fallback"] = "compare"

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("query must not be empty")
        if len(text) > MAX_QUERY_LENGTH:
            raise ValueError("query must be at most 500 characters")
        return text


class NumericConstraint(BaseModel):
    """An explicit SQLite comparison. It belongs only to hybrid search."""

    model_config = ConfigDict(extra="forbid")

    metric: Literal["production", "yield_harvested", "yield_planted", "area_harvested", "area_planted"]
    operator: Literal["gt", "gte", "lt", "lte"]
    threshold: float = Field(gt=0)
    unit: Literal["t", "kg/rai", "rai"]


class HybridSearchRequest(BaseModel):
    """A hybrid search request. It does not change /search or /compare."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    top_k: int = Field(default=5, ge=1, le=MAX_TOP_K)
    filters: FilterSet | None = None
    numeric: NumericConstraint | None = None

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("query must not be empty")
        if len(text) > MAX_QUERY_LENGTH:
            raise ValueError("query must be at most 500 characters")
        return text

    def effective_filters(self) -> dict:
        return (self.filters or FilterSet()).model_dump()
