"""config/rules.yaml dosyasini okuyup dogrulanmis bir kural nesnesi verir."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

import yaml

DEFAULT_CONFIG_PATH = os.path.join("config", "rules.yaml")


@dataclass
class RewardTier:
    min_score: int
    chest: str
    label: str


@dataclass
class Rules:
    ranks: Sequence[int]
    colors: Sequence[str]
    copies: int
    slots: int
    combo_size: int
    hand_size: int
    group_scores: Dict[int, int]
    run_mixed_scores: Dict[int, int]
    run_same_color_scores: Dict[int, int]
    invalid_score: int
    rewards: List[RewardTier]
    agent: dict = field(default_factory=dict)
    logging: dict = field(default_factory=dict)
    cost: dict = field(default_factory=dict)

    @property
    def deck_size(self) -> int:
        return len(self.ranks) * len(self.colors) * self.copies

    @property
    def board_capacity(self) -> int:
        return self.slots * self.combo_size

    @property
    def max_score(self) -> int:
        best_combo = max(
            list(self.group_scores.values())
            + list(self.run_mixed_scores.values())
            + list(self.run_same_color_scores.values())
        )
        return best_combo * self.slots

    def chest_for(self, score: int) -> RewardTier:
        for tier in sorted(self.rewards, key=lambda t: t.min_score, reverse=True):
            if score >= tier.min_score:
                return tier
        return self.rewards[-1]

    def validate(self) -> None:
        if self.combo_size != 3:
            raise ValueError("combo_size su an sadece 3 destekleniyor")
        if self.hand_size < self.combo_size:
            raise ValueError("hand_size, combo_size'dan kucuk olamaz")
        if self.slots < 1:
            raise ValueError("en az bir kombinasyon kurulabilmeli")
        if not self.rewards:
            raise ValueError("en az bir odul kademesi tanimlanmali")


def _int_keyed(raw: dict | None) -> Dict[int, int]:
    return {int(k): int(v) for k, v in (raw or {}).items()}


def load_rules(path: str = DEFAULT_CONFIG_PATH) -> Rules:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    deck = data.get("deck", {})
    board = data.get("board", {})
    scoring = data.get("scoring", {})

    ranks = [int(r) for r in deck.get("ranks", [])]
    colors = [str(c) for c in deck.get("colors", [])]
    copies = int(deck.get("copies", 1))
    combo_size = int(board.get("combo_size", 3))

    # Kombinasyon alanlari sirayla acilir; toplam sayilari desteyle belirlenir.
    # "auto" (varsayilan) = deste / 3.
    raw_slots = board.get("slots", "auto")
    if raw_slots in (None, "auto", "otomatik"):
        slots = (len(ranks) * len(colors) * copies) // combo_size
    else:
        slots = int(raw_slots)

    rules = Rules(
        ranks=ranks,
        colors=colors,
        copies=copies,
        slots=slots,
        combo_size=combo_size,
        hand_size=int(board.get("hand_size", 5)),
        group_scores=_int_keyed(scoring.get("group")),
        run_mixed_scores=_int_keyed(scoring.get("run_mixed")),
        run_same_color_scores=_int_keyed(scoring.get("run_same_color")),
        invalid_score=int(scoring.get("invalid", 0)),
        rewards=[RewardTier(int(r["min_score"]), str(r["chest"]), str(r.get("label", r["chest"])))
                 for r in data.get("rewards", [])],
        agent=data.get("agent", {}) or {},
        logging=data.get("logging", {}) or {},
        cost=data.get("cost", {}) or {},
    )
    rules.validate()
    return rules
