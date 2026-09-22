"""Oyunu oynayan ajanlar."""
from .base import Agent, play_game, play_many
from .simple import GreedyAgent, LookaheadAgent, RandomAgent

#: Isimle ajan kurmak icin (evaluate.py bunu kullaniyor).
REGISTRY = {
    "rastgele": RandomAgent,
    "acgozlu": GreedyAgent,
    "ileri": LookaheadAgent,
}

__all__ = [
    "Agent", "play_game", "play_many",
    "RandomAgent", "GreedyAgent", "LookaheadAgent", "REGISTRY",
]
