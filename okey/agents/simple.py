"""Basit referans oyuncular.

Ucu de "ogrenmiyor"; elle yazilmis kurallarla oynuyorlar. Ogrenen ajanin
yenmesi gereken cita bunlar. Her biri bir oncekine tek bir fikir ekliyor,
boylece hangi fikrin kac puan getirdigini gorebiliyoruz.
"""
from __future__ import annotations

import random
from typing import List, Optional

from ..engine import OkeyGame
from .base import Agent


class RandomAgent(Agent):
    """Gecerli hamleler arasindan rastgele secer.

    En alt cita. Bir ajan bunu yenemiyorsa hicbir sey ogrenmemis demektir.
    """

    name = "rastgele"

    def __init__(self, seed: Optional[int] = 0):
        self.rng = random.Random(seed)

    def act(self, game: OkeyGame) -> int:
        return self.rng.choice(game.legal_actions())


class GreedyAgent(Agent):
    """Uclu kurabiliyorsa en yuksek puanliyi kurar, yoksa en olu karti siler.

    Iki basit fikir:

    1. **Bekleme.** Uclu varsa hemen kur. (Bunun her zaman dogru olmadigini
       ileride gorecegiz: bazen kucuk bir ucluyu bozup buyugunu beklemek
       daha iyi. Ama baslangic icin makul.)
    2. **Olu karti at.** Her kart icin "elde ve destede kalanlarla bu kart
       en iyi hangi ucluyu kurabilir" hesaplanir; en dusugu silinir. Hic
       uclu kuramayan bir kart 0 alir ve ilk o gider.
    """

    name = "acgozlu"

    def act(self, game: OkeyGame) -> int:
        okey = game.okey
        actions = game.legal_actions()

        melds = [a for a in actions if not okey.is_discard(a)]
        if melds:
            return max(melds, key=lambda a: self._meld_points(game, a))

        discards = [a for a in actions if okey.is_discard(a)]
        if not discards:
            return actions[0]
        return min(discards, key=lambda a: self._card_value(game, game.hand[a]))

    # ---------------------------------------------------------------- yardim

    @staticmethod
    def _meld_points(game: OkeyGame, action: int) -> int:
        slot = game.okey.meld_slot(action)
        triple = tuple(sorted(game.hand[i] for i in slot))
        return game.okey.table.points(triple)

    @staticmethod
    def _available(game: OkeyGame) -> frozenset:
        """Hala oyunda olan kartlar: elindekiler + destede kalanlar."""
        return frozenset(game.hand) | frozenset(game.unseen())

    def _card_value(self, game: OkeyGame, card: int) -> int:
        return game.okey.table.best_use_of(card, self._available(game))


class LookaheadAgent(Agent):
    """Her hamleyi deneyip turu sonuna kadar simule eder, en iyisini secer.

    Monte-Carlo: destenin gercek sirasini bilmedigimiz icin gorulmemis
    kartlari rastgele siralayip oyunu sonuna kadar oynatiyoruz. Bunu her aday
    hamle icin defalarca yapip ortalamasini aliyoruz.

    Iki nokta kritik:

    * **Hile yok.** Ajan destenin gercek sirasina bakmaz; kendi karistirdigi
      destelerle calisir (`game.with_deck`).
    * **Ortak desteler.** Butun adaylar **ayni** deste siralarinda denenir.
      Her adaya farkli desteler verirsek, aradaki fark gurultuye bogulur:
      tur puanlarinin standart sapmasi ~60, yani 12 simulasyonla tek bir
      adayin hatasi +-17 puan olur. Ayni desteler kullanilinca fark
      eslestirilmis olculuyor ve ayni sayida simulasyonla cok daha guvenilir
      siralama cikiyor.
    """

    name = "ileri-bakisli"

    def __init__(self, rollouts: int = 12, seed: Optional[int] = 0,
                 policy: Optional[Agent] = None):
        self.rollouts = rollouts
        self.rng = random.Random(seed)
        # Simulasyon sirasinda oynayan ajan. Hizli olmasi gerekiyor cunku
        # binlerce kez calisacak.
        self.policy = policy or GreedyAgent()
        self.name = f"ileri-bakisli-{rollouts}"

    def act(self, game: OkeyGame) -> int:
        actions = game.legal_actions()
        if len(actions) == 1:
            return actions[0]

        decks = self._sample_decks(game)
        best_action, best_mean = actions[0], float("-inf")
        for action in actions:
            total = 0
            for deck in decks:
                total += self._rollout(game, action, deck)
            mean = total / len(decks)
            if mean > best_mean:
                best_action, best_mean = action, mean
        return best_action

    # ---------------------------------------------------------------- yardim

    def _sample_decks(self, game: OkeyGame) -> List[List[int]]:
        """Ortak deste siralari: her aday ayni desteler uzerinde denenir."""
        pool = list(game.unseen())
        decks = []
        for _ in range(self.rollouts):
            order = list(pool)
            self.rng.shuffle(order)
            decks.append(order)
        return decks

    def _rollout(self, game: OkeyGame, action: int, deck: List[int]) -> int:
        sim = game.with_deck(deck)
        sim.apply(action)
        guard = 0
        while not sim.is_over and guard < 100:
            sim.apply(self.policy.act(sim))
            guard += 1
        return sim.score
