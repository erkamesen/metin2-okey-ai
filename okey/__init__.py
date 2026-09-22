"""Metin2 Okey — oyun motoru ve ogrenen ajan.

Hizli baslangic:

    from okey import Okey
    okey = Okey()                  # kurallar + deste + puan tablosu
    game = okey.new_game(seed=1)
    while not game.is_over:
        game.apply(game.legal_actions()[0])
    print(game.describe())
"""
from .cards import Deck
from .engine import DISCARD, MELD, IllegalMove, Move, Okey, OkeyGame
from .rules import DEFAULT_RULES, Rules, scoring_rows
from .scoring import GROUP, RUN_MIXED, RUN_SAME, ComboKind, ScoreTable, classify

__version__ = "0.3.0"
__all__ = [
    "Okey", "OkeyGame", "Move", "IllegalMove", "DISCARD", "MELD",
    "Rules", "DEFAULT_RULES", "scoring_rows",
    "Deck", "ScoreTable", "ComboKind", "classify",
    "GROUP", "RUN_SAME", "RUN_MIXED",
]
