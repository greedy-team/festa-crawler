"""추출 결과 및 아티스트 마스터의 pydantic 모델."""
from typing import Literal

from pydantic import BaseModel, Field

ExternalVisitorPolicy = Literal["ALLOWED", "CONDITIONAL", "DENIED"]
VerificationMethod = Literal["NONE", "STUDENT_ID", "PRE_BOOKING", "INVITATION", "OTHER"]
TicketType = Literal["FREE", "PAID"]
Genre = Literal["HIPHOP", "BALLAD_RNB", "DANCE", "BAND"]


class LineupItem(BaseModel):
    artist_raw: str
    day: int | None = None
    is_secret: bool = False


class ExtractionResult(BaseModel):
    found: bool
    university_name: str
    year: int
    festival_name: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    venue_name: str | None = None
    description: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    external_visitor_policy: ExternalVisitorPolicy | None = None
    verification_method: VerificationMethod | None = None
    ticket_type: TicketType | None = None
    ticket_open_at: str | None = None
    admission_raw: str | None = None
    instagram_handle: str | None = None
    lineup: list[LineupItem] = Field(default_factory=list)


class ArtistMaster(BaseModel):
    name: str
    other_names: list[str] = Field(default_factory=list)
    genre: Genre | None = None
    needs_review: bool = False


class EnrichResult(BaseModel):
    mapping: dict[str, str]
    artists: list[ArtistMaster]


class Candidate(BaseModel):
    url: str
    title: str | None = None


class DiscoverResult(BaseModel):
    candidates: list[Candidate] = Field(default_factory=list)
