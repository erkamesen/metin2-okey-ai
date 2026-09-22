"""Motor, puanlama ve solver icin temel testler."""
from __future__ import annotations

import random
import pytest

from okey.cards import Card, CardCodec
from okey.engine import (
    COMPLETE, DISCARD, PLACE, Action, InvalidCard, InvalidMove, OkeyGame,
)
from okey.rules import load_rules
from okey.scoring import GROUP, INVALID, RUN_MIXED, RUN_SAME, classify, score_combo
from okey.solver import Solver, SolverConfig, play_greedy


@pytest.fixture(scope="module")
def rules():
    return load_rules("config/rules.yaml")


def live_game(rules, hand=(), seed=1):
    """Elle kart girilen bir tur baslatir."""
    game = OkeyGame(rules, seed=seed, live=True)
    if hand:
        game.provide_cards(list(hand))
    return game


# ---------------------------------------------------------------- puanlama

def test_group_scoring(rules):
    combo = score_combo([Card(7, "red"), Card(7, "blue"), Card(7, "green")], rules)
    assert combo.kind == GROUP
    assert combo.points == rules.group_scores[7] == 80


def test_same_color_run_beats_mixed(rules):
    same = score_combo([Card(6, "red"), Card(7, "red"), Card(8, "red")], rules)
    mixed = score_combo([Card(6, "red"), Card(7, "blue"), Card(8, "red")], rules)
    assert same.kind == RUN_SAME and same.points == 100
    assert mixed.kind == RUN_MIXED and mixed.points == 60


def test_run_order_does_not_matter(rules):
    forward = score_combo([Card(1, "red"), Card(2, "red"), Card(3, "red")], rules)
    backward = score_combo([Card(3, "red"), Card(2, "red"), Card(1, "red")], rules)
    assert forward == backward


@pytest.mark.parametrize("cards", [
    [Card(1, "red"), Card(2, "red"), Card(4, "red")],     # ardisik degil
    [Card(1, "red"), Card(1, "red"), Card(2, "red")],     # ne grup ne seri
    [Card(3, "red"), Card(5, "blue"), Card(8, "green")],  # alakasiz
])
def test_invalid_combinations_score_zero(rules, cards):
    combo = score_combo(cards, rules)
    assert combo.kind == INVALID
    assert combo.points == 0


def test_run_outside_table_is_invalid(rules):
    assert classify([Card(6, "red"), Card(7, "red"), Card(8, "red")]).kind == RUN_SAME
    assert classify([Card(2, "red"), Card(4, "red"), Card(6, "red")]).kind == INVALID


# ----------------------------------------------------- sirali uclu modeli

def test_slot_count_follows_deck(rules):
    assert rules.deck_size == 24
    assert rules.slots == rules.deck_size // rules.combo_size == 8


def test_only_the_active_combo_accepts_cards(rules):
    """Onundeki uclu dolmadan bir sonrakine kart konamaz."""
    game = live_game(rules, [Card(1, "red"), Card(2, "red"), Card(3, "red"),
                             Card(4, "red"), Card(5, "red")])
    assert game.active_slot_index == 0
    assert game.is_legal(Action(PLACE, 0, 0))
    assert game.is_legal(Action(PLACE, 0))          # slot verilmezse acik uclu
    assert not game.is_legal(Action(PLACE, 0, 1))
    assert not game.is_legal(Action(PLACE, 0, 7))


def test_combo_is_not_scored_until_it_is_completed(rules):
    """Uclu dolunca kendiliginden puanlanmaz; TAMAMLA ile kilitlenir."""
    game = live_game(rules, [Card(1, "red"), Card(2, "red"), Card(3, "red"),
                             Card(4, "red"), Card(5, "red")])
    for _ in range(3):
        game.apply(Action(PLACE, 0))
    assert game.slots[0].is_full
    assert not game.slots[0].is_locked
    assert game.total_score == 0
    assert game.can_complete
    assert game.pending_combo.points == 50
    assert game.active_slot_index == 0          # hala ayni uclu acik

    game.complete()
    assert game.slots[0].is_locked
    assert game.slots[0].result.points == rules.run_same_color_scores[1] == 50
    assert game.total_score == 50
    assert game.active_slot_index == 1
    assert not game.can_complete


def test_placed_cards_can_be_taken_back_before_completing(rules):
    game = live_game(rules, [Card(1, "red"), Card(5, "blue"), Card(8, "green"),
                             Card(4, "red"), Card(2, "red")])
    game.apply(Action(PLACE, 1))                # 5b ucluye
    assert game.staged == [Card(5, "blue")]
    assert len(game.hand) == 4

    back = game.take_back(0)
    assert back == Card(5, "blue")
    assert game.staged == []
    assert Card(5, "blue") in game.hand
    assert len(game.hand) == 5


