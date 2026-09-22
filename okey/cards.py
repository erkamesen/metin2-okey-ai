"""Kartlarin sayiya cevrilmesi.

Her kart bir tamsayi:

    kart = renk_indeksi * sayi_adedi + (sayi - 1)

Yani 24 kartlik destede 0..23 arasi sayilar. Nesne yerine tamsayi kullanmanin
sebebi hiz: karsilastirma, kopyalama, siralama ve kume islemleri tamsayilarda
kat kat ucuz. Milyonlarca oyun simule edecegimiz icin bu fark buyuk.

Insan tarafi icin `Deck.label` / `Deck.parse` var: "5k" = 5 kirmizi.
"""
from __future__ import annotations

import random
from typing import Dict, Iterable, List, Sequence, Tuple

from .rules import DEFAULT_RULES, Rules


class Deck:
    """Bir kural setinin kart evreni: kodlama, cozme ve yazim.

    Kural seti oyun boyunca degismedigi icin bu nesne de bir kez kurulup
    her yerde paylasilabilir.
    """

    __slots__ = ("rules", "ranks", "colors", "n_ranks", "n_colors", "size",
                 "_rank_of", "_color_of", "_labels", "_codes", "_by_label")

    def __init__(self, rules: Rules = DEFAULT_RULES):
        self.rules = rules
        self.ranks: Tuple[int, ...] = tuple(rules.ranks)
        self.colors: Tuple[str, ...] = tuple(rules.colors)
        self.n_ranks = len(self.ranks)
        self.n_colors = len(self.colors)
        self.size = self.n_ranks * self.n_colors

        # Sik kullanilan cevrimler onceden hesaplanip listeye konuyor;
        # oyun sirasinda bolme/modulo yapmaktan daha hizli.
        self._rank_of: Tuple[int, ...] = tuple(
            self.ranks[card % self.n_ranks] for card in range(self.size))
        self._color_of: Tuple[int, ...] = tuple(
            card // self.n_ranks for card in range(self.size))

        self._codes: Tuple[str, ...] = self._unique_codes(self.colors)
        self._labels: Tuple[str, ...] = tuple(
            f"{self._rank_of[c]}{self._codes[self._color_of[c]]}" for c in range(self.size))
        self._by_label: Dict[str, int] = {
            label.lower(): card for card, label in enumerate(self._labels)}

    # ------------------------------------------------------------- cevrimler

    @staticmethod
    def _unique_codes(colors: Sequence[str]) -> Tuple[str, ...]:
        """Renk kisaltmalari: kirmizi->k, mavi->m, sari->s.

        Iki renk ayni harfle baslarsa (or. mavi/mor) kisaltma otomatik olarak
        uzatilir, boylece yazim her zaman tek anlamli kalir.
        """
        codes: List[str] = []
        for color in colors:
            length = 1
            code = color[:length].lower()
            while code in codes and length < len(color):
                length += 1
                code = color[:length].lower()
            codes.append(code)
        return tuple(codes)

    def card(self, rank: int, color: str) -> int:
        """Sayi + renk adindan kart numarasi."""
        return self.colors.index(color) * self.n_ranks + self.ranks.index(rank)

    def rank(self, card: int) -> int:
        return self._rank_of[card]

    def color(self, card: int) -> int:
        """Rengin **indeksi** (adi degil); karsilastirmalar icin."""
        return self._color_of[card]

    def color_name(self, card: int) -> str:
        return self.colors[self._color_of[card]]

    def label(self, card: int) -> str:
        return self._labels[card]

    def labels(self, cards: Iterable[int]) -> str:
        return " ".join(self._labels[c] for c in cards)

    def parse(self, text: str) -> int:
        """"5k" -> kart numarasi. Bilinmeyen yazimda ValueError."""
        key = text.strip().lower().replace("-", "").replace("_", "")
        card = self._by_label.get(key)
        if card is None:
            raise ValueError(
                f"kart okunamadi: {text!r} (ornek: {self._labels[0]}, "
                f"renkler: {', '.join(self._codes)})")
        return card

    def parse_many(self, text: str) -> List[int]:
        """"5k 6k 7k" ya da "5k, 6k, 7k" -> kart listesi."""
        parts = text.replace(",", " ").replace(";", " ").split()
        return [self.parse(part) for part in parts]

    # ------------------------------------------------------------- uretimler

    def all_cards(self) -> List[int]:
        return list(range(self.size))

    def shuffled(self, rng: random.Random) -> List[int]:
        """Karilmis deste. Son elemandan cekilecek sekilde kullanilir."""
        deck = list(range(self.size))
        rng.shuffle(deck)
        return deck

    def __len__(self) -> int:
        return self.size

    def __repr__(self) -> str:
        return f"<Deck {self.size} kart: {self.n_ranks} sayi x {self.n_colors} renk>"
