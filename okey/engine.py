"""Okey mini oyununun kural motoru.

TUR AKISI
    1. Desteden 5 kart cekilir.
    2. Her hamlede iki secenekten biri yapilir:
         - SIL   : elden bir kart kalici olarak cikarilir
         - UCLU  : elden tam 3 kart secilip kombinasyon kurulur (puan gelir)
       Gecersiz uclu kurulamaz; oyun izin vermez.
    3. Her hamleden sonra el desteden 5'e tamamlanir.
    4. Deste bitince ve elde gecerli uclu kalmayinca tur biter.

EYLEMLERIN SAYIYLA GOSTERIMI
    Ogrenen ajanlarin isini kolaylastirmak icin her hamle tek bir tamsayi:

        0 .. hand_size-1            -> eldeki o indeksteki karti sil
        hand_size .. n_actions-1    -> o numarali indeks ucluyle kombinasyon kur

    5 kartlik elde 5 silme + C(5,3)=10 uclu = toplam 15 eylem. El her hamleden
    sonra siralandigi icin bu indeksler kararli: "0 numarali kart" her zaman
    elindeki en kucuk karttir.
"""
from __future__ import annotations

import random
from itertools import combinations
from typing import List, NamedTuple, Optional, Sequence, Tuple

from .cards import Deck
from .rules import DEFAULT_RULES, Rules
from .scoring import ComboKind, ScoreTable

DISCARD = "sil"
MELD = "uclu"


class IllegalMove(ValueError):
    """Kurallara uymayan hamle."""


class Move(NamedTuple):
    """Yapilan hamlenin ozeti (loglama ve gosterim icin)."""

    number: int                     # kacinci hamle
    action: int                     # eylem numarasi
    kind: str                       # DISCARD | MELD
    cards: Tuple[int, ...]          # elden cikan kartlar
    combo: Optional[ComboKind]      # uclu kurulduysa turu ve puani
    points: int
    total_score: int
    drawn: Tuple[int, ...]          # yerine gelen kartlar
    cards_left: int
    finished: bool


class Okey:
    """Kural seti + deste + puan tablosu.

    Puan tablosunu kurmak 2024 ucluyu taramak demek; bunu her oyunda tekrar
    yapmak bosuna. Bu nesne bir kez kurulur, butun oyunlar paylasir.
    """

    __slots__ = ("rules", "deck", "table", "meld_slots", "n_actions", "n_melds")

    def __init__(self, rules: Rules = DEFAULT_RULES):
        rules.validate()
        self.rules = rules
        self.deck = Deck(rules)
        self.table = ScoreTable(self.deck, rules)
        # Eldeki hangi indekslerin uclu olusturabilecegi: (0,1,2), (0,1,3), ...
        self.meld_slots: Tuple[Tuple[int, ...], ...] = tuple(
            combinations(range(rules.hand_size), rules.combo_size))
        self.n_melds = len(self.meld_slots)
        self.n_actions = rules.hand_size + self.n_melds

    # ------------------------------------------------------------- eylemler

    def is_discard(self, action: int) -> bool:
        return 0 <= action < self.rules.hand_size

    def discard_index(self, action: int) -> int:
        return action

    def meld_slot(self, action: int) -> Tuple[int, ...]:
        return self.meld_slots[action - self.rules.hand_size]

    def describe_action(self, action: int, hand: Sequence[int]) -> str:
        if not (0 <= action < self.n_actions):
            return f"tanimsiz eylem {action} (0..{self.n_actions - 1} bekleniyor)"
        if self.is_discard(action):
            index = action
            card = self.deck.label(hand[index]) if index < len(hand) else "?"
            return f"sil {card}"
        slot = self.meld_slot(action)
        if max(slot) >= len(hand):
            return "uclu (gecersiz)"
        triple = tuple(sorted(hand[i] for i in slot))
        return f"uclu {self.table.describe(triple)}"

    def new_game(self, seed: Optional[int] = None) -> "OkeyGame":
        return OkeyGame(self, seed)


