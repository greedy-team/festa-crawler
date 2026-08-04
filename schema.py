"""추출 결과 및 아티스트 마스터의 pydantic 모델."""
from pydantic import BaseModel, Field


class LineupItem(BaseModel):
    artist_raw: str
    day_label: str | None = None
    date: str | None = None
    time: str | None = None
    is_secret: bool = False


class ExtractionResult(BaseModel):
    found: bool
    university_name: str
    year: int
    festival_name: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    venue_name: str | None = None
    outsider_admission: str | None = None
    ticket_info: str | None = None
    instagram_handle: str | None = None
    lineup: list[LineupItem] = Field(default_factory=list)


class ArtistMaster(BaseModel):
    name_canonical: str
    name_en: str | None = None
    real_name: str | None = None
    category: str | None = None
    aliases: list[str] = Field(default_factory=list)
    needs_review: bool = False


class EnrichResult(BaseModel):
    mapping: dict[str, str]
    artists: list[ArtistMaster]
