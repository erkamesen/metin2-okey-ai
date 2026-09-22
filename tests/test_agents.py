"""Referans oyuncularin dogru davrandigini gosteren testler.

Buradaki testler "ajan iyi oynuyor mu" degil, "ajan kurallara uyuyor ve
soyledigi seyi yapiyor mu" sorusunu sorguluyor. Ne kadar iyi oynadigi
`evaluate.py`'nin isi.
"""
from __future__ import annotations

import random

import pytest

from okey import Okey
from okey.agents import GreedyAgent, LookaheadAgent, RandomAgent, play_game


@pytest.fixture(scope="module")
def okey():
    return Okey()


def hand_of(okey, game, text):
    """Oyunun elini belirli kartlarla degistirir (test kurgusu icin)."""
    cards = sorted(okey.deck.parse_many(text))
    for card in cards:
        if card in game.deck:
            game.deck.remove(card)
    game.hand = cards
    game._refresh_over()
    return game


ALL_AGENTS = [RandomAgent, GreedyAgent, lambda: LookaheadAgent(rollouts=3)]


# --------------------------------------------------------- ortak davranis

@pytest.mark.parametrize("make_agent", ALL_AGENTS)
def test_agent_only_plays_legal_moves(okey, make_agent):
    agent = make_agent()
    for seed in range(8):
        game = okey.new_game(seed=seed)
        agent.reset()
        while not game.is_over:
            action = agent.act(game)
            assert game.is_legal(action), f"{agent.name} gecersiz hamle onerdi: {action}"
            game.apply(action)


@pytest.mark.parametrize("make_agent", ALL_AGENTS)
def test_agent_finishes_every_round(okey, make_agent):
    agent = make_agent()
    for seed in range(8):
        game = play_game(okey, agent, seed)
        assert game.is_over
        assert game.score >= 0


@pytest.mark.parametrize("make_agent", ALL_AGENTS)
def test_agent_is_reproducible(okey, make_agent):
    """Ayni seed + ayni ajan = ayni sonuc. Olcumun tekrarlanabilir olmasi sart."""
    first = play_game(okey, make_agent(), seed=11).score
    second = play_game(okey, make_agent(), seed=11).score
    assert first == second


# ------------------------------------------------------------- acgozlu

def test_greedy_takes_a_meld_when_one_exists(okey):
    game = hand_of(okey, okey.new_game(seed=1), "1k 2k 3k 8m 8s")
    action = GreedyAgent().act(game)
    assert not okey.is_discard(action)


def test_greedy_takes_the_highest_scoring_meld(okey):
    """Elde iki uclu var: 6-7-8 ayni renk (100) ve karisik 6-7-8 (60)."""
    game = hand_of(okey, okey.new_game(seed=2), "6k 7k 8k 7m 8s")
    action = GreedyAgent().act(game)
    slot = okey.meld_slot(action)
    triple = tuple(sorted(game.hand[i] for i in slot))
    assert okey.table.points(triple) == 100


def test_greedy_discards_the_deadest_card(okey):
    """Destede karsiligi kalmamis kart once gitmeli."""
    game = hand_of(okey, okey.new_game(seed=3), "1k 4m 6s 7s 2m")
    # 1k'yi iceren butun ucluleri imkansiz kil: 2 ve 3'leri, 1'leri destedan cikar
    dead = okey.deck.parse_many("1m 1s 2k 3k 2s 3s 3m")
    for card in dead:
        if card in game.deck:
            game.deck.remove(card)
    game._refresh_over()

    available = frozenset(game.hand) | frozenset(game.unseen())
    assert okey.table.best_use_of(okey.deck.parse("1k"), available) == 0

    action = GreedyAgent().act(game)
    assert okey.is_discard(action)
    assert game.hand[action] == okey.deck.parse("1k")


def test_greedy_beats_random_clearly(okey):
    """Ayni destelerde: acgozlu her turda rastgeleden iyi olmasa da acik ara onde."""
    seeds = range(60)
    greedy = [play_game(okey, GreedyAgent(), s).score for s in seeds]
    chance = [play_game(okey, RandomAgent(), s).score for s in seeds]
    assert sum(greedy) / len(greedy) > 2 * (sum(chance) / len(chance))


# -------------------------------------------------------- ileri-bakisli

def test_lookahead_does_not_peek_at_the_deck(okey):
    """Ajan destenin gercek sirasini gormemeli.

    Destenin sirasini degistirip (ayni kartlar, farkli sira) ajana tekrar
    soruyoruz. Sirayi okusaydi karari degisirdi; okumadigi icin ayni kaliyor.
    """
    game = hand_of(okey, okey.new_game(seed=5), "1k 2k 5m 7s 8s")
    agent = LookaheadAgent(rollouts=6, seed=0)
    first = agent.act(game)

    shuffled = game.copy()
    random.Random(99).shuffle(shuffled.deck)
    second = LookaheadAgent(rollouts=6, seed=0).act(shuffled)
    assert first == second


def test_lookahead_uses_the_same_decks_for_every_candidate(okey):
    """Ortak desteler: ayni ajan ayni durumda hep ayni cevabi vermeli."""
    game = okey.new_game(seed=7)
    answers = {LookaheadAgent(rollouts=5, seed=0).act(game) for _ in range(3)}
    assert len(answers) == 1


def test_lookahead_takes_a_guaranteed_high_meld(okey):
    """Deste bitmisken elde 100 puanlik uclu varsa baska secenek yok."""
    game = hand_of(okey, okey.new_game(seed=9), "6k 7k 8k 1m 2s")
    game.deck.clear()
    game._refresh_over()
    action = LookaheadAgent(rollouts=4).act(game)
    slot = okey.meld_slot(action)
    triple = tuple(sorted(game.hand[i] for i in slot))
    assert okey.table.points(triple) == 100


def test_with_deck_rejects_a_different_card_set(okey):
    from okey.engine import IllegalMove

    game = okey.new_game(seed=13)
    wrong = list(game.deck)[:-1]
    with pytest.raises(IllegalMove):
        game.with_deck(wrong)


def test_with_deck_keeps_the_position(okey):
    game = okey.new_game(seed=17)
    order = list(reversed(game.deck))
    clone = game.with_deck(order)
    assert clone.hand == game.hand
    assert clone.score == game.score
    assert sorted(clone.deck) == sorted(game.deck)
    assert clone.deck != game.deck        # sadece sira degisti