def test_take_back_is_refused_after_completing(rules):
    game = live_game(rules, [Card(1, "red"), Card(2, "red"), Card(3, "red"),
                             Card(4, "red"), Card(5, "red")])
    for _ in range(3):
        game.apply(Action(PLACE, 0))
    game.complete()
    with pytest.raises(InvalidMove):
        game.take_back(0)


def test_combos_possible_drops_by_one_per_three_discards(rules):
    game = live_game(rules, [Card(1, "red"), Card(2, "red"), Card(3, "red"),
                             Card(4, "red"), Card(5, "red")])
    before = game.combos_possible
    for _ in range(3):
        game.apply(Action(DISCARD, 0))
        game.request_draw()
        game.provide_cards([next(iter(game.unseen))])
    assert game.combos_possible == before - 1


def test_placing_does_not_cost_a_combo(rules):
    game = live_game(rules, [Card(1, "red"), Card(2, "red"), Card(3, "red"),
                             Card(4, "red"), Card(5, "red")])
    before = game.combos_possible
    game.apply(Action(PLACE, 0))
    assert game.combos_possible == before


# ------------------------------------------------------------- kart giris

def test_round_starts_by_asking_for_cards(rules):
    game = OkeyGame(rules, seed=1, live=True)
    assert game.phase == "awaiting_cards"
    assert game.pending_draws == rules.hand_size
    assert game.legal_actions() == []
    assert game.cards_left == rules.deck_size


def test_entered_cards_leave_the_unseen_pool(rules):
    game = OkeyGame(rules, seed=1, live=True)
    game.provide_cards([Card(7, "red"), Card(7, "blue")])
    assert game.cards_left == rules.deck_size - 2
    assert Card(7, "red") not in game.unseen
    assert game.pending_draws == rules.hand_size - 2
    assert game.phase == "awaiting_cards"          # hala 3 kart bekliyor


def test_cannot_enter_a_card_that_is_already_gone(rules):
    game = OkeyGame(rules, seed=1, live=True)
    game.provide_cards([Card(7, "red")])
    with pytest.raises(InvalidCard):
        game.provide_cards([Card(7, "red")])
    assert game.pending_draws == rules.hand_size - 1   # durum bozulmadi
    assert len(game.hand) == 1


def test_partial_entry_rolls_back_completely(rules):
    game = OkeyGame(rules, seed=1, live=True)
    game.provide_cards([Card(7, "red")])
    with pytest.raises(InvalidCard):
        game.provide_cards([Card(1, "blue"), Card(7, "red")])   # ikincisi gecersiz
    assert len(game.hand) == 1
    assert Card(1, "blue") in game.unseen


def test_cannot_enter_more_than_requested(rules):
    game = OkeyGame(rules, seed=1, live=True)
    with pytest.raises(InvalidCard):
        game.provide_cards([Card(r, "red") for r in range(1, 8)])


def test_discarding_one_card_lets_you_draw_one(rules):
    game = live_game(rules, [Card(1, "red"), Card(2, "red"), Card(3, "blue"),
                             Card(4, "red"), Card(5, "red")])
    assert game.draw_count == 0                 # el dolu, cekilecek yer yok
    game.apply(Action(DISCARD, 2))
    assert len(game.hand) == 4
    assert game.draw_count == 1

    game.request_draw()
    assert game.pending_draws == 1
    assert game.phase == "awaiting_cards"
    game.provide_cards([Card(8, "green")])
    assert game.phase == "playing"
    assert len(game.hand) == rules.hand_size


def test_discarding_two_cards_lets_you_draw_two(rules):
    game = live_game(rules, [Card(1, "red"), Card(2, "red"), Card(3, "blue"),
                             Card(4, "red"), Card(5, "red")])
    game.apply(Action(DISCARD, 0))
    game.apply(Action(DISCARD, 0))
    assert len(game.hand) == 3
    assert game.draw_count == 2


def test_placed_cards_do_not_earn_a_draw(rules):
    """Ucluye konan kartin yeri belli; tamamlanmadan yerine kart gelmez."""
    game = live_game(rules, [Card(1, "red"), Card(2, "red"), Card(3, "red"),
                             Card(4, "red"), Card(5, "red")])
    game.apply(Action(PLACE, 0))
    assert len(game.hand) == 4
    assert game.draw_count == 0                 # 5 - 4(el) - 1(masada)
    game.apply(Action(PLACE, 0))
    assert game.draw_count == 0
    with pytest.raises(InvalidMove):
        game.provide_cards([Card(8, "green")])


