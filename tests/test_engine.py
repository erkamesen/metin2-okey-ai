"""Motorun kurallari dogru uyguladigini gosteren testler.

Her test tek bir kurali sorguluyor. Bir kural degisirse hangi testin
kirildigina bakip neyin degistigini okuyabilmelisin.
"""
from __future__ import annotations

import random

import pytest

from okey import DEFAULT_RULES, Okey, IllegalMove
from okey.scoring import GROUP, RUN_MIXED, RUN_SAME


@pytest.fixture(scope="module")
def okey():
    return Okey()


@pytest.fixture(scope="module")
def deck(okey):
    return okey.deck


def hand_of(okey, game, text):
    """Oyunun elini belirli kartlarla degistirir (test kurgusu icin).

    Kartlar desteden cikarilir ki "hem elde hem destede" gibi imkansiz bir
    durum olusmasin.
    """
    cards = sorted(okey.deck.parse_many(text))
    for card in cards:
        if card in game.deck:
            game.deck.remove(card)
    game.hand = cards
    game._refresh_over()
    return game


# ------------------------------------------------------------------- deste

def test_deck_is_24_unique_cards(deck):
    assert deck.size == 24
    assert deck.n_ranks == 8 and deck.n_colors == 3
    assert len(set(deck.all_cards())) == 24


def test_every_card_has_a_unique_label(deck):
    labels = [deck.label(card) for card in deck.all_cards()]
    assert len(set(labels)) == 24
    assert deck.label(deck.card(5, "kirmizi")) == "5k"
    assert deck.label(deck.card(1, "mavi")) == "1m"
    assert deck.label(deck.card(8, "sari")) == "8s"


def test_labels_round_trip(deck):
    for card in deck.all_cards():
        assert deck.parse(deck.label(card)) == card


def test_parse_rejects_nonsense(deck):
    with pytest.raises(ValueError):
        deck.parse("9k")
    with pytest.raises(ValueError):
        deck.parse("5x")


def test_parse_many_accepts_loose_text(deck):
    assert deck.parse_many("5k 6k, 7k") == [
        deck.card(5, "kirmizi"), deck.card(6, "kirmizi"), deck.card(7, "kirmizi")]


# --------------------------------------------------------------- puanlama

@pytest.mark.parametrize("text,kind,points", [
    # Ayni sayilar: tek kopya oldugu icin her zaman uc renk birden
    ("1k 1m 1s", GROUP, 20),
    ("5k 5m 5s", GROUP, 60),
    ("8k 8m 8s", GROUP, 90),
    # Ayni renk seriler
    ("1k 2k 3k", RUN_SAME, 50),
    ("4m 5m 6m", RUN_SAME, 80),
    ("6s 7s 8s", RUN_SAME, 100),
    # Karisik seriler
    ("1m 2s 3k", RUN_MIXED, 10),
    ("4m 5s 6k", RUN_MIXED, 40),
    ("6m 7s 8k", RUN_MIXED, 60),
    ("6m 7m 8k", RUN_MIXED, 60),      # ikisi ayni renk yetmiyor
])
def test_scoring_table_matches_the_game(okey, text, kind, points):
    triple = tuple(sorted(okey.deck.parse_many(text)))
    combo = okey.table.combo(triple)
    assert combo is not None, f"{text} gecerli olmaliydi"
    assert combo.kind == kind
    assert combo.points == points


@pytest.mark.parametrize("text", [
    "1k 2k 4k",      # ardisik degil
    "1k 3m 5s",      # aralikli
    "1k 1m 2s",      # ne grup ne seri
    "7k 8k 1m",      # 8'den sonra devam yok
])
def test_invalid_triples_are_not_in_the_table(okey, text):
    triple = tuple(sorted(okey.deck.parse_many(text)))
    assert not okey.table.is_valid(triple)
    assert okey.table.points(triple) == 0


def test_same_color_run_beats_mixed(okey):
    same = okey.table.points(tuple(sorted(okey.deck.parse_many("6k 7k 8k"))))
    mixed = okey.table.points(tuple(sorted(okey.deck.parse_many("6k 7k 8m"))))
    assert same == 100 and mixed == 60


