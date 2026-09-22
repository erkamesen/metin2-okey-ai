"""Canli danisman akisi, CSV loglama ve LLM cevap ayristirma testleri."""
from __future__ import annotations

import csv

import pytest

from okey.agents.base import LLM, SOLVER, Advice, annotate_plan
from okey.agents.hybrid import HybridAgent, SolverAgent
from okey.agents.ollama_agent import AgentError, extract_json
from okey.cards import Card
from okey.engine import DISCARD, PLACE, Action, OkeyGame
from okey.logbook import CsvLogger
from okey.rules import load_rules
from okey.session import GameSession
from okey.solver import Solver

HAND = [Card(1, "red"), Card(2, "red"), Card(3, "red"), Card(5, "blue"), Card(8, "green")]


@pytest.fixture(scope="module")
def rules():
    return load_rules("config/rules.yaml")


@pytest.fixture
def logger(tmp_path):
    return CsvLogger(str(tmp_path / "stages.csv"), str(tmp_path / "games.csv"))


@pytest.fixture
def session(rules, logger):
    return GameSession(rules, SolverAgent(rules), logger, live=True)


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def feed(session, cards):
    return session.provide_cards(list(cards))


# ------------------------------------------------------------- canli akis

def test_round_opens_by_asking_for_cards(session, rules):
    state = session.new_game(seed=1)
    assert state["phase"] == "awaiting_cards"
    assert state["pending_draws"] == rules.hand_size
    assert state["hand"] == []


def test_advice_is_blocked_until_cards_are_entered(session):
    session.new_game(seed=1)
    result = session.get_advice()
    assert result["advice"] is None
    assert "kart gir" in result["error"]


def test_full_loop_enter_advise_apply(session):
    session.new_game(seed=1)
    feed(session, HAND)

    advice = session.get_advice(refresh=True)
    assert advice["error"] is None
    steps = advice["advice"]["steps"]
    assert steps and all(s["type"] in ("place", "discard", "complete") for s in steps)
    # TAMAMLA adiminda kart yoktur, digerlerinde olmali
    assert all(s["card_label"] for s in steps if s["type"] != "complete")
    if steps[-1]["type"] == "complete":
        assert steps[-1]["completes"] is not None

    applied = session.apply_steps(len(steps))
    assert applied["applied"] == len(steps)
    # Kart cekme artik otomatik degil; once hakki dogmali
    assert session.state()["pending_draws"] == 0


def test_advice_is_invalidated_when_hand_changes(session):
    session.new_game(seed=1)
    feed(session, HAND)
    session.get_advice(refresh=True)
    assert session.advice is not None
    session.apply_steps(1)
    assert session.advice is None or session.advice.steps


def test_entering_a_seen_card_is_rejected_without_breaking_state(session):
    session.new_game(seed=1)
    feed(session, HAND)
    session.apply_steps(0) if session.advice else None
    result = feed(session, [Card(1, "red")])
    assert result["error"]
    assert len(session.game.hand) == 5


def test_text_entry_accepts_short_codes(session):
    session.new_game(seed=1)
    result = session.provide_text("1r 2r 3r 5b 8g")
    assert result["error"] is None
    assert result["added"] == ["1r", "2r", "3r", "5b", "8g"]
    assert session.state()["hand_labels"] == ["1r", "2r", "3r", "5b", "8g"]


def test_text_entry_reports_bad_input(session):
    session.new_game(seed=1)
    result = session.provide_text("1r 9z")
    assert result["error"]
    assert session.game.hand == []


def test_undo_reverts_the_last_applied_step(session):
    session.new_game(seed=1)
    feed(session, HAND)
    session.get_advice(refresh=True)
    session.apply_steps(1)
    moves_before = session.game.move_no

    result = session.undo()
    assert result["error"] is None
    assert session.game.move_no == moves_before - 1
    assert len(session.game.hand) == 5


def test_draw_is_refused_until_a_card_leaves_the_hand(session):
    session.new_game(seed=1)
    feed(session, HAND)
    assert session.request_draw()["error"]          # el dolu

    session.manual_move(Action(DISCARD, 0))
    assert session.game.draw_count == 1
    assert session.request_draw()["error"] is None
    assert session.game.pending_draws == 1