def test_completing_a_combo_lets_you_draw_three(rules):
    """Uclu tamamlaninca elde 2 kart kalir, desteden 3 kart gelir."""
    game = live_game(rules, [Card(1, "red"), Card(2, "red"), Card(3, "red"),
                             Card(4, "red"), Card(5, "red")])
    for _ in range(3):
        game.apply(Action(PLACE, 0))
    assert game.draw_count == 0                 # once tamamla
    game.complete()
    assert len(game.hand) == 2
    assert game.draw_count == 3

    game.request_draw()
    game.provide_cards([Card(8, "green"), Card(7, "blue"), Card(6, "green")])
    assert len(game.hand) == rules.hand_size


def test_no_actions_when_hand_is_empty(rules):
    game = OkeyGame(rules, seed=1, live=True)
    assert game.legal_actions() == []
    assert not game.is_legal(Action(PLACE, 0, 0))


def test_stop_waiting_ends_the_deck(rules):
    game = live_game(rules, [Card(1, "red"), Card(2, "red"), Card(3, "red"),
                             Card(4, "red"), Card(5, "red")])
    game.apply(Action(DISCARD, 4))
    game.stop_waiting()
    assert game.cards_left == 0
    assert game.pending_draws == 0
    assert game.phase == "playing"


def test_round_ends_when_active_combo_cannot_be_completed(rules):
    game = live_game(rules, [Card(1, "red"), Card(2, "red"), Card(3, "red"),
                             Card(4, "red"), Card(5, "red")])
    game.stop_waiting()                      # deste bitti
    for _ in range(3):
        game.apply(Action(PLACE, 0))
    game.complete()
    assert game.total_score == 50
    assert game.is_over                      # elde 2 kart kaldi, uclu olmaz


# ------------------------------------------------------------- geri alma

def test_undo_reverts_a_move(rules):
    game = live_game(rules, [Card(1, "red"), Card(2, "red"), Card(3, "red"),
                             Card(4, "red"), Card(5, "red")])
    game.apply(Action(PLACE, 0, None))
    assert len(game.slots[0].cards) == 1
    assert game.undo()
    assert game.slots[0].cards == []
    assert game.hand[0] == Card(1, "red")
    assert game.pending_draws == 0
    assert game.move_no == 0


def test_undo_reverts_a_card_entry(rules):
    """Yanlis kart girilirse geri alinabilmeli."""
    game = OkeyGame(rules, seed=1, live=True)
    game.provide_cards([Card(7, "red"), Card(2, "blue")])
    assert game.undo()
    assert game.hand == []
    assert game.pending_draws == rules.hand_size
    assert Card(7, "red") in game.unseen


def test_undo_returns_false_when_nothing_to_undo(rules):
    assert OkeyGame(rules, seed=1, live=True).undo() is False


# ------------------------------------------------------------------ kart

def test_card_codec_roundtrip(rules):
    codec = CardCodec(rules.colors)
    for card in (Card(7, "red"), Card(1, "blue"), Card(8, "green")):
        assert codec.parse(codec.label(card)) == card


def test_card_codec_parses_free_text(rules):
    codec = CardCodec(rules.colors)
    assert codec.parse_many("7r 4b, 1g") == [Card(7, "red"), Card(4, "blue"), Card(1, "green")]
    with pytest.raises(ValueError):
        codec.parse("7x")


def test_card_codec_keeps_codes_unique():
    codec = CardCodec(["blue", "black", "red"])
    assert len(set(codec.to_code.values())) == 3
    assert codec.parse(codec.label(Card(3, "black"))) == Card(3, "black")


# ---------------------------------------------------------------- solver

def test_card_conservation(rules):
    game = play_greedy(OkeyGame(rules, seed=7, live=False), Solver(rules))
    seen = (game.cards_left + len(game.hand) + len(game.discards)
            + sum(len(s.cards) for s in game.slots))
    assert seen == rules.deck_size


def test_seed_is_reproducible(rules):
    a = play_greedy(OkeyGame(rules, seed=99, live=False), Solver(rules))
    b = play_greedy(OkeyGame(rules, seed=99, live=False), Solver(rules))
    assert a.total_score == b.total_score


def test_solver_does_not_see_the_next_card(rules):
    """Degerlendirme kopyasi kart cekmemeli; aksi halde solver hile yapar."""
    game = OkeyGame(rules, seed=3, live=False)
    game.open_deck()
    before = list(game.deck)
    Solver(rules).evaluate_actions(game)
    assert game.deck == before
    assert len(game.hand) == rules.hand_size


