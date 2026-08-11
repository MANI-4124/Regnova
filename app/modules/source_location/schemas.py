from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


class SourceLocationCreate(BaseModel):

    source_version_id: UUID

    section: str | None = None
    article: str | None = None
    schedule: str | None = None
    page: str | None = None
    table_ref: str | None = None
    paragraph: str | None = None

    normalized_text: str | None = None

    ocr_confidence: float | None = None
    is_manually_corrected: bool | None = None
    original_ocr_text: str | None = None

    @model_validator(mode="after")
    def _at_least_one_coordinate(self):
        coordinates = (
            self.section,
            self.article,
            self.schedule,
            self.page,
            self.table_ref,
            self.paragraph,
        )

        if not any(coordinates):
            raise ValueError(
                "At least one coordinate field (section, article, "
                "schedule, page, table_ref, paragraph) is required."
            )

        return self


class SourceLocationUpdate(BaseModel):

    section: str | None = None
    article: str | None = None
    schedule: str | None = None
    page: str | None = None
    table_ref: str | None = None
    paragraph: str | None = None

    normalized_text: str | None = None

    ocr_confidence: float | None = None
    is_manually_corrected: bool | None = None
    original_ocr_text: str | None = None
    corrected_by_user_id: UUID | None = None


class SourceLocationResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    source_version_id: UUID

    section: str | None
    article: str | None
    schedule: str | None
    page: str | None
    table_ref: str | None
    paragraph: str | None

    normalized_text: str | None

    ocr_confidence: float | None
    is_manually_corrected: bool
    original_ocr_text: str | None
    corrected_by_user_id: UUID | None
