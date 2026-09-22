"""Oyunu oynayan ajanlar."""
from .base import Agent, play_game, play_many
from .linear import LinearAgent
from .simple import GreedyAgent, LookaheadAgent, RandomAgent

#: Isimle ajan kurmak icin (evaluate.py ve replay.py bunu kullaniyor).
REGISTRY = {
    "rastgele": RandomAgent,
    "acgozlu": GreedyAgent,
    "ileri": LookaheadAgent,
    "ogrenen": LinearAgent,
}

__all__ = [
    "Agent", "play_game", "play_many",
    "RandomAgent", "GreedyAgent", "LookaheadAgent", "LinearAgent", "REGISTRY",
]
