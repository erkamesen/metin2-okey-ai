"""Kombinasyon tipleri ve puan hesabi."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

from .cards import Card
from .rules import Rules

GROUP = "group"
RUN_SAME = "run_same_color"
RUN_MIXED = "run_mixed"
INVALID = "invalid"

_TYPE_LABELS = {
    GROUP: "Grup",
    RUN_SAME: "Seri (ayni renk)",
    RUN_MIXED: "Seri (karisik renk)",
    INVALID: "Gecersiz",
}


@dataclass(frozen=True)
class ComboResult:
    kind: str
    points: int
    key: int | None  # grup icin sayi, seri icin en kucuk sayi

    @property
    def label(self) -> str:
        return _TYPE_LABELS.get(self.kind, self.kind)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "label": self.label, "points": self.points, "key": self.key}


INVALID_RESULT = ComboResult(INVALID, 0, None)


def classify(cards: Sequence[Card]) -> ComboResult:
    """Kombinasyon tipini belirler; puani classify_with_rules doldurur."""
    if len(cards) != 3 or any(c is None for c in cards):
        return INVALID_RESULT

    ranks = sorted(c.rank for c in cards)
    same_color = len({c.color for c in cards}) == 1

    if ranks[0] == ranks[1] == ranks[2]:
        return ComboResult(GROUP, 0, ranks[0])

    if ranks[1] == ranks[0] + 1 and ranks[2] == ranks[1] + 1:
        return ComboResult(RUN_SAME if same_color else RUN_MIXED, 0, ranks[0])

    return INVALID_RESULT


def score_combo(cards: Sequence[Card], rules: Rules) -> ComboResult:
    """Uc karta kural tablosundaki puani uygular."""
    base = classify(cards)
    if base.kind == INVALID:
        return ComboResult(INVALID, rules.invalid_score, None)

    table = {
        GROUP: rules.group_scores,
        RUN_SAME: rules.run_same_color_scores,
        RUN_MIXED: rules.run_mixed_scores,
    }[base.kind]

    points = table.get(base.key)
    if points is None:
        # Kural tablosunda karsiligi olmayan kombinasyon (or. 7-8-9 serisi yok)
        return ComboResult(INVALID, rules.invalid_score, None)
    return ComboResult(base.kind, int(points), base.key)


def best_possible_score(rules: Rules) -> int:
    return rules.max_score


def all_scoring_combos(rules: Rules) -> List[dict]:
    """UI'da kural tablosunu gostermek icin duz liste."""
    rows: List[dict] = []
    for rank, pts in sorted(rules.group_scores.items()):
        rows.append({"kind": GROUP, "pattern": f"{rank}-{rank}-{rank}", "points": pts})
    for rank, pts in sorted(rules.run_mixed_scores.items()):
        rows.append({"kind": RUN_MIXED, "pattern": f"{rank}-{rank+1}-{rank+2}", "points": pts})
    for rank, pts in sorted(rules.run_same_color_scores.items()):
        rows.append({"kind": RUN_SAME, "pattern": f"{rank}-{rank+1}-{rank+2}", "points": pts})
    return rows