def test_solver_takes_the_only_scoring_move(rules):
    game = live_game(rules, [Card(8, "red")])
    game.slots[0].cards = [Card(8, "blue"), Card(8, "green")]
    game.stop_waiting()
    move = Solver(rules).best_move(game)
    assert move.type == PLACE and game.hand[move.card_index] == Card(8, "red")


def test_solver_avoids_wasting_the_active_combo(rules):
    """Tamamlanabilir ucluye dogru karti koymali."""
    game = live_game(rules, [Card(7, "red"), Card(1, "green")])
    game.slots[0].cards = [Card(6, "red"), Card(8, "red")]   # 7r ile 100 puan
    game.stop_waiting()
    move = Solver(rules).best_move(game)
    assert move.type == PLACE
    assert game.hand[move.card_index] == Card(7, "red")


def test_solver_beats_random(rules):
    import random

    solver_scores = [play_greedy(OkeyGame(rules, seed=s, live=False), Solver(rules)).total_score
                     for s in range(12)]
    random_scores = []
    for seed in range(12):
        game = OkeyGame(rules, seed=seed, live=False)
        game.open_deck()
        rng = random.Random(seed)
        while not game.is_over:
            game.apply(rng.choice(game.legal_actions()))
        random_scores.append(game.total_score)

    assert sum(solver_scores) / 12 > sum(random_scores) / 12 * 1.5


def test_rollout_solver_runs_in_live_mode(rules):
    """Canli modda deste sirasi bilinmez; rollout havuzu karistirarak calisir."""
    solver = Solver(rules, SolverConfig(rollouts=3, rollout_seed=1))
    game = live_game(rules, [Card(1, "red"), Card(5, "blue"), Card(7, "green"),
                             Card(2, "red"), Card(8, "blue")])
    assert game.is_legal(solver.best_move(game))


# ------------------------------------------------------------------ plan

def test_plan_is_short_and_stays_on_the_active_combo(rules):
    game = live_game(rules, [Card(1, "red"), Card(5, "blue"), Card(7, "green"),
                             Card(2, "red"), Card(8, "blue")])
    actions = Solver(rules).plan(game)
    assert 1 <= len(actions) <= rules.combo_size
    assert all(a.slot_index in (None, 0) for a in actions if a.type == PLACE)


def test_plan_never_chains_discards(rules):
    """Kart atinca yerine yeni kart gelir; onu gormeden ikinci kart atilmaz."""
    game = live_game(rules, [Card(1, "red"), Card(4, "blue"), Card(7, "green"),
                             Card(2, "green"), Card(8, "blue")])
    actions = Solver(rules).plan(game)
    assert sum(1 for a in actions if a.type == DISCARD) <= 1
    if actions[0].type == DISCARD:
        assert len(actions) == 1


def test_plan_completes_a_combo_it_can_finish_now(rules):
    game = live_game(rules, [Card(7, "red"), Card(8, "red"), Card(1, "green"),
                             Card(4, "blue"), Card(2, "green")])
    game.slots[0].cards = [Card(6, "red")]        # 6r + 7r + 8r = 100
    actions = Solver(rules).plan(game)
    assert [a.type for a in actions] == [PLACE, PLACE, COMPLETE]
    for action in actions:
        game.apply(action)
    assert game.slots[0].result.points == 100
    assert game.total_score == 100


def test_rollouts_survive_a_nearly_empty_deck(rules):
    """Tur sonunda rollout kopyasi ana oyunun hamlelerini gecersiz kilmamali.

    Kopya kurulur kurulmaz kart cekseydi, kisa bir el doldurulurken havuz
    tukeniyor ve ana oyunda gecerli olan "kart at" hamlesi kopyada
    gecersizlesiyordu (ValueError ile cokuyordu).
    """
    game = live_game(rules, [Card(1, "red"), Card(5, "blue"), Card(8, "green"),
                             Card(2, "red"), Card(7, "blue")])
    # Destede sadece iki kart biraksin
    keep = list(game.unseen)[:2]
    game.unseen = {card: 1 for card in keep}
    assert game.cards_left == 2
    assert any(a.type == DISCARD for a in game.legal_actions())

    solver = Solver(rules, SolverConfig(rollouts=4, rollout_candidates=0, rollout_seed=1))
    actions = solver.plan(game)          # cokmemeli
    assert actions and all(game.is_legal(actions[0]) for _ in [0])


