"""Agent arayuzu ve ortak veri tipleri.

Agent tek bir hamle degil, **plan** uretir: "su karti su alana koy, su karti at".
Boylece oyuncu gercek oyunda birkac islemi arka arkaya yapip sonra yerine gelen
kartlari tek seferde girebilir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol, Sequence

from ..cards import Card, CardCodec
from ..engine import (
    COMPLETE, COMPLETE_ACTION, DISCARD, PLACE, Action, InvalidCard, OkeyGame,
    clone_for_search,
)
from ..scoring import ComboResult

LLM = "llm"
SOLVER = "solver"
HUMAN = "human"


@dataclass
class PlanStep:
    """Plandaki tek bir islem, oyuncuya gosterilecek haliyle.

    TAMAMLA adiminda kart yoktur (`card is None`); o adim ucluyu kilitler.
    """

    action: Action
    card: Optional[Card]
    slot_index: Optional[int]
    completes: Optional[ComboResult]
    points: int
    note: str = ""

    @property
    def kind(self) -> str:
        return self.action.type

    def to_dict(self, codec: Optional[CardCodec] = None) -> dict:
        label = ""
        if self.card is not None:
            label = codec.label(self.card) if codec else str(self.card)
        return {
            "action": self.action.to_dict(),
            "type": self.action.type,
            "card": self.card.to_dict() if self.card else None,
            "card_label": label,
            "slot_index": self.slot_index,
            "completes": self.completes.to_dict() if self.completes else None,
            "points": self.points,
            "note": self.note,
        }


@dataclass
class Advice:
    """Agent'in onerisi: bir veya birden fazla adim + gerekce."""

    steps: List[PlanStep] = field(default_factory=list)
    source: str = SOLVER
    reason: str = ""
    latency_ms: int = 0
    attempts: int = 1
    fallback_reason: str = ""
    raw: Optional[str] = None

    @property
    def total_points(self) -> int:
        return sum(step.points for step in self.steps)

    def to_dict(self, codec: Optional[CardCodec] = None) -> dict:
        return {
            "steps": [step.to_dict(codec) for step in self.steps],
            "source": self.source,
            "reason": self.reason,
            "latency_ms": self.latency_ms,
            "attempts": self.attempts,
            "fallback_reason": self.fallback_reason,
            "total_points": self.total_points,
        }


class Agent(Protocol):
    name: str

    def advise(self, game: OkeyGame) -> Advice:
        ...


# --------------------------------------------------------------- plan kurma


def annotate_plan(game: OkeyGame, actions: Sequence[Action]) -> List[PlanStep]:
    """Hamle dizisini dogrular ve her adimin ne yapacagini hesaplar.

    Gecersiz bir adima rastlanirsa o adimda durur; gecerli olan on ek dondurulur.
    Boylece modelin planinin ilk dogru kismi yine de kullanilabilir.
    """
    sim = clone_for_search(game, planning=True)
    steps: List[PlanStep] = []
    for action in actions:
        if not sim.is_legal(action):
            break
        card = None if action.type == COMPLETE else sim.hand[action.card_index]
        outcome = sim.apply(action)
        steps.append(PlanStep(
            action=action,
            card=card,
            slot_index=outcome.slot_index,
            completes=outcome.completed,
            points=outcome.points,
            note=_describe(outcome.completed, action),
        ))
    return steps


def _describe(completed: Optional[ComboResult], action: Action) -> str:
    if completed:
        return f"{completed.label} -> {completed.points} puan"
    if action.type == DISCARD:
        return "kart at"
    if action.type == COMPLETE:
        return "ucluyu tamamla"
    return "ucluye ekle"


def resolve_card_steps(game: OkeyGame, raw_steps: Sequence[dict], codec: CardCodec) -> List[Action]:
    """Kart adiyla verilen plani ("8r koy") hamle dizisine cevirir.

    Kart indeksleri her hamlede kaydigi icin adimlar sirayla bir kopya uzerinde
    cozulur. Uclu dolunca TAMAMLA adimi kendiliginden eklenir; modelin bunu
    bilmesi gerekmiyor.
    """
    sim = clone_for_search(game, planning=True)
    actions: List[Action] = []

    def maybe_complete() -> None:
        if sim.can_complete:
            sim.apply(COMPLETE_ACTION)
            actions.append(COMPLETE_ACTION)

    maybe_complete()          # oyuncu ucluyu elle doldurmus olabilir
    for raw in raw_steps:
        kind = str(raw.get("action", "")).strip().lower()
        if kind not in (PLACE, DISCARD):
            raise InvalidCard(f"bilinmeyen islem: {raw.get('action')!r} (place/discard)")
        card = raw.get("card")
        card = card if isinstance(card, Card) else codec.parse(str(card))
        index = sim.find_card(card)
        action = Action(kind, index)
        if not sim.is_legal(action):
            raise InvalidCard(f"gecersiz adim: {kind} {codec.label(card)}")
        sim.apply(action)
        actions.append(action)
        maybe_complete()
    return actions
