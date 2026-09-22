"""Ozellik cikarimi ve ogrenen ajan icin testler.

Ogrenmenin dogru calistigini test etmek zor — "iyi ogrendi mi" sorusunun
kesin cevabi yok. Bunun yerine **sozlesmeyi** test ediyoruz: ozellikler
dogru hesaplaniyor mu, ajan gecerli oynuyor mu, agirliklar kaydedilip geri
yuklenebiliyor mu, ogrenme sinyali dogru yonde mi.
"""
from __future__ import annotations

import json

import pytest

from okey import Okey
from okey.agents import GreedyAgent, LinearAgent, play_game
from okey.features import FEATURE_NAMES, N_FEATURES, FeatureExtractor


@pytest.fixture(scope="module")
def okey():
    return Okey()


@pytest.fixture(scope="module")
def extractor(okey):
    return FeatureExtractor(okey.table, okey.rules)


def cards(okey, text):
    return sorted(okey.deck.parse_many(text))


def feature(extractor, vector, name):
    return vector[FEATURE_NAMES.index(name)]


def everything(okey, hand):
    """Elde + destede olan her sey (silinen yokmus gibi)."""
    return frozenset(hand) | frozenset(
        c for c in okey.deck.all_cards() if c not in hand)


# --------------------------------------------------------------- ozellikler

def test_vector_has_one_value_per_name(okey, extractor):
    hand = cards(okey, "1k 2k 3k")
    vector = extractor.extract(hand, everything(okey, hand), 10, 0)
    assert len(vector) == N_FEATURES == len(FEATURE_NAMES)


def test_values_stay_in_a_sane_range(okey, extractor):
    hand = cards(okey, "6k 7k 8k 1m 5s")
    vector = extractor.extract(hand, everything(okey, hand), 19, 0)
    assert all(0.0 <= value <= 1.5 for value in vector)


def test_ready_meld_is_seen(okey, extractor):
    """Elde kurulmaya hazir uclu varsa ozellik bunu gostermeli."""
    with_meld = cards(okey, "6k 7k 8k 1m 5s")        # 6-7-8 ayni renk = 100
    # Dikkat: hicbir uclu ICERMEYEN bir el secmek sanildigi kadar kolay degil.
    # "6k 7k 1m 5s 3s" bosuna gorunuyor ama 5s-6k-7k karisik serisi var (50).
    # Asagidaki elde 1,2,4,6,8 var: ne ardisik uclu ne de ayni sayidan uclu.
    without = cards(okey, "1k 2m 4m 6s 8s")
    ready_with = feature(extractor, extractor.extract(
        with_meld, everything(okey, with_meld), 19, 0), "hazir_uclu")
    ready_without = feature(extractor, extractor.extract(
        without, everything(okey, without), 19, 0), "hazir_uclu")
    assert ready_with == 1.0                          # 100/100
    assert ready_without == 0.0


def test_pair_value_reflects_what_it_waits_for(okey, extractor):
    """6k+7k, 8k'yi bekliyor: 100 puanlik uclu. 1k+2k ise 3k'yi: 50."""
    high = cards(okey, "6k 7k")
    low = cards(okey, "1k 2k")
    high_value = feature(extractor, extractor.extract(
        high, everything(okey, high), 19, 0), "en_iyi_ikili")
    low_value = feature(extractor, extractor.extract(
        low, everything(okey, low), 19, 0), "en_iyi_ikili")
    assert high_value == 1.0                          # 100/100
    assert low_value == 0.5                           # 50/100
    assert high_value > low_value


def test_pair_value_drops_when_the_partner_is_gone(okey, extractor):
    """Tamamlayici kartlar oyundan cikinca ikili degersizlesir."""
    hand = cards(okey, "6k 7k")
    full = feature(extractor, extractor.extract(
        hand, everything(okey, hand), 19, 0), "en_iyi_ikili")

    # 6-7-8 ve 5-6-7 serilerini imkansiz kil, geriye karisik seriler kalsin
    gone = set(okey.deck.parse_many("8k 5k"))
    available = frozenset(c for c in everything(okey, hand) if c not in gone)
    reduced = feature(extractor, extractor.extract(hand, available, 17, 0),
                      "en_iyi_ikili")
    assert reduced < full


def test_second_pair_must_not_share_cards(okey, extractor):
    """Ayni karti iki ucluye koyamazsin; ikinci ikili ayri kartlardan olmali."""
    hand = cards(okey, "6k 7k 1m 2m")        # iki ayri ikili
    vector = extractor.extract(hand, everything(okey, hand), 19, 0)
    assert feature(extractor, vector, "en_iyi_ikili") > 0
    assert feature(extractor, vector, "ikinci_ikili") > 0

    single = cards(okey, "6k 7k 8m")         # tek ikili ekseni
    vector = extractor.extract(single, everything(okey, single), 19, 0)
    assert feature(extractor, vector, "ikinci_ikili") == 0.0


def test_dead_cards_are_counted(okey, extractor):
    """Hicbir ucluye giremeyen kart sayisi."""
    hand = cards(okey, "1k 5m")
    # 1k'yi olduren kartlari cikar: 1'ler, 2'ler, 3'ler
    gone = set(okey.deck.parse_many("1m 1s 2k 2m 2s 3k 3m 3s"))
    available = frozenset(c for c in everything(okey, hand) if c not in gone)
    vector = extractor.extract(hand, available, 14, 0)
    assert feature(extractor, vector, "olu_kart") == 1 / okey.rules.hand_size
    assert feature(extractor, vector, "canlilik_min") == 0.0