def test_card_order_does_not_matter(okey):
    forward = tuple(sorted(okey.deck.parse_many("1k 2k 3k")))
    backward = tuple(sorted(okey.deck.parse_many("3k 2k 1k")))
    assert forward == backward
    assert okey.table.points(forward) == 50


def test_table_has_every_valid_triple(okey):
    counts = okey.table.summary()
    assert counts[GROUP] == 8                 # her sayidan bir grup
    assert counts[RUN_SAME] == 6 * 3          # 6 seri x 3 renk
    # Karisik seri: 6 baslangic x (3^3 renk dizilimi - 3 saf dizilim)
    assert counts[RUN_MIXED] == 6 * (27 - 3)
    assert len(okey.table) == 8 + 18 + 144


# ------------------------------------------------------------- tur baslangici

def test_round_starts_with_five_cards(okey):
    game = okey.new_game(seed=1)
    assert len(game.hand) == DEFAULT_RULES.hand_size == 5
    assert game.cards_left == 24 - 5
    assert game.score == 0
    assert not game.is_over


def test_hand_is_always_sorted(okey):
    game = okey.new_game(seed=7)
    assert game.hand == sorted(game.hand)
    while not game.is_over:
        game.apply(game.legal_actions()[-1])
        assert game.hand == sorted(game.hand)


def test_same_seed_gives_the_same_deal(okey):
    a, b = okey.new_game(seed=42), okey.new_game(seed=42)
    assert a.hand == b.hand
    assert a.deck == b.deck


# ------------------------------------------------------------------ hamleler

def test_discard_removes_a_card_and_draws_one(okey):
    game = okey.new_game(seed=3)
    before = list(game.hand)
    left_before = game.cards_left

    move = game.apply(0)
    assert move.kind == "sil"
    assert move.cards[0] == before[0]
    assert move.cards[0] in game.discarded
    assert len(game.hand) == 5              # el tekrar dolduruldu
    assert game.cards_left == left_before - 1
    assert move.points == 0


def test_discarded_cards_never_come_back(okey):
    game = okey.new_game(seed=5)
    thrown = []
    for _ in range(4):
        thrown.append(game.hand[0])
        game.apply(0)
    assert all(card not in game.hand for card in thrown)
    assert all(card not in game.deck for card in thrown)
    assert game.discarded == thrown


def test_meld_scores_and_refills_the_hand(okey):
    game = hand_of(okey, okey.new_game(seed=9), "1k 2k 3k 8m 8s")
    action = next(a for a in game.legal_actions() if not okey.is_discard(a))

    move = game.apply(action)
    assert move.kind == "uclu"
    assert move.points == 50                 # 1-2-3 ayni renk
    assert game.score == 50
    assert len(game.hand) == 5               # 2 kart kalmisti, 3 kart geldi
    assert len(move.drawn) == 3
    assert len(game.melds) == 1


def test_only_valid_melds_are_offered(okey):
    """Gecersiz uclu kurulamaz — oyun bunu maskeyle engeller."""
    game = hand_of(okey, okey.new_game(seed=11), "1k 2k 4k 6m 8s")
    meld_actions = [a for a in game.legal_actions() if not okey.is_discard(a)]
    assert meld_actions == []                # bu elde hicbir gecerli uclu yok

    game = hand_of(okey, okey.new_game(seed=11), "1k 2k 3k 6m 8s")
    meld_actions = [a for a in game.legal_actions() if not okey.is_discard(a)]
    assert len(meld_actions) == 1            # sadece 1k-2k-3k


def test_applying_an_illegal_action_raises(okey):
    game = hand_of(okey, okey.new_game(seed=13), "1k 2k 4k 6m 8s")
    illegal = next(a for a in range(okey.n_actions) if not game.is_legal(a))
    with pytest.raises(IllegalMove):
        game.apply(illegal)
    with pytest.raises(IllegalMove):
        game.apply(999)


def test_melding_takes_exactly_the_chosen_cards(okey):
    game = hand_of(okey, okey.new_game(seed=17), "3k 4k 5k 8m 8s")
    keep = {okey.deck.parse("8m"), okey.deck.parse("8s")}
    action = next(a for a in game.legal_actions() if not okey.is_discard(a))

    game.apply(action)
    assert keep.issubset(set(game.hand))     # dokunulmamis kartlar elde kaldi


# ------------------------------------------------------------- eylem uzayi

