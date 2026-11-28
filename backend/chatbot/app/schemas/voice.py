from typing import Annotated

from pydantic import Field, StringConstraints

from app.schemas.chat import ArModel, Locale

TranscriptionKeyword = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80, pattern=r"^[^<>\r\n]+$"),
]


class ArTranscriptionContext(ArModel):
    language: Locale = "ko"
    keywords: list[TranscriptionKeyword] = Field(default_factory=list, max_length=24)