def test_rollout_continuation_keeps_the_parent_position(rules):
    """Kopya, hamle yapilmadan once ana oyunla ayni elde ve havuzda olmali."""
    from okey.solver import simulated_continuation

    game = live_game(rules, [Card(1, "red"), Card(5, "blue"), Card(8, "green"),
                             Card(4, "red"), Card(2, "green")])
    sim = simulated_continuation(game, random.Random(1))
    assert sim.hand == game.hand
    assert sim.cards_left == game.cards_left
    assert sim.pending_draws == 0

    sim.apply(Action(PLACE, 0))          # kart koymak cekme hakki kazandirmaz
    assert len(sim.hand) == 4
    assert len(sim.staged) == 1

    sim.apply(Action(DISCARD, 0))        # kart atmak kazandirir, yerine gelir
    assert len(sim.hand) == 4
    assert sim.cards_left == game.cards_left - 1


def test_rollouts_do_not_throw_away_the_completing_card(rules):
    """100 puanlik ucluyu tamamlayan kart ne atilmali ne de uclu bozulmali.

    Karti hemen oynamak sart degil: elde tutup sonraki hamlede oynamak da ayni
    100 puani veriyor. Test bu yuzden hamlenin tam yerine, harcanmamasini
    dogruluyor.
    """
    game = live_game(rules, [Card(7, "red"), Card(1, "green"), Card(4, "blue"),
                             Card(2, "green"), Card(5, "blue")])
    game.slots[0].cards = [Card(6, "red"), Card(8, "red")]
    solver = Solver(rules, SolverConfig(rollouts=8, rollout_candidates=0, rollout_seed=1))
    move = solver.best_move(game)
    chosen = game.hand[move.card_index]
    if move.type == PLACE:
        assert chosen == Card(7, "red")     # baska kart ucluyu 0 puana dusururdu
    else:
        assert chosen != Card(7, "red")     # tamamlayan karti atmak olmaz


def test_rollouts_complete_the_combo_when_it_is_the_last_chance(rules):
    """Deste bittiginde tamamlayan karti oynamaktan baska secenek yok."""
    game = live_game(rules, [Card(7, "red"), Card(1, "green"), Card(4, "blue")])
    game.slots[0].cards = [Card(6, "red"), Card(8, "red")]
    game.stop_waiting()                     # destede kart kalmadi -> atma yok
    solver = Solver(rules, SolverConfig(rollouts=8, rollout_candidates=0, rollout_seed=1))
    move = solver.best_move(game)
    assert move.type == PLACE
    assert game.hand[move.card_index] == Card(7, "red")
    game.apply(move)
    game.complete()
    assert game.slots[0].result.points == 100


# ----------------------------------------------- tamamlayan kartlar

def test_completions_are_empty_until_two_cards_are_placed(rules):
    game = live_game(rules, [Card(6, "blue"), Card(8, "blue"), Card(1, "red"),
                             Card(3, "green"), Card(5, "red")])
    solver = Solver(rules)
    assert solver.completions(game) == []          # bos uclu
    game.apply(Action(PLACE, 0, None))
    assert solver.completions(game) == []          # tek kart


def test_completions_rank_the_best_card_first(rules):
    game = live_game(rules, [Card(1, "red"), Card(3, "green"), Card(5, "red")])
    game.slots[0].cards = [Card(6, "blue"), Card(8, "blue")]
    rows = Solver(rules).completions(game)
    assert rows[0] == {"rank": 7, "color": "blue", "points": 100,
                       "remaining": 1, "in_hand": False}
    assert {r["color"] for r in rows} == {"blue", "red", "green"}
    assert all(r["points"] == 60 for r in rows[1:])   # farkli renk serisi


def test_completions_mark_a_card_already_in_hand(rules):
    game = live_game(rules, [Card(7, "blue"), Card(1, "red"), Card(3, "green")])
    game.slots[0].cards = [Card(6, "blue"), Card(8, "blue")]
    rows = Solver(rules).completions(game)
    best = rows[0]
    assert best["in_hand"] is True and best["points"] == 100


def test_completions_drop_cards_that_are_gone(rules):
    game = live_game(rules, [Card(1, "red"), Card(3, "green"), Card(5, "red")])
    game.slots[0].cards = [Card(6, "blue"), Card(8, "blue")]
    for color in ("blue", "red", "green"):
        game.unseen.pop(Card(7, color), None)
    assert Solver(rules).completions(game) == []


def test_completions_for_a_dead_combo_are_empty(rules):
    game = live_game(rules, [Card(1, "red"), Card(3, "green"), Card(5, "red")])
    game.slots[0].cards = [Card(1, "blue"), Card(5, "green")]   # hicbir uclu olmaz
    assert Solver(rules).completions(game) == []
