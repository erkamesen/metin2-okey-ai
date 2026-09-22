"""Kombinasyonlarin puanlanmasi.

Ana fikir: oyun basladiginda **butun gecerli ucluleri bir kez** hesaplayip
tabloya koyuyoruz. 24 karttan 3'lu secmenin 2024 ihtimali var; bunlarin
puanlarini onceden cikarmak bir milisaniye surmuyor. Karsiliginda oyun
sirasinda "bu uclu gecerli mi, kac puan" sorusu tek sozluk bakisina iniyor.

Tabloda olmayan uclu = gecersiz. Oyun gecersiz uclu kurmaya zaten izin
vermiyor, bu yuzden "0 puanlik uclu" diye bir sey yok.
"""
from __future__ import annotations

from itertools import combinations
from typing import Dict, Optional, Tuple

from .cards import Deck
from .rules import DEFAULT_RULES, Rules

GROUP = "grup"
RUN_SAME = "seri-ayni-renk"
RUN_MIXED = "seri-karisik"

Triple = Tuple[int, int, int]      # her zaman kucukten buyuge sirali


class ComboKind:
    """Bir uclunun turu ve puani."""

    __slots__ = ("kind", "points", "key")

    def __init__(self, kind: str, points: int, key: int):
        self.kind = kind        # GROUP | RUN_SAME | RUN_MIXED
        self.points = points
        self.key = key          # grupta sayi, seride en kucuk sayi

    @property
    def label(self) -> str:
        return {
            GROUP: f"Grup {self.key}-{self.key}-{self.key}",
            RUN_SAME: f"Ayni renk {self.key}-{self.key + 1}-{self.key + 2}",
            RUN_MIXED: f"Karisik {self.key}-{self.key + 1}-{self.key + 2}",
        }[self.kind]

    def __repr__(self) -> str:
        return f"<{self.label} = {self.points}p>"


def classify(deck: Deck, triple: Triple, rules: Rules) -> Optional[ComboKind]:
    """Uc kart gecerli bir kombinasyon mu? Degilse None.

    Bu fonksiyon tabloyu kurarken bir kez calisir; oyun sirasinda kullanilmaz.
    """
    ranks = sorted(deck.rank(card) for card in triple)
    same_color = len({deck.color(card) for card in triple}) == 1

    # Ayni sayidan uc kart
    if ranks[0] == ranks[1] == ranks[2]:
        points = rules.group_scores.get(ranks[0])
        return None if points is None else ComboKind(GROUP, points, ranks[0])

    # Ardisik uc sayi
    if ranks[1] == ranks[0] + 1 and ranks[2] == ranks[1] + 1:
        table = rules.run_same_color_scores if same_color else rules.run_mixed_scores
        points = table.get(ranks[0])
        kind = RUN_SAME if same_color else RUN_MIXED
        return None if points is None else ComboKind(kind, points, ranks[0])

    return None


class ScoreTable:
    """Onceden hesaplanmis "uclu -> puan" tablosu.

    `points(triple)` sifir donerse uclu gecersizdir.
    """

    __slots__ = ("deck", "rules", "_points", "_combos")

    def __init__(self, deck: Deck, rules: Rules = DEFAULT_RULES):
        self.deck = deck
        self.rules = rules
        self._points: Dict[Triple, int] = {}
        self._combos: Dict[Triple, ComboKind] = {}

        for triple in combinations(range(deck.size), rules.combo_size):
            combo = classify(deck, triple, rules)
            if combo is not None:
                self._points[triple] = combo.points
                self._combos[triple] = combo

    # ------------------------------------------------------------- sorgular

    def points(self, triple: Triple) -> int:
        """Uclunun puani; gecersizse 0."""
        return self._points.get(triple, 0)

    def combo(self, triple: Triple) -> Optional[ComboKind]:
        return self._combos.get(triple)

    def is_valid(self, triple: Triple) -> bool:
        return triple in self._points

    def describe(self, triple: Triple) -> str:
        combo = self._combos.get(triple)
        cards = self.deck.labels(triple)
        return f"{cards} -> {combo.label} {combo.points}p" if combo else f"{cards} -> gecersiz"

    # ------------------------------------------------------------ istatistik

    def __len__(self) -> int:
        return len(self._points)

    def valid_triples(self) -> Dict[Triple, int]:
        """Tum gecerli ucluler ve puanlari (analiz/ogretim icin)."""
        return dict(self._points)

    def best_points(self) -> int:
        return max(self._points.values(), default=0)

    def summary(self) -> Dict[str, int]:
        """Her turden kac gecerli uclu var (tabloyu anlamak icin)."""
        counts: Dict[str, int] = {GROUP: 0, RUN_SAME: 0, RUN_MIXED: 0}
        for combo in self._combos.values():
            counts[combo.kind] += 1
        return counts