def test_empty_hand_does_not_crash(okey, extractor):
    vector = extractor.extract([], frozenset(), 0, 8)
    assert len(vector) == N_FEATURES
    assert feature(extractor, vector, "eldeki_kart") == 0.0


# ------------------------------------------------------------------- ajan

def test_agent_plays_only_legal_moves(okey):
    agent = LinearAgent(okey, [0.1] * N_FEATURES)
    game = okey.new_game(seed=3)
    while not game.is_over:
        action = agent.act(game)
        assert game.is_legal(action)
        game.apply(action)


def test_agent_rejects_wrong_sized_weights(okey):
    with pytest.raises(ValueError):
        LinearAgent(okey, [0.0] * (N_FEATURES + 1))


def test_zero_weights_make_it_greedy_about_points(okey):
    """Agirliklar sifirken karar sadece hemen kazanilan puana bakar."""
    agent = LinearAgent(okey, [0.0] * N_FEATURES)
    game = okey.new_game(seed=1)
    action, _, _ = agent.evaluate(game)
    best_now = max(
        (points for _, points, _ in agent.candidates(game)), default=0)
    chosen = next(points for a, points, _ in agent.candidates(game) if a == action)
    assert chosen == best_now


def test_candidates_cover_every_legal_action(okey):
    agent = LinearAgent(okey)
    game = okey.new_game(seed=5)
    assert [c[0] for c in agent.candidates(game)] == game.legal_actions()


def test_candidates_do_not_disturb_the_game(okey):
    """Aday hesaplama oyunu degistirmemeli — kopyalamadan calisiyoruz."""
    agent = LinearAgent(okey)
    game = okey.new_game(seed=7)
    before = (list(game.hand), list(game.deck), game.score, game.move_no)
    list(agent.candidates(game))
    assert (list(game.hand), list(game.deck), game.score, game.move_no) == before


def test_immediate_points_and_value_share_a_scale(okey):
    """Birim uyumu: ham puan (0..100) ogrenilen degeri bastirmamali.

    Bu bir kez hata olmustu — puan olceklenmeden ekleniyordu ve ogrenilen
    deger karari hic etkilemiyordu. Test o hatanin geri gelmesini engelliyor.
    """
    agent = LinearAgent(okey, [0.0] * N_FEATURES, reward_scale=100.0)
    game = okey.new_game(seed=11)
    _, value, _ = agent.evaluate(game)
    assert value <= 1.5            # en iyi uclu 100 puan -> olcekli 1.0


def test_epsilon_makes_it_explore(okey):
    """Kesif orani 1 iken kararlar rastgele olmali."""
    always = LinearAgent(okey, [1.0] * N_FEATURES, epsilon=1.0, seed=1)
    game = okey.new_game(seed=13)
    choices = {always.act(game) for _ in range(30)}
    assert len(choices) > 1


# ------------------------------------------------------------------ kayit

def test_weights_survive_a_round_trip(okey, tmp_path):
    path = str(tmp_path / "w.json")
    weights = [0.1 * i for i in range(N_FEATURES)]
    LinearAgent(okey, weights).save(path, extra={"tur": 5})

    loaded = LinearAgent.load(okey, path)
    assert loaded.weights == weights
    payload = json.loads(open(path, encoding="utf-8").read())
    assert payload["ozellikler"] == list(FEATURE_NAMES)
    assert payload["tur"] == 5


def test_loading_mismatched_features_is_refused(okey, tmp_path):
    """Ozellikler degisirse eski agirliklar anlamsizdir; sessizce yuklenmemeli."""
    path = str(tmp_path / "eski.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"ozellikler": ["baska", "seyler"],
                   "agirliklar": [0.0] * N_FEATURES}, handle)
    with pytest.raises(ValueError):
        LinearAgent.load(okey, path)


def test_load_if_trained_returns_none_without_a_file(okey, tmp_path):
    assert LinearAgent.load_if_trained(okey, str(tmp_path / "yok.json")) is None


def test_explain_lists_every_feature(okey):
    text = LinearAgent(okey, [0.5] * N_FEATURES).explain()
    for name in FEATURE_NAMES:
        assert name in text


# --------------------------------------------------------------- ogrenme

def test_a_short_training_run_improves_on_random_weights(okey):
    """Kisa bir egitim, egitimsiz halinden iyi olmali.

    Cok kisa oldugu icin acgozluyu yenmesini beklemiyoruz; sadece ogrenme
    sinyalinin dogru yonde oldugunu goruyoruz.
    """
    from train import train
    from okey.env import RewardConfig

    agent, _ = train(okey, episodes=400, alpha=0.05, epsilon_start=0.3,
                     epsilon_end=0.05, eval_every=0, eval_games=0,
                     reward=RewardConfig(), seed=1)
    seeds = range(800_000, 800_060)
    trained = sum(play_game(okey, agent, s).score for s in seeds)
    untrained = sum(
        play_game(okey, LinearAgent(okey, [-1.0] * N_FEATURES), s).score for s in seeds)
    assert trained > untrained


def test_training_changes_the_weights(okey):
    from train import train
    from okey.env import RewardConfig

    agent, _ = train(okey, episodes=200, alpha=0.05, epsilon_start=0.2,
                     epsilon_end=0.05, eval_every=0, eval_games=0,
                     reward=RewardConfig(), seed=2)
    assert any(abs(w) > 1e-6 for w in agent.weights)
