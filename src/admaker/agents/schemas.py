"""Creative output only: models cannot return account, billing or storage commands."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

ShortText = Annotated[str, Field(max_length=500)]
Caption = Annotated[str, Field(max_length=2200)]


class IntakeVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    product_visible: StrictBool
    product_guess: ShortText
    reason: ShortText


class StyleCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: Annotated[str, Field(min_length=1, max_length=100)]
    name: Annotated[str, Field(max_length=100)]
    one_liner: ShortText
    caption_preview: Caption


class CreativePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    video_prompt: Annotated[str, Field(min_length=1, max_length=4000)]
    ad_copy: ShortText
    captions: dict[Literal["tiktok", "reels", "stories", "feed", "feed_square"], Caption]
    music_mood: Annotated[str, Field(max_length=100)]
    candidates: Annotated[list[StyleCandidate], Field(max_length=3)]


class ContentVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    passed: StrictBool
    score: Annotated[float, Field(ge=0, le=1)]
    reasons: Annotated[list[ShortText], Field(max_length=10)]


RUNNER_SCHEMAS = {"intake": IntakeVerdict, "style_planner": CreativePlan, "qa_content": ContentVerdict}
