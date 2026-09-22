"""Kart ve deste tanimlari."""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable, List, Sequence


@dataclass(frozen=True, order=True)
class Card:
    """Tek bir okey karti: bir sayi ve bir renk."""

    rank: int
    color: str

    def __str__(self) -> str:  # "5r" gibi kisa gosterim
        return f"{self.rank}{self.color[0]}"

    def to_dict(self) -> dict:
        return {"rank": self.rank, "color": self.color}

    @classmethod
    def from_dict(cls, data: dict) -> "Card":
        return cls(int(data["rank"]), str(data["color"]))


def build_deck(ranks: Sequence[int], colors: Sequence[str], copies: int = 1) -> List[Card]:
    """Config'teki sayi/renk listesinden tam desteyi uretir."""
    deck: List[Card] = []
    for _ in range(copies):
        for color in colors:
            for rank in ranks:
                deck.append(Card(rank, color))
    return deck


def shuffled_deck(
    ranks: Sequence[int],
    colors: Sequence[str],
    copies: int = 1,
    rng: random.Random | None = None,
) -> List[Card]:
    deck = build_deck(ranks, colors, copies)
    (rng or random).shuffle(deck)
    return deck


def counter_of(cards: Iterable[Card]) -> dict:
    """Kart -> adet sozlugu (gorulmemis kart havuzu hesaplari icin)."""
    counts: dict = {}
    for card in cards:
        counts[card] = counts.get(card, 0) + 1
    return counts


class CardCodec:
    """Kartlarin kisa yazimi: "7r" = 7 kirmizi.

    Renk kisaltmalari config'teki renk listesinden uretilir ve benzersiz olmasi
    garanti edilir (or. blue + black -> "b" ve "bl"). Hem LLM protokolunde hem
    de kullanicinin elle yazdigi girdide bu yazim kullanilir.
    """

    def __init__(self, colors: Sequence[str]):
        self.colors = list(colors)
        self.to_code: dict = {}
        for color in self.colors:
            length = 1
            code = color[:length].lower()
            while code in self.to_code.values() and length < len(color):
                length += 1
                code = color[:length].lower()
            self.to_code[color] = code
        self.from_code = {code: color for color, code in self.to_code.items()}

    def label(self, card: Card) -> str:
        return f"{card.rank}{self.to_code.get(card.color, card.color)}"

    def parse(self, text: str) -> Card:
        raw = text.strip().lower().replace("-", "").replace("_", "")
        if not raw:
            raise ValueError("bos kart")
        digits = ""
        index = 0
        while index < len(raw) and raw[index].isdigit():
            digits += raw[index]
            index += 1
        suffix = raw[index:]
        if not digits or not suffix:
            raise ValueError(f"kart okunamadi: {text!r} (ornek: 7r)")
        color = self.from_code.get(suffix)
        if color is None:
            color = next((c for c in self.colors if c.lower() == suffix), None)
        if color is None:
            raise ValueError(f"bilinmeyen renk: {suffix!r} ({', '.join(self.from_code)})")
        return Card(int(digits), color)

    def parse_many(self, text: str) -> List[Card]:
        """"7r 4b, 1g" gibi serbest yazimi kart listesine cevirir."""
        parts = [p for p in text.replace(",", " ").replace(";", " ").split() if p]
        return [self.parse(part) for part in parts]
