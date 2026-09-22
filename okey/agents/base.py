"""Ajan arayuzu.

Bir ajan tek bir soruyu cevaplar: "bu durumda hangi eylemi yaparim?"
Cevap bir tamsayi — motorun eylem numarasi.

    class Agent:
        def act(self, game) -> int

Bu kadar sade olmasi bilincli. Ilerideki ogrenen ajan da ayni arayuzu
kullanacak, boylece rastgele oynayanla sinir agini ayni olcum duzeneginde
yan yana koyabilecegiz.
"""
from __future__ import annotations

from typing import List, Optional

from ..engine import Okey, OkeyGame


class Agent:
    """Butun ajanlarin ortak atasi."""

    name = "ajan"

    def act(self, game: OkeyGame) -> int:
        """Bu durumda yapilacak eylemin numarasi."""
        raise NotImplementedError

    def reset(self) -> None:
        """Yeni tur basliyor. Tur arasi hafiza tutan ajanlar icin."""

    def __repr__(self) -> str:
        return f"<{self.name}>"


def play_game(okey: Okey, agent: Agent, seed: Optional[int] = None,
              max_moves: int = 200) -> OkeyGame:
    """Tek bir turu bastan sona oynatir ve biten oyunu dondurur."""
    game = okey.new_game(seed)
    agent.reset()
    moves = 0
    while not game.is_over and moves < max_moves:
        game.apply(agent.act(game))
        moves += 1
    return game


def play_many(okey: Okey, agent: Agent, seeds: List[int]) -> List[OkeyGame]:
    """Ayni seed listesini oynatir.

    Ajanlari **ayni** seed'lerle oynatmak olcumun temeli: boylece "bu ajan
    daha mi iyi" sorusu ile "bu ajanin destesi daha mi iyiydi" sorusu
    birbirine karismaz.
    """
    return [play_game(okey, agent, seed) for seed in seeds]