def test_placing_cards_does_not_open_a_draw(session):
    session.new_game(seed=1)
    feed(session, HAND)
    session.manual_move(Action(PLACE, 0))
    session.manual_move(Action(PLACE, 0))
    assert session.game.draw_count == 0
    assert session.request_draw()["error"]


def test_completing_opens_three_draws(session):
    session.new_game(seed=1)
    feed(session, [Card(1, "red"), Card(2, "red"), Card(3, "red"),
                   Card(5, "blue"), Card(8, "green")])
    for _ in range(3):
        session.manual_move(Action(PLACE, 0))
    assert session.state()["can_complete"] is True
    assert session.state()["pending_combo"]["points"] == 50

    result = session.complete_combo()
    assert result["error"] is None
    assert session.game.total_score == 50
    assert session.game.draw_count == 3


def test_take_back_returns_a_card_to_the_hand(session):
    session.new_game(seed=1)
    feed(session, HAND)
    session.manual_move(Action(PLACE, 0))
    assert len(session.game.staged) == 1

    result = session.take_back(0)
    assert result["error"] is None
    assert session.game.staged == []
    assert len(session.game.hand) == 5


def test_take_back_reports_an_empty_combo(session):
    session.new_game(seed=1)
    feed(session, HAND)
    assert session.take_back(0)["error"]


def test_manual_move_overrides_the_advice(session):
    session.new_game(seed=1)
    feed(session, HAND)
    session.get_advice(refresh=True)
    result = session.manual_move(Action(DISCARD, 0))
    assert result["error"] is None
    assert session.advice is None
    assert session.game.discards == [Card(1, "red")]


def test_manual_illegal_move_reports_error(session, logger):
    session.new_game(seed=1)
    feed(session, HAND)
    result = session.manual_move(Action(PLACE, 99, None))
    assert result["error"] == "gecersiz hamle"
    assert read_csv(logger.stages_path) == []


# ---------------------------------------------------------------- loglama

def play_to_the_end(session, rng_seed=0):
    """Gercek oyunu taklit ederek turu bitirir."""
    import random
    rng = random.Random(rng_seed)

    def top_up():
        game = session.game
        while True:
            if game.pending_draws == 0:
                if game.draw_count == 0 or game.is_over:
                    return
                session.request_draw()
            pool = [c for c, n in game.unseen.items() for _ in range(n)]
            if not pool:
                session.stop_waiting()
                return
            session.provide_cards([rng.choice(pool)])

    top_up()
    guard = 0
    while not session.game.is_over and guard < 120:
        result = session.get_advice(refresh=True)
        if result["error"] or not result["advice"]:
            break
        session.apply_steps(len(result["advice"]["steps"]))
        top_up()
        guard += 1


def test_every_step_and_one_game_row_is_logged(session, logger):
    session.new_game(seed=101)
    play_to_the_end(session)

    stages = read_csv(logger.stages_path)
    games = read_csv(logger.games_path)
    assert len(games) == 1
    assert len(stages) == int(games[0]["moves"])
    assert int(stages[-1]["total_score"]) == int(games[0]["total_score"])
    assert games[0]["mode"] == "canli"
    assert all(row["source"] == SOLVER for row in stages)


def test_stage_rows_track_the_combo_number(session, logger):
    session.new_game(seed=5)
    play_to_the_end(session)
    rows = [r for r in read_csv(logger.stages_path) if r["action"] == "complete"]
    combo_numbers = [int(r["combo_no"]) for r in rows]
    assert combo_numbers == sorted(combo_numbers)      # ucluler sirayla dolar
    assert combo_numbers[0] == 1


def test_multiple_rounds_append_to_csv(session, logger):
    for seed in (1, 2, 3):
        session.new_game(seed=seed)
        play_to_the_end(session, rng_seed=seed)
    games = read_csv(logger.games_path)
    assert len(games) == 3
    stats = logger.stats()
    assert stats["games"] == 3
    assert stats["worst_score"] <= stats["avg_score"] <= stats["best_score"]


def test_game_row_is_not_duplicated(session, logger):
    session.new_game(seed=55)
    play_to_the_end(session)
    session.stop_waiting()
    assert len(read_csv(logger.games_path)) == 1