def test_action_space_is_five_discards_and_ten_melds(okey):
    assert okey.rules.hand_size == 5
    assert okey.n_melds == 10                # C(5,3)
    assert okey.n_actions == 15


def test_action_mask_matches_legal_actions(okey):
    game = okey.new_game(seed=19)
    while not game.is_over:
        mask = game.action_mask()
        assert game.legal_actions() == [i for i, ok in enumerate(mask) if ok]
        assert all(game.is_legal(a) for a in game.legal_actions())
        game.apply(game.legal_actions()[0])


def test_discards_are_blocked_when_the_deck_is_empty(okey):
    """Yerine kart gelmeyecekse kart silmenin anlami yok."""
    game = hand_of(okey, okey.new_game(seed=23), "1k 2k 3k 8m 8s")
    game.deck.clear()
    game._refresh_over()
    assert all(not okey.is_discard(a) for a in game.legal_actions())


# ------------------------------------------------------------- turun bitisi

def test_round_ends_when_no_move_is_left(okey):
    game = hand_of(okey, okey.new_game(seed=29), "1k 2k 4k 6m 8s")
    game.deck.clear()
    game._refresh_over()
    assert game.is_over
    assert game.legal_actions() == []


def test_round_continues_while_a_meld_is_possible(okey):
    game = hand_of(okey, okey.new_game(seed=31), "1k 2k 3k 4k 6m")
    game.deck.clear()
    game._refresh_over()
    assert not game.is_over
    game.apply(next(a for a in game.legal_actions() if not okey.is_discard(a)))
    assert game.is_over                      # elde 2 kart kaldi, uclu olmaz


def test_a_full_round_conserves_every_card(okey):
    game = okey.new_game(seed=37)
    while not game.is_over:
        game.apply(game.legal_actions()[0])
    used = sum(len(cards) for cards, _ in game.melds)
    seen = used + len(game.discarded) + len(game.hand) + game.cards_left
    assert seen == 24


def test_score_equals_the_sum_of_its_melds(okey):
    game = okey.new_game(seed=41)
    while not game.is_over:
        game.apply(game.legal_actions()[-1])
    assert game.score == sum(combo.points for _, combo in game.melds)


# --------------------------------------------------------------- kart sayma

def test_unseen_hides_the_deck_order(okey):
    """Ajan hangi kartlarin kaldigini bilebilir, hangi sirada geldigini bilemez."""
    game = okey.new_game(seed=43)
    unseen = game.unseen()
    assert unseen == tuple(sorted(unseen))
    assert set(unseen) == set(game.deck)


def test_unseen_shrinks_as_cards_appear(okey):
    game = okey.new_game(seed=47)
    assert len(game.unseen()) == 24 - 5
    assert not set(game.unseen()) & set(game.hand)
    game.apply(0)
    assert len(game.unseen()) == 24 - 6


# ------------------------------------------------------------------ sandik

@pytest.mark.parametrize("score,chest", [
    (0, "bronz"), (299, "bronz"), (300, "gumus"), (399, "gumus"),
    (400, "altin"), (1000, "altin"),
])
def test_chest_thresholds(score, chest):
    assert DEFAULT_RULES.chest_for(score) == chest


# ---------------------------------------------------------------- kopyalama

def test_copy_is_independent(okey):
    game = okey.new_game(seed=53)
    clone = game.copy()
    clone.apply(clone.legal_actions()[0])
    assert clone.move_no == game.move_no + 1
    assert clone.hand != game.hand or clone.cards_left != game.cards_left


def test_copy_keeps_the_same_position(okey):
    game = okey.new_game(seed=59)
    game.apply(game.legal_actions()[0])
    clone = game.copy()
    assert clone.hand == game.hand
    assert clone.deck == game.deck
    assert clone.score == game.score
    assert clone.legal_actions() == game.legal_actions()


# -------------------------------------------------------------- saglamlik

def test_random_play_never_breaks(okey):
    """Binlerce rastgele tur: hicbir hamle cokmemeli, puan negatif olmamali."""
    rng = random.Random(0)
    for seed in range(300):
        game = okey.new_game(seed=seed)
        guard = 0
        while not game.is_over and guard < 100:
            game.apply(rng.choice(game.legal_actions()))
            guard += 1
        assert game.is_over
        assert game.score >= 0
        assert len(game.hand) <= 5
