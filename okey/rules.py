"""Oyunun butun sayilari tek yerde.

Bu dosya bilerek sade Python: hicbir kutuphane gerekmiyor ve her satirin
yanina neden oyle oldugunu yazabiliyoruz. Bir sayiyi degistirmek istersen
asagidaki `DEFAULT_RULES` icinde degistir, motor gerisini kendi ayarlar.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Sequence

# ---------------------------------------------------------------- varsayilan

#: Deste: her renkten 1..8, her karttan **birer** tane -> 24 kart.
#: Kart sayisi tek oldugu icin "bir kart ya elinde, ya destede, ya da silinmis"
#: diyebiliyoruz; bu, ilerideki ogrenen ajan icin cok ise yarayacak.
RANKS: Sequence[int] = (1, 2, 3, 4, 5, 6, 7, 8)
COLORS: Sequence[str] = ("kirmizi", "mavi", "sari")

#: Ayni sayidan uc kart. Tek kopya oldugu icin bu her zaman "her renkten bir
#: tane" demek: 5-kirmizi + 5-mavi + 5-sari.
GROUP_SCORES: Dict[int, int] = {
    1: 20, 2: 30, 3: 40, 4: 50, 5: 60, 6: 70, 7: 80, 8: 90,
}

#: Ardisik uc sayi, ucu de ayni renk. Anahtar = serinin en kucuk sayisi.
RUN_SAME_COLOR_SCORES: Dict[int, int] = {
    1: 50, 2: 60, 3: 70, 4: 80, 5: 90, 6: 100,
}

#: Ardisik uc sayi, en az biri farkli renk. Anahtar = serinin en kucuk sayisi.
RUN_MIXED_SCORES: Dict[int, int] = {
    1: 10, 2: 20, 3: 30, 4: 40, 5: 50, 6: 60,
}

#: Tur sonu sandigi: (en dusuk puan, isim). Buyukten kucuge kontrol edilir.
CHESTS: Sequence[tuple] = (
    (400, "altin"),
    (300, "gumus"),
    (0, "bronz"),
)


@dataclass(frozen=True)
class Rules:
    """Motorun ihtiyac duydugu her sey.

    `frozen=True`: kurallar oyun sirasinda degismez. Yanlislikla degistirmeyi
    imkansiz kilmak, "acaba bu tur hangi puan tablosuyla oynandi" sorusunu
    tamamen ortadan kaldiriyor.
    """

    ranks: Sequence[int] = RANKS
    colors: Sequence[str] = COLORS
    hand_size: int = 5              # elde ayni anda en fazla kac kart olur
    combo_size: int = 3             # bir kombinasyon kac karttan olusur

    group_scores: Dict[int, int] = field(default_factory=lambda: dict(GROUP_SCORES))
    run_same_color_scores: Dict[int, int] = field(
        default_factory=lambda: dict(RUN_SAME_COLOR_SCORES))
    run_mixed_scores: Dict[int, int] = field(
        default_factory=lambda: dict(RUN_MIXED_SCORES))
    chests: Sequence[tuple] = CHESTS

    # ------------------------------------------------------------ turetilen

    @property
    def deck_size(self) -> int:
        return len(self.ranks) * len(self.colors)

    @property
    def max_combos(self) -> int:
        """Hic kart silmeden en fazla kac kombinasyon kurulabilir."""
        return self.deck_size // self.combo_size

    @property
    def best_combo(self) -> int:
        return max([*self.group_scores.values(),
                    *self.run_same_color_scores.values(),
                    *self.run_mixed_scores.values()])

    @property
    def score_ceiling(self) -> int:
        """Ust sinir: her kombinasyon en iyi ihtimalle en yuksek puani verse.

        Gercekte ulasilamaz (ayni kartlari iki kombinasyonda kullanamazsin);
        sadece "yuzde kac" hesaplarinda olcek olarak kullaniliyor.
        """
        return self.best_combo * self.max_combos

    def chest_for(self, score: int) -> str:
        for threshold, name in sorted(self.chests, reverse=True):
            if score >= threshold:
                return name
        return self.chests[-1][1]

    def validate(self) -> None:
        if self.combo_size != 3:
            raise ValueError("combo_size su an sadece 3 destekleniyor")
        if self.hand_size < self.combo_size:
            raise ValueError("elde en az combo_size kadar kart olabilmeli")
        if len(self.colors) < 2:
            raise ValueError("en az iki renk gerekli")
        if not self.chests:
            raise ValueError("en az bir sandik kademesi tanimlanmali")

    def with_(self, **changes) -> "Rules":
        """Tek bir ayari degistirilmis yeni kural seti (deneyler icin)."""
        updated = replace(self, **changes)
        updated.validate()
        return updated


DEFAULT_RULES = Rules()
DEFAULT_RULES.validate()


def scoring_rows(rules: Rules = DEFAULT_RULES) -> List[dict]:
    """Puan tablosunu duz liste halinde verir (yazdirmak/gostermek icin)."""
    rows: List[dict] = []
    for rank, points in sorted(rules.group_scores.items()):
        rows.append({"tur": "grup", "desen": f"{rank}-{rank}-{rank}", "puan": points})
    for start, points in sorted(rules.run_same_color_scores.items()):
        rows.append({"tur": "seri-ayni-renk",
                     "desen": f"{start}-{start+1}-{start+2}", "puan": points})
    for start, points in sorted(rules.run_mixed_scores.items()):
        rows.append({"tur": "seri-karisik",
                     "desen": f"{start}-{start+1}-{start+2}", "puan": points})
    return rows