def test_each_round_starts_from_zero(session):
    session.new_game(seed=4)
    play_to_the_end(session)
    state = session.new_game(seed=4)
    assert state["total_score"] == 0
    assert state["cards_left"] == session.rules.deck_size
    assert session.events == []


# -------------------------------------------------------------- hibrit agent

class BrokenLLM:
    name = "llm:broken"

    def advise(self, game):
        raise AgentError("model cevap vermedi")


class FakeLLM:
    name = "llm:fake"

    def __init__(self, rules):
        self.solver = Solver(rules)

    def advise(self, game):
        return Advice(steps=annotate_plan(game, self.solver.plan(game)),
                      source=LLM, reason="sahte model", latency_ms=5)


def test_hybrid_falls_back_to_solver(rules, logger):
    agent = HybridAgent(rules, llm=BrokenLLM(), solver_agent=SolverAgent(rules))
    session = GameSession(rules, agent, logger, live=True)
    session.new_game(seed=17)
    play_to_the_end(session)

    stages = read_csv(logger.stages_path)
    assert stages and all(row["source"] == SOLVER for row in stages)
    assert agent.fallback_plans > 0
    assert int(read_csv(logger.games_path)[0]["llm_moves"]) == 0


def test_hybrid_without_fallback_raises(rules):
    agent = HybridAgent(rules, llm=BrokenLLM(), solver_agent=SolverAgent(rules), fallback=False)
    with pytest.raises(AgentError):
        agent.advise(OkeyGame(rules, seed=17, live=True))


def test_session_surfaces_agent_error_instead_of_crashing(rules, logger):
    agent = HybridAgent(rules, llm=BrokenLLM(), solver_agent=SolverAgent(rules), fallback=False)
    session = GameSession(rules, agent, logger, live=True)
    session.new_game(seed=17)
    feed(session, HAND)
    result = session.get_advice(refresh=True)
    assert "model cevap vermedi" in result["error"]
    assert result["advice"] is None


def test_llm_steps_are_tracked_in_csv(rules, logger):
    agent = HybridAgent(rules, llm=FakeLLM(rules), solver_agent=SolverAgent(rules))
    session = GameSession(rules, agent, logger, live=True)
    session.new_game(seed=23)
    play_to_the_end(session)

    row = read_csv(logger.games_path)[0]
    assert int(row["llm_moves"]) == int(row["moves"])
    assert float(row["llm_share"]) == 1.0


# ------------------------------------------------------------ plan cozumu

def test_resolve_card_steps_maps_labels_to_moves(rules):
    from okey.agents.base import resolve_card_steps
    from okey.cards import CardCodec

    game = OkeyGame(rules, seed=1, live=True)
    game.provide_cards(HAND)
    codec = CardCodec(rules.colors)
    actions = resolve_card_steps(
        game, [{"action": "place", "card": "1r"}, {"action": "discard", "card": "8g"}], codec
    )
    assert actions[0].type == PLACE
    assert game.hand[actions[0].card_index] == Card(1, "red")
    steps = annotate_plan(game, actions)
    assert [s.card for s in steps] == [Card(1, "red"), Card(8, "green")]


def test_resolve_card_steps_rejects_a_card_not_in_hand(rules):
    from okey.agents.base import resolve_card_steps
    from okey.cards import CardCodec
    from okey.engine import InvalidCard

    game = OkeyGame(rules, seed=1, live=True)
    game.provide_cards(HAND)
    with pytest.raises(InvalidCard):
        resolve_card_steps(game, [{"action": "place", "card": "7b"}], CardCodec(rules.colors))


def test_annotate_plan_stops_at_the_first_invalid_step(rules):
    game = OkeyGame(rules, seed=1, live=True)
    game.provide_cards(HAND)
    steps = annotate_plan(game, [Action(PLACE, 0, None), Action(PLACE, 99, None)])
    assert len(steps) == 1


# ------------------------------------------------------------- json ayristirma

@pytest.mark.parametrize("raw,expected", [
    ('{"plan": [{"action": "place", "card": "8r"}], "reason": "x"}', "8r"),
    ('```json\n{"plan": [{"action": "discard", "card": "1g"}], "reason": "y"}\n```', "1g"),
    ('<think>uzun uzun</think>{"plan": [{"action": "place", "card": "3b"}], "reason": "z"}', "3b"),
    ('Iste: {"plan": [{"action": "place", "card": "2r"}], "reason": "q"} umarim olur', "2r"),
])
def test_extract_json_variants(raw, expected):
    assert extract_json(raw)["plan"][0]["card"] == expected


