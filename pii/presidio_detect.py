from __future__ import annotations

from functools import lru_cache

from pii.models import PiiSource, PiiSpan

_PRESIDIO_TYPE_MAP = {
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "PERSON": "PERSON",
    "LOCATION": "ADDRESS",
    "IBAN_CODE": "IBAN",
    "CREDIT_CARD": "CREDIT_CARD",
    "NRP": "PERSON",
}


@lru_cache(maxsize=1)
def _analyzer():
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
    except ImportError as exc:
        raise RuntimeError(
            "presidio-analyzer is not installed. pip install -e . "
            "and download: python -m spacy download en_core_web_sm"
        ) from exc

    provider = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }
    )
    return AnalyzerEngine(nlp_engine=provider.create_engine())


def detect_presidio(
    text: str,
    allowed_types: list[str] | None = None,
    *,
    language: str = "en",
) -> list[PiiSpan]:
    """Run Microsoft Presidio analyzer; map entities to pipeline types."""
    allowed = set(allowed_types) if allowed_types else None
    engine = _analyzer()
    results = engine.analyze(text=text, language=language)
    spans: list[PiiSpan] = []
    for hit in results:
        mapped = _PRESIDIO_TYPE_MAP.get(hit.entity_type)
        if mapped is None:
            continue
        if allowed is not None and mapped not in allowed:
            continue
        if mapped == "CNP":
            continue
        value = text[hit.start : hit.end]
        spans.append(
            PiiSpan(
                entity_type=mapped,
                start=hit.start,
                end=hit.end,
                value=value,
                confidence=float(hit.score),
                source=PiiSource.PRESIDIO,
            )
        )
    return spans
