"""Metin2 Okey - kural motoru + karar agent'i + canli danisman UI."""
from .cards import Card, CardCodec, build_deck, shuffled_deck
from .engine import Action, InvalidCard, MoveOutcome, OkeyGame, Slot, DISCARD, PLACE
from .rules import Rules, load_rules
from .scoring import ComboResult, classify, score_combo
from .solver import Solver, SolverConfig

__version__ = "0.2.0"
__all__ = [
    "Card", "CardCodec", "build_deck", "shuffled_deck",
    "Action", "MoveOutcome", "OkeyGame", "Slot", "PLACE", "DISCARD", "InvalidCard",
    "Rules", "load_rules",
    "ComboResult", "classify", "score_combo",
    "Solver", "SolverConfig",
]
