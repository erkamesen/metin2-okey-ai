"""RL ortaminin sozunu tuttugunu gosteren testler.

Ortam yanlissa ajan yanlis seyi ogrenir ve bunu anlamak cok zor olur —
ajan "calisiyor" gibi gorunur, sadece kotu oynar. Bu yuzden ortamin
sozlesmesini tek tek sinamak onemli.
"""
from __future__ import annotations

import random

import pytest

from okey import Okey
from okey.env import OkeyEnv, RewardConfig


@pytest.fixture(scope="module")
def okey():
    return Okey()


@pytest.fixture
def env(okey):
    return OkeyEnv(okey)


def play_random(env: OkeyEnv, seed: int = 0, rng_seed: int = 0):
    """Bir turu rastgele oynatir; (odul toplami, adim sayisi) dondurur."""
    rng = random.Random(rng_seed)
    env.reset(seed=seed)
    total, steps = 0.0, 0
    while True:
        _, reward, done, _ = env.step(rng.choice(env.legal_actions()))
        total += reward
        steps += 1
        if done:
            return total, steps


# ----------------------------------------------------------------- sozlesme

def test_reset_returns_a_full_observation(env):
    observation = env.reset(seed=1)
    assert len(observation) == env.observation_size == 52
    assert all(isinstance(value, float) for value in observation)


def test_step_returns_four_things(env):
    env.reset(seed=1)
    result = env.step(env.legal_actions()[0])
    assert len(result) == 4
    observation, reward, done, info = result
    assert len(observation) == env.observation_size
    assert isinstance(reward, float)
    assert isinstance(done, bool)
    assert "puan" in info


def test_step_before_reset_is_refused(okey):
    with pytest.raises(RuntimeError):
        OkeyEnv(okey).step(0)


def test_reset_starts_a_fresh_round(env):
    env.reset(seed=3)
    while True:
        _, _, done, _ = env.step(env.legal_actions()[0])
        if done:
            break
    assert env.score > 0
    env.reset(seed=3)
    assert env.score == 0


def test_same_seed_gives_the_same_episode(env):
    first = play_random(env, seed=5)
    second = play_random(env, seed=5)
    assert first == second


# ------------------------------------------------------------------ gozlem

def test_observation_marks_the_hand_and_the_deck(env, okey):
    env.reset(seed=7)
    observation = env.observe()
    size = env.deck_size
    for card in env.game.hand:
        assert observation[card] == 1.0
    for card in env.game.deck:
        assert observation[size + card] == 1.0


def test_a_card_is_never_in_both_places(env):
    """Bir kart ya elde ya destede olabilir, ikisi birden olamaz."""
    env.reset(seed=11)
    size = env.deck_size
    for _ in range(6):
        observation = env.observe()
        assert all(not (observation[c] and observation[size + c]) for c in range(size))
        if env.game.is_over:
            break
        env.step(env.legal_actions()[0])


def test_gone_cards_are_zero_in_both_places(env, okey):
    """Silinen kart artik ne elde ne destede — ayri bir alan gerekmiyor."""
    env.reset(seed=13)
    discard = next(a for a in env.legal_actions() if okey.is_discard(a))
    card = env.game.hand[discard]
    env.step(discard)

    observation = env.observe()
    assert observation[card] == 0.0
    assert observation[env.deck_size + card] == 0.0


def test_observation_never_leaks_the_deck_order(env):
    """Gozlem sadece 'hangi kartlar kaldi' der, 'hangi sirada' demez.

    Destenin sirasini degistirip gozlemi tekrar aliyoruz: ayni cikmali.
    Ciksaydi ajan hile yapabilirdi.
    """
    env.reset(seed=17)
    before = env.observe()
    random.Random(99).shuffle(env.game.deck)
    assert env.observe() == before


def test_scalars_stay_between_zero_and_one(env):
    env.reset(seed=19)
    while True:
        observation = env.observe()
        assert all(0.0 <= value <= 1.0 for value in observation[-4:])
        if env.game.is_over:
            break
        env.step(env.legal_actions()[-1])


# ------------------------------------------------------------------- maske

def test_mask_matches_the_engine(env):
    env.reset(seed=23)
    while not env.game.is_over:
        mask = env.action_mask()
        assert len(mask) == env.n_actions
        assert env.legal_actions() == [i for i, ok in enumerate(mask) if ok]
        env.step(env.legal_actions()[0])


def test_mask_is_all_false_when_the_round_ends(env):
    env.reset(seed=29)
    while True:
        _, _, done, _ = env.step(env.legal_actions()[0])
        if done:
            break
    assert not any(env.action_mask())


# -------------------------------------------------------------------- odul

def test_plain_reward_sums_to_the_round_score(env):
    """Sade odulde toplam odul = turun puani. Ajanin en yuksege cikardigi sey,
    oyunun gercek amaciyla birebir ayni."""
    for seed in range(6):
        total, _ = play_random(env, seed=seed)
        assert total == env.score


def test_reward_is_the_points_of_that_move(env, okey):
    env.reset(seed=31)
    before = env.score
    action = env.legal_actions()[0]
    _, reward, _, info = env.step(action)
    assert reward == info["puan"] - before


def test_discard_earns_nothing(env, okey):
    env.reset(seed=37)
    discard = next(a for a in env.legal_actions() if okey.is_discard(a))
    _, reward, _, _ = env.step(discard)
    assert reward == 0.0


def test_leftover_penalty_only_lands_at_the_end(okey):
    env = OkeyEnv(okey, reward=RewardConfig(leftover_penalty=5.0))
    env.reset(seed=41)
    rewards = []
    while True:
        _, reward, done, _ = env.step(env.legal_actions()[0])
        rewards.append(reward)
        if done:
            break
    plain = OkeyEnv(okey)
    plain.reset(seed=41)
    plain_rewards = []
    while True:
        _, reward, done, _ = plain.step(plain.legal_actions()[0])
        plain_rewards.append(reward)
        if done:
            break

    assert rewards[:-1] == plain_rewards[:-1]          # ara adimlar ayni
    assert rewards[-1] == plain_rewards[-1] - 5.0 * len(env.game.hand)


def test_gold_bonus_changes_what_is_optimised(okey):
    """Bonus turun puanini degistirmez, sadece odulu degistirir.

    Ogrenilecek nokta: ajan puani degil **odulu** en yuksege cikarir. Ikisi
    ayni sey olmak zorunda degil.
    """
    config = RewardConfig(gold_bonus=100.0, gold_threshold=0)   # her tur alsin
    env = OkeyEnv(okey, reward=config)
    total, _ = play_random(env, seed=43)
    assert total == env.score + 100.0

    plain = OkeyEnv(okey)
    plain_total, _ = play_random(plain, seed=43)
    assert plain_total == plain.score
    assert env.score == plain.score                    # oyun ayni oynandi


def test_plain_config_is_the_default(env):
    assert env.reward_config.is_plain
    assert RewardConfig(leftover_penalty=1.0).is_plain is False
    assert RewardConfig(gold_bonus=1.0).is_plain is False


# ------------------------------------------------------------- aciklamalar

def test_describe_observation_accounts_for_every_card(env):
    env.reset(seed=47)
    env.step(env.legal_actions()[0])
    text = env.describe_observation()
    counts = [int(part.split(")")[0]) for part in text.split("(")[1:4]]
    assert sum(counts) == env.deck_size      # el + destede + gitmis = 24
