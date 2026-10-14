from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field, ValidationError

from config.settings import Settings, get_settings
from obs.logging_setup import get_logger
from prompts.loader import load_prompt

logger = get_logger(__name__)

UsageDict = dict[str, int]

# Sensible default when LLM_PROVIDER=groq and LLM_MODEL is still the Ollama default.
_GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_SUPPORTED_PROVIDERS = frozenset({"ollama", "groq"})



class DetectedEntity(BaseModel):
    entity_type: str
    start: int
    end: int
    value: str
    confidence: float = 0.7


class DetectResponse(BaseModel):
    entities: list[DetectedEntity] = Field(default_factory=list)


class VerifyVerdict(BaseModel):
    index: int
    keep: bool = True
    confidence: float = 0.7
    reason: str = ""


class VerifyResponse(BaseModel):
    verdicts: list[VerifyVerdict] = Field(default_factory=list)


class RewriteResponse(BaseModel):
    rewritten_text: str


def ollama_available(base_url: str, timeout: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(base_url.rstrip("/") + "/", timeout=timeout)
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _build_ollama(cfg: Settings) -> BaseChatModel:
    if not ollama_available(cfg.ollama_base_url):
        raise RuntimeError(
            f"Ollama not reachable at {cfg.ollama_base_url}. Start it with `ollama serve`."
        )
    return ChatOllama(
        model=cfg.llm_model,
        base_url=cfg.ollama_base_url,
        temperature=cfg.llm_temperature,
        client_kwargs={"timeout": cfg.llm_timeout_seconds},
    )


def _build_groq(cfg: Settings) -> BaseChatModel:
    if not cfg.groq_api_key.strip():
        raise RuntimeError("GROQ_API_KEY is empty. Set it in .env to use LLM_PROVIDER=groq.")
    try:
        from langchain_groq import ChatGroq
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "langchain-groq is not installed. Run: pip install langchain-groq"
        ) from exc
    model = cfg.llm_model.strip()
    if not model or model.lower() == "mistral":
        model = _GROQ_DEFAULT_MODEL
    return ChatGroq(
        model=model,
        api_key=cfg.groq_api_key,
        temperature=cfg.llm_temperature,
        timeout=cfg.llm_timeout_seconds,
        max_retries=cfg.llm_max_retries,
    )


def build_chat_model(settings: Settings | None = None) -> BaseChatModel:
    cfg = settings or get_settings()
    provider = cfg.llm_provider.lower().strip()
    if provider not in _SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported LLM_PROVIDER={provider!r}; supported: {sorted(_SUPPORTED_PROVIDERS)}"
        )
    if provider == "groq":
        return _build_groq(cfg)
    return _build_ollama(cfg)



def extract_token_usage(message: BaseMessage) -> UsageDict:
    """Best-effort token usage from LangChain message metadata (PII-free)."""
    usage: UsageDict = {}
    meta = getattr(message, "usage_metadata", None) or {}
    if isinstance(meta, dict):
        for src_key, dst_key in (
            ("input_tokens", "prompt_tokens"),
            ("output_tokens", "completion_tokens"),
            ("total_tokens", "total_tokens"),
        ):
            if src_key in meta and meta[src_key] is not None:
                usage[dst_key] = int(meta[src_key])
    resp = getattr(message, "response_metadata", None) or {}
    if isinstance(resp, dict):
        nested = resp.get("token_usage") or resp.get("usage") or {}
        if isinstance(nested, dict):
            for src_key, dst_key in (
                ("prompt_tokens", "prompt_tokens"),
                ("completion_tokens", "completion_tokens"),
                ("total_tokens", "total_tokens"),
                ("prompt_eval_count", "prompt_tokens"),
                ("eval_count", "completion_tokens"),
            ):
                if src_key in nested and nested[src_key] is not None and dst_key not in usage:
                    usage[dst_key] = int(nested[src_key])
        for src_key, dst_key in (
            ("prompt_eval_count", "prompt_tokens"),
            ("eval_count", "completion_tokens"),
        ):
            if src_key in resp and resp[src_key] is not None and dst_key not in usage:
                usage[dst_key] = int(resp[src_key])
    if usage and "total_tokens" not in usage:
        usage["total_tokens"] = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
    return usage


def _extract_json(raw: str) -> Any:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def invoke_json(model: BaseChatModel, prompt: str, retries: int) -> tuple[Any, UsageDict]:
    last_error: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            message = model.invoke([HumanMessage(content=prompt)])
            usage = extract_token_usage(message) if isinstance(message, BaseMessage) else {}
            content = message.content if isinstance(message.content, str) else str(message.content)
            return _extract_json(content), usage
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("llm_json_retry", attempt=attempt + 1, error=str(exc))
    raise RuntimeError(f"LLM JSON invoke failed after retries: {last_error}")


def llm_detect_soft(
    text: str,
    model: BaseChatModel | None = None,
) -> tuple[list[DetectedEntity], UsageDict]:
    cfg = get_settings()
    chat = model or build_chat_model(cfg)
    template = load_prompt("detect_v1")
    prompt = template.replace("{text}", text)
    raw, usage = invoke_json(chat, prompt, cfg.llm_max_retries)
    try:
        parsed = DetectResponse.model_validate(raw)
    except ValidationError as exc:
        logger.warning("detect_parse_failed", error=str(exc))
        return [], usage
    return parsed.entities, usage


def llm_verify(
    text: str,
    candidates: list[dict[str, Any]],
    model: BaseChatModel | None = None,
) -> tuple[list[VerifyVerdict], UsageDict]:
    cfg = get_settings()
    chat = model or build_chat_model(cfg)
    template = load_prompt("verify_v1")
    prompt = template.replace("{text}", text).replace(
        "{candidates}",
        json.dumps(candidates, ensure_ascii=False),
    )
    raw, usage = invoke_json(chat, prompt, cfg.llm_max_retries)
    try:
        parsed = VerifyResponse.model_validate(raw)
    except ValidationError as exc:
        logger.warning("verify_parse_failed", error=str(exc))
        return [
            VerifyVerdict(index=i, keep=True, confidence=float(c.get("confidence", 0.5)))
            for i, c in enumerate(candidates)
        ], usage
    return parsed.verdicts, usage


def llm_rewrite(text: str, model: BaseChatModel | None = None) -> tuple[str, UsageDict]:
    cfg = get_settings()
    chat = model or build_chat_model(cfg)
    template = load_prompt("rewrite_v1")
    prompt = template.replace("{text}", text)
    raw, usage = invoke_json(chat, prompt, cfg.llm_max_retries)
    try:
        parsed = RewriteResponse.model_validate(raw)
    except ValidationError as exc:
        logger.warning("rewrite_parse_failed", error=str(exc))
        return text, usage
    return parsed.rewritten_text or text, usage
