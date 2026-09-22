"""Ogrenen ajan: dogrusal deger fonksiyonu.

NASIL KARAR VERIYOR
    Her gecerli eylem icin "bu eylemi yaparsam ortaya cikan durum" hesaplanir
    (henuz kart cekilmemis hali — bkz. features.py). O durumun degeri:

        V(durum) = agirliklar . ozellikler

    Eylemin toplam degeri ise:

        hemen kazanilan puan  +  V(sonraki durum)

    En yuksegi secilir. Agirliklar egitimle ogrenilir (train.py).

NEDEN DOGRUSAL
    Saf Python'da sinir agi egitmek pratik degil. Ama daha onemlisi:
    ogrenilen agirliklar **okunabilir**. Egitim bitince "ajan neyi onemli
    buldu" diye bakabiliyorsun. Kara kutu degil.
"""
from __future__ import annotations

import json
import os
import random
from typing import Dict, List, Optional, Sequence, Tuple

from ..engine import OkeyGame
from ..features import FEATURE_NAMES, N_FEATURES, FeatureExtractor
from .base import Agent

DEFAULT_WEIGHTS_PATH = "agirliklar.json"


class LinearAgent(Agent):
    """Ogrenilmis agirliklarla oynayan ajan."""

    name = "ogrenen"

    def __init__(self, okey, weights: Optional[Sequence[float]] = None,
                 epsilon: float = 0.0, seed: Optional[int] = 0,
                 reward_scale: float = 100.0):
        self.okey = okey
        self.features = FeatureExtractor(okey.table, okey.rules)
        self.weights: List[float] = list(weights) if weights else [0.0] * N_FEATURES
        if len(self.weights) != N_FEATURES:
            raise ValueError(
                f"{N_FEATURES} agirlik bekleniyor, {len(self.weights)} verildi")
        self.epsilon = epsilon        # kesif orani (egitimde >0, olcumde 0)
        self.rng = random.Random(seed)
        # Puanlar 0..100; 100'e bolunce degerler ~0..4 araliginda kaliyor ve
        # tek bir ogrenme hizi butun ozelliklere uyuyor. **Onemli**: hemen
        # kazanilan puan ile ogrenilen deger AYNI olcekte olmali, yoksa ham
        # puan (70 gibi) ogrenilen degeri (0.5 gibi) tamamen bastirir ve ajan
        # ne ogrenirse ogrensin acgozlu gibi oynar.
        self.reward_scale = reward_scale

    # ------------------------------------------------------------- karar

    def act(self, game: OkeyGame) -> int:
        actions = game.legal_actions()
        if self.epsilon and self.rng.random() < self.epsilon:
            return self.rng.choice(actions)
        return self.evaluate(game)[0]

    def evaluate(self, game: OkeyGame) -> Tuple[int, float, List[float]]:
        """En iyi eylemi, degerini ve o eylemin ozelliklerini dondurur.

        Egitim sirasinda ozelliklere de ihtiyac var (agirlik guncellemesi
        icin), o yuzden hepsini birden donduruyoruz.
        """
        best_action, best_value, best_features = -1, float("-inf"), None
        scale = self.reward_scale
        for action, points, vector in self.candidates(game):
            value = points / scale + self.value(vector)
            if value > best_value:
                best_action, best_value, best_features = action, value, vector
        return best_action, best_value, best_features

    def candidates(self, game: OkeyGame):
        """Her gecerli eylem icin (eylem, hemen kazanilan puan, ozellikler).

        Oyunu kopyalamadan hesapliyoruz: bir eylem sadece elden kart cikarir,
        deste degismez. Kopyalamak binlerce kez tekrarlandiginda pahali olur.
        """
        okey = self.okey
        hand = game.hand
        unseen = frozenset(game.deck)
        melds_done = len(game.melds)

        for action in game.legal_actions():
            if okey.is_discard(action):
                rest = hand[:action] + hand[action + 1:]
                points = 0
            else:
                slot = okey.meld_slot(action)
                taken = set(slot)
                rest = [card for index, card in enumerate(hand) if index not in taken]
                triple = tuple(sorted(hand[i] for i in slot))
                points = okey.table.points(triple)

            available = frozenset(rest) | unseen
            vector = self.features.extract(rest, available, len(game.deck),
                                           melds_done + (1 if points else 0))
            yield action, points, vector

    def value(self, vector: Sequence[float]) -> float:
        weights = self.weights
        return sum(w * f for w, f in zip(weights, vector))

    # ------------------------------------------------------------- kayit

    def save(self, path: str = DEFAULT_WEIGHTS_PATH, extra: Optional[Dict] = None) -> None:
        payload = {
            "ozellikler": list(FEATURE_NAMES),
            "agirliklar": self.weights,
        }
        if extra:
            payload.update(extra)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, okey, path: str = DEFAULT_WEIGHTS_PATH, **kwargs) -> "LinearAgent":
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        names = payload.get("ozellikler")
        if names and list(names) != list(FEATURE_NAMES):
            raise ValueError(
                "kayitli agirliklar baska bir ozellik kumesine ait; "
                "yeniden egitmen gerekiyor")
        return cls(okey, payload["agirliklar"], **kwargs)

    @classmethod
    def load_if_trained(cls, okey, path: str = DEFAULT_WEIGHTS_PATH, **kwargs):
        """Egitilmis agirlik varsa yukler, yoksa None."""
        return cls.load(okey, path, **kwargs) if os.path.exists(path) else None

    # ------------------------------------------------------------ okuma

    def explain(self) -> str:
        """Ogrenilen agirliklari buyukten kucuge yazar."""
        rows = sorted(zip(FEATURE_NAMES, self.weights), key=lambda row: -abs(row[1]))
        width = max(len(name) for name in FEATURE_NAMES)
        lines = ["  ozellik".ljust(width + 4) + "agirlik"]
        for name, weight in rows:
            bar = "#" * min(30, int(abs(weight) * 10))
            lines.append(f"  {name:<{width}}  {weight:>+8.3f}  {bar}")
        return "\n".join(lines)
