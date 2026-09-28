from __future__ import annotations

from enum import Enum
from hashlib import sha256

from pydantic import BaseModel, Field


class PiiSource(str, Enum):
    REGEX = "regex"
    LLM = "llm"
    PRESIDIO = "presidio"
    MERGED = "merged"


class PiiEntityType(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    PERSON = "PERSON"
    ADDRESS = "ADDRESS"
    IBAN = "IBAN"
    CNP = "CNP"
    CREDIT_CARD = "CREDIT_CARD"


class PiiSpan(BaseModel):
    entity_type: str
    start: int
    end: int
    value: str = Field(repr=False)
    confidence: float = 1.0
    source: PiiSource = PiiSource.REGEX

    def value_hash(self) -> str:
        return sha256(self.value.encode("utf-8")).hexdigest()[:16]

    def safe_dict(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
            "source": self.source.value,
            "value_hash": self.value_hash(),
        }
