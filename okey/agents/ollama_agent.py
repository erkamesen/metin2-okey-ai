"""Ollama uzerinde calisan LLM karar vericisi.

Model tek bir hamle degil, kart adlariyla bir **plan** dondurur:

    {"plan": [{"action": "place", "card": "8r"}, {"action": "discard", "card": "1g"}],
     "reason": "..."}

Kart adlari indeks yerine kullanilir; indeksler her hamlede kaydigi icin bu hem
model icin hem de hata ayiklama icin cok daha saglam.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from ..cards import CardCodec
from ..engine import InvalidCard, OkeyGame
from ..rules import Rules
from .base import LLM, Advice, annotate_plan, resolve_card_steps
from .prompt import build_system_prompt, build_user_prompt

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "plan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["place", "discard"]},
                    "card": {"type": "string"},
                },
                "required": ["action", "card"],
            },
        },
        "reason": {"type": "string"},
    },
    "required": ["plan", "reason"],
}


class AgentError(RuntimeError):
    """Model cagrisi basarisiz oldu veya cevabi kullanilamadi."""


@dataclass
class OllamaConfig:
    host: str = "http://127.0.0.1:11434"
    model: str = "qwen3.5:9b"
    timeout_s: float = 180.0
    temperature: float = 0.2
    max_retries: int = 2
    with_hints: bool = True
    num_ctx: int = 8192
    # Dusunen modellerde (qwen3.x) dusunme zinciri hamle basina dakikalar
    # suruyor ve karar kalitesini olculebilir sekilde artirmiyor.
    think: bool = False
    num_predict: int = 250

    @classmethod
    def from_rules(cls, rules: Rules) -> "OllamaConfig":
        cfg = rules.agent or {}
        return cls(
            host=str(cfg.get("host", cls.host)).rstrip("/"),
            model=str(cfg.get("model", cls.model)),
            timeout_s=float(cfg.get("timeout_s", cls.timeout_s)),
            temperature=float(cfg.get("temperature", cls.temperature)),
            max_retries=int(cfg.get("max_retries", cls.max_retries)),
            with_hints=bool(cfg.get("with_hints", cls.with_hints)),
            num_ctx=int(cfg.get("num_ctx", cls.num_ctx)),
            think=bool(cfg.get("think", cls.think)),
            num_predict=int(cfg.get("num_predict", cls.num_predict)),
        )


def extract_json(text: str) -> Dict[str, Any]:
    """Modelin cevabindan ilk JSON nesnesini cikarir (dusunce bloklarini atar)."""
    cleaned = _THINK_RE.sub("", text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    depth = 0
    start = -1
    for index, char in enumerate(cleaned):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(cleaned[start:index + 1])
                except json.JSONDecodeError:
                    start = -1
    raise AgentError(f"cevapta JSON bulunamadi: {text[:200]!r}")


class OllamaClient:
    def __init__(self, config: OllamaConfig):
        self.config = config
        self.session = requests.Session()
        self._think_supported = True

    def is_available(self) -> bool:
        try:
            return self.session.get(f"{self.config.host}/api/tags", timeout=3).ok
        except requests.RequestException:
            return False

    def installed_models(self) -> List[str]:
        try:
            response = self.session.get(f"{self.config.host}/api/tags", timeout=5)
            response.raise_for_status()
            return [m.get("name", "") for m in response.json().get("models", [])]
        except requests.RequestException:
            return []

    def chat(self, system: str, user: str) -> str:
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": RESPONSE_SCHEMA,
            "options": {
                "temperature": self.config.temperature,
                "num_ctx": self.config.num_ctx,
                "num_predict": self.config.num_predict,
            },
        }
        if self._think_supported:
            payload["think"] = self.config.think

        try:
            response = self.session.post(
                f"{self.config.host}/api/chat", json=payload, timeout=self.config.timeout_s
            )
            if response.status_code == 400 and "think" in response.text.lower():
                # Model dusunmeyi desteklemiyor; parametresiz tekrar dene
                self._think_supported = False
                payload.pop("think", None)
                response = self.session.post(
                    f"{self.config.host}/api/chat", json=payload, timeout=self.config.timeout_s
                )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AgentError(f"ollama cagrisi basarisiz: {exc}") from exc

        data = response.json()
        message = data.get("message") or {}
        content = message.get("content", "")
        if not content and message.get("thinking"):
            raise AgentError("model yalnizca dusunce uretti, cevap bos")
        return content


class OllamaAgent:
    """Her adimda modele danisir, gecersiz plan gelirse tekrar dener."""

    def __init__(self, rules: Rules, config: Optional[OllamaConfig] = None):
        self.rules = rules
        self.config = config or OllamaConfig.from_rules(rules)
        self.client = OllamaClient(self.config)
        self.codec = CardCodec(rules.colors)
        self.system_prompt = build_system_prompt(rules)
        self.name = f"llm:{self.config.model}"
        self.last_prompt = ""
        self.last_raw = ""

    def advise(self, game: OkeyGame) -> Advice:
        if not game.legal_actions():
            raise AgentError("oynanabilecek hamle yok")

        base_prompt = build_user_prompt(game, self.codec, self.config.with_hints)
        self.last_prompt = base_prompt
        errors: List[str] = []
        started = time.perf_counter()

        for attempt in range(1, self.config.max_retries + 2):
            prompt = base_prompt
            if errors:
                prompt += (
                    f"\n\nONCEKI PLAN GECERSIZDI: {errors[-1]}\n"
                    f"Sadece elindeki kartlari kullan: "
                    f"{' '.join(self.codec.label(c) for c in game.hand)}"
                )
            try:
                raw = self.client.chat(self.system_prompt, prompt)
                self.last_raw = raw
                data = extract_json(raw)
                raw_steps = data.get("plan") or []
                if not isinstance(raw_steps, list) or not raw_steps:
                    raise AgentError("plan bos")

                actions = resolve_card_steps(game, raw_steps, self.codec)
                steps = annotate_plan(game, actions)
                if not steps:
                    raise AgentError("planin hicbir adimi uygulanabilir degil")

                return Advice(
                    steps=steps,
                    source=LLM,
                    reason=str(data.get("reason", "")).strip(),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    attempts=attempt,
                    raw=raw,
                )
            except (AgentError, InvalidCard, KeyError, TypeError, ValueError) as exc:
                errors.append(str(exc))

        raise AgentError(" | ".join(errors[-2:]) or "model karar veremedi")