def test_extract_json_raises_without_json():
    with pytest.raises(AgentError):
        extract_json("hicbir sey bulamadim")


# ------------------------------------------------------- solver vetosu

class FixedLLM:
    """Her zaman ayni karti oynamak isteyen sahte model."""

    name = "llm:fixed"

    def __init__(self, rules, card, kind=PLACE):
        self.rules = rules
        self.card = card
        self.kind = kind

    def advise(self, game):
        index = game.find_card(self.card)
        return Advice(steps=annotate_plan(game, [Action(self.kind, index, None)]),
                      source=LLM, reason="sabit model")


def screenshot_position(rules):
    """Kullanicinin bildirdigi pozisyon: acik uclu bos, elde 1m 3k 6k 2m 4k."""
    game = OkeyGame(rules, seed=1, live=True)
    game.provide_cards([Card(1, "blue"), Card(3, "red"), Card(6, "red"),
                        Card(2, "blue"), Card(4, "red")])
    return game


def test_veto_rejects_a_weak_llm_move(rules):
    """Kirmizi 6'yi oynamak Monte-Carlo'ya gore zayif; veto devreye girmeli."""
    agent = HybridAgent(rules, llm=FixedLLM(rules, Card(6, "red")),
                        solver_agent=SolverAgent(rules), veto_margin=0.25)
    advice = agent.advise(screenshot_position(rules))
    assert advice.source == SOLVER
    assert "zayif" in advice.fallback_reason
    assert agent.vetoed_plans == 1
    assert advice.steps[0].card != Card(6, "red")


def test_veto_lets_a_good_llm_move_through(rules):
    agent = HybridAgent(rules, llm=FixedLLM(rules, Card(3, "red")),
                        solver_agent=SolverAgent(rules), veto_margin=0.25)
    advice = agent.advise(screenshot_position(rules))
    assert advice.source == LLM
    assert agent.vetoed_plans == 0
    assert advice.steps[0].card == Card(3, "red")


def test_veto_can_be_disabled(rules):
    agent = HybridAgent(rules, llm=FixedLLM(rules, Card(6, "red")),
                        solver_agent=SolverAgent(rules), veto_margin=0.0)
    advice = agent.advise(screenshot_position(rules))
    assert advice.source == LLM
    assert advice.steps[0].card == Card(6, "red")


def test_vetoed_step_is_logged_as_solver(rules, logger):
    agent = HybridAgent(rules, llm=FixedLLM(rules, Card(6, "red")),
                        solver_agent=SolverAgent(rules), veto_margin=0.25)
    session = GameSession(rules, agent, logger, live=True)
    session.new_game(seed=1)
    session.provide_cards([Card(1, "blue"), Card(3, "red"), Card(6, "red"),
                           Card(2, "blue"), Card(4, "red")])
    session.get_advice(refresh=True)
    session.apply_steps(1)
    row = read_csv(logger.stages_path)[0]
    assert row["source"] == SOLVER
    assert "zayif" in row["fallback_reason"]


# ------------------------------------------------------- derin analiz

def test_deep_advice_uses_rollouts(rules, logger):
    session = GameSession(rules, SolverAgent(rules), logger, live=True)
    session.rules.agent = dict(session.rules.agent or {})
    session.new_game(seed=1)
    session.provide_cards([Card(1, "blue"), Card(3, "red"), Card(6, "red"),
                           Card(2, "blue"), Card(4, "red")])
    session.deep_solver.config.rollouts = 8      # test icin hizli tut
    result = session.get_deep_advice()
    assert result["error"] is None
    assert result["advice"]["source"] == SOLVER
    assert "derin analiz" in result["advice"]["reason"]
    assert result["advice"]["steps"]


def test_deep_advice_requires_cards_first(rules, logger):
    session = GameSession(rules, SolverAgent(rules), logger, live=True)
    session.new_game(seed=1)
    result = session.get_deep_advice()
    assert result["advice"] is None
    assert "kart gir" in result["error"]