class OkeyGame:
    """Tek bir tur. Gecmis turlardan hicbir sey tasimaz."""

    __slots__ = ("okey", "rules", "seed", "rng", "hand", "deck",
                 "discarded", "melds", "score", "move_no", "_over")

    def __init__(self, okey: Okey, seed: Optional[int] = None):
        self.okey = okey
        self.rules = okey.rules
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.rng = random.Random(self.seed)

        self.deck: List[int] = okey.deck.shuffled(self.rng)
        self.hand: List[int] = []
        self.discarded: List[int] = []
        self.melds: List[Tuple[Tuple[int, ...], ComboKind]] = []
        self.score = 0
        self.move_no = 0
        self._over = False

        self._refill()
        self._refresh_over()

    # ------------------------------------------------------------ ic isleyis

    def _refill(self) -> List[int]:
        """Eli desteden 5'e tamamlar; gelen kartlari dondurur."""
        drawn: List[int] = []
        while len(self.hand) < self.rules.hand_size and self.deck:
            card = self.deck.pop()
            self.hand.append(card)      # dongu kosulu eli sayiyor: hemen ekle
            drawn.append(card)
        # El her zaman sirali: eylem indeksleri boylece kararli oluyor.
        self.hand.sort()
        return drawn

    def _refresh_over(self) -> None:
        self._over = not any(self.action_mask())

    # --------------------------------------------------------------- durum

    @property
    def is_over(self) -> bool:
        return self._over

    @property
    def cards_left(self) -> int:
        """Destede kalan kart sayisi."""
        return len(self.deck)

    def unseen(self) -> Tuple[int, ...]:
        """Henuz gorulmemis kartlar — **sirasiz**.

        Kart sayma yapan ajanlar bunu kullanir. Bilerek sirali dondurulur ki
        destenin gercek sirasi sizmasin; ajanin bilmeye hakki olan sey
        "hangi kartlar hala gelebilir", "hangi sirayla gelecek" degil.
        """
        return tuple(sorted(self.deck))

    def chest(self) -> str:
        return self.rules.chest_for(self.score)

    # ------------------------------------------------------------- eylemler

    def action_mask(self) -> List[bool]:
        """Her eylem icin "su anda yapilabilir mi".

        Ogrenen ajan bu maskeyi kullanarak yalnizca gecerli hamleler arasindan
        secer. Gecersiz hamleyi denemesine ve ceza yemesine gerek kalmaz —
        kurallari ogrenmekle vakit kaybetmeyip stratejiye odaklanir.
        """
        okey = self.okey
        mask = [False] * okey.n_actions
        if self._over:
            return mask

        hand = self.hand
        n = len(hand)
        # Kart silmek ancak yerine yeni kart gelebiliyorsa anlamli
        if self.deck:
            for index in range(n):
                mask[index] = True

        table = okey.table
        offset = self.rules.hand_size
        for slot_no, slot in enumerate(okey.meld_slots):
            if slot[-1] >= n:
                continue
            triple = (hand[slot[0]], hand[slot[1]], hand[slot[2]])
            if table.is_valid(triple):
                mask[offset + slot_no] = True
        return mask

    def legal_actions(self) -> List[int]:
        return [action for action, ok in enumerate(self.action_mask()) if ok]

    def is_legal(self, action: int) -> bool:
        if not (0 <= action < self.okey.n_actions):
            return False
        return self.action_mask()[action]

    def apply(self, action: int) -> Move:
        if not self.is_legal(action):
            raise IllegalMove(
                f"gecersiz hamle: {action} "
                f"({self.okey.describe_action(action, self.hand)})")

        self.move_no += 1
        okey = self.okey
        combo: Optional[ComboKind] = None
        points = 0

        if okey.is_discard(action):
            kind = DISCARD
            card = self.hand.pop(action)
            self.discarded.append(card)
            cards: Tuple[int, ...] = (card,)
        else:
            kind = MELD
            slot = okey.meld_slot(action)
            cards = tuple(self.hand[i] for i in slot)
            # Buyukten kucuge cikar ki indeksler kaymasin
            for index in sorted(slot, reverse=True):
                del self.hand[index]
            combo = okey.table.combo(cards)
            points = combo.points
            self.score += points
            self.melds.append((cards, combo))

        drawn = tuple(self._refill())
        self._refresh_over()
        return Move(
            number=self.move_no, action=action, kind=kind, cards=cards,
            combo=combo, points=points, total_score=self.score, drawn=drawn,
            cards_left=len(self.deck), finished=self._over,
        )

    # ---------------------------------------------------------------- ozet

    def summary(self) -> dict:
        kinds: dict = {}
        for _, combo in self.melds:
            kinds[combo.kind] = kinds.get(combo.kind, 0) + 1
        return {
            "seed": self.seed,
            "puan": self.score,
            "uclu": len(self.melds),
            "silinen": len(self.discarded),
            "hamle": self.move_no,
            "elde_kalan": len(self.hand),
            "sandik": self.chest(),
            "turler": kinds,
        }

    def describe(self) -> str:
        deck = self.okey.deck
        lines = [
            f"puan {self.score} ({self.chest()})  "
            f"uclu {len(self.melds)}  destede {len(self.deck)}",
            f"  el      : {deck.labels(self.hand) or '-'}",
            f"  silinen : {deck.labels(self.discarded) or '-'}",
        ]
        for cards, combo in self.melds:
            lines.append(f"  uclu    : {deck.labels(cards)} -> {combo.label} {combo.points}p")
        return "\n".join(lines)

    def copy(self) -> "OkeyGame":
        """Ileriye bakan ajanlar icin hizli kopya."""
        clone = OkeyGame.__new__(OkeyGame)
        clone.okey = self.okey
        clone.rules = self.rules
        clone.seed = self.seed
        clone.rng = random.Random(0)
        clone.deck = list(self.deck)
        clone.hand = list(self.hand)
        clone.discarded = list(self.discarded)
        clone.melds = list(self.melds)
        clone.score = self.score
        clone.move_no = self.move_no
        clone._over = self._over
        return clone
