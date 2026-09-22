"""Web API'nin arayuzun bekledigi sekilde cevap verdigini dogrular."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from okey.web.server import create_app

HAND_TEXT = "1r 2r 3r 5b 8g"
HAND_CARDS = [
    {"rank": 1, "color": "red"}, {"rank": 2, "color": "red"}, {"rank": 3, "color": "red"},
    {"rank": 5, "color": "blue"}, {"rank": 8, "color": "green"},
]


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app("config/rules.yaml", log_dir=str(tmp_path))) as test_client:
        yield test_client


def start(client, seed=77, mode="solver"):
    return client.post("/api/new", json={"seed": seed, "agent_mode": mode}).json()


def deal(client, text=HAND_TEXT):
    return client.post("/api/cards", json={"text": text}).json()


# ----------------------------------------------------------------- servis

def test_index_and_static_files_served(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_config_exposes_everything_the_ui_needs(client):
    data = client.get("/api/config").json()
    for key in ("ranks", "colors", "color_codes", "max_combos", "hand_size", "scoring", "rewards"):
        assert key in data
    assert {row["kind"] for row in data["scoring"]} == {"group", "run_mixed", "run_same_color"}
    assert [r["chest"] for r in data["rewards"]] == ["golden", "silver", "bronze"]
    assert data["max_combos"] == data["deck_size"] // data["combo_size"]


# ------------------------------------------------------------- tur akisi

def test_new_round_asks_for_the_first_cards(client):
    state = start(client)
    assert state["phase"] == "awaiting_cards"
    assert state["pending_draws"] == state["hand_size"]
    assert state["hand"] == []
    assert state["cards_left"] == 24


def test_cards_can_be_entered_as_text_or_objects(client):
    start(client)
    state = deal(client)["state"]
    assert state["hand_labels"] == ["1r", "2r", "3r", "5b", "8g"]
    assert state["cards_left"] == 24 - 5
    assert state["phase"] == "playing"

    start(client, seed=78)
    state = client.post("/api/cards", json={"cards": HAND_CARDS}).json()["state"]
    assert state["hand_labels"] == ["1r", "2r", "3r", "5b", "8g"]


def test_entering_an_impossible_card_is_reported(client):
    start(client)
    deal(client)
    result = client.post("/api/cards", json={"text": "1r"}).json()
    assert result["error"]


def test_bad_card_text_is_reported(client):
    start(client)
    result = client.post("/api/cards", json={"text": "9zz"}).json()
    assert result["error"]
    assert result["state"]["hand"] == []


def test_only_the_active_combo_is_exposed(client):
    start(client)
    state = deal(client)["state"]
    assert state["active_slot"] == 0
    assert state["combos_done"] == 0
    assert all(not slot["is_full"] for slot in state["slots"])


def test_advice_then_apply(client):
    start(client)
    deal(client)
    advice = client.get("/api/advice?refresh=true").json()
    assert advice["error"] is None
    steps = advice["advice"]["steps"]
    assert steps
    assert advice["advice"]["source"] == "solver"

    result = client.post("/api/apply", json={"count": len(steps)}).json()
    assert result["applied"] == len(steps)
    assert result["state"]["pending_draws"] == 0


def test_advice_requires_cards_first(client):
    start(client)
    result = client.get("/api/advice?refresh=true").json()
    assert result["advice"] is None
    assert "kart gir" in result["error"]


def test_manual_move_and_undo(client):
    start(client)
    deal(client)
    moved = client.post("/api/move", json={"type": "discard", "card_index": 0}).json()
    assert moved["error"] is None
    assert moved["state"]["draw_count"] == 1
    assert moved["state"]["can_undo"] is True

    undone = client.post("/api/undo").json()
    assert undone["error"] is None
    assert undone["state"]["draw_count"] == 0
    assert undone["state"]["hand_labels"] == ["1r", "2r", "3r", "5b", "8g"]


def test_illegal_manual_move_is_reported(client):
    start(client)
    deal(client)
    result = client.post("/api/move", json={"type": "place", "card_index": 99}).json()
    assert result["error"] == "gecersiz hamle"
    assert client.post("/api/move", json={"type": "fly", "card_index": 0}).status_code == 400


def test_draw_complete_and_take_back(client):
    """Kullanicinin tarif ettigi akis: 3 kart koy -> Tamamla -> 3 kart cek."""
    start(client)
    deal(client, "1r 2r 3r 5b 8g")

    # Kart koymak cekme hakki kazandirmaz
    for _ in range(3):
        client.post("/api/move", json={"type": "place", "card_index": 0})
    state = client.get("/api/state").json()
    assert state["draw_count"] == 0
    assert state["can_complete"] is True
    assert state["pending_combo"]["points"] == 50
    assert client.post("/api/draw").json()["error"]

    # Tamamla -> elde 2 kart kalir, 3 kart cekilebilir
    completed = client.post("/api/complete").json()
    assert completed["error"] is None
    assert completed["state"]["total_score"] == 50
    assert completed["state"]["draw_count"] == 3
    assert len(completed["state"]["hand"]) == 2

    drawn = client.post("/api/draw").json()
    assert drawn["state"]["pending_draws"] == 3


def test_take_back_endpoint(client):
    start(client)
    deal(client)
    client.post("/api/move", json={"type": "place", "card_index": 0})
    state = client.get("/api/state").json()
    assert len(state["slots"][state["active_slot"]]["cards"]) == 1

    result = client.post("/api/take-back", json={"position": 0}).json()
    assert result["error"] is None
    assert result["state"]["slots"][0]["cards"] == []
    assert result["state"]["hand_labels"] == ["2r", "3r", "5b", "8g", "1r"]


def test_complete_is_refused_before_the_combo_is_full(client):
    start(client)
    deal(client)
    assert client.post("/api/complete").json()["error"] == "uclu henuz dolmadi"


def test_no_more_cards_ends_the_deck(client):
    start(client)
    deal(client)
    state = client.post("/api/no-more-cards").json()["state"]
    assert state["cards_left"] == 0
    assert state["combos_possible"] == 1


def test_unseen_pool_shrinks_as_cards_are_entered(client):
    state = start(client)
    before = sum(entry["count"] for entry in state["unseen"])
    state = deal(client)["state"]
    after = sum(entry["count"] for entry in state["unseen"])
    assert before - after == 5


def test_hints_are_ranked_and_labelled(client):
    start(client)
    deal(client)
    hints = client.get("/api/hints?top=4").json()["hints"]
    assert 0 < len(hints) <= 4
    assert hints == sorted(hints, key=lambda h: -h["value"])
    assert all(h["card_label"] for h in hints)


def test_log_endpoint_returns_stats_shape(client):
    data = client.get("/api/log?limit=5").json()
    assert "games" in data and "stats" in data


# ------------------------------------------------- olasilik bilgisi

def test_state_carries_the_target_text(client):
    start(client)
    state = deal(client)["state"]
    assert state["target"] == "yeni uclu"


def test_state_lists_completing_cards_with_counts(client):
    """Arayuz bu listeden "hangi kart kac puan, gelme sansi ne" hesapliyor."""
    start(client)
    deal(client, "6b 8b 1r 3g 5r")
    client.post("/api/move", json={"type": "place", "card_index": 0})   # 6b
    client.post("/api/move", json={"type": "place", "card_index": 0})   # 8b
    state = client.get("/api/state").json()

    assert [c["rank"] for c in state["slots"][state["active_slot"]]["cards"]] == [6, 8]
    completions = state["completions"]
    assert completions, "7'ler ucluyu tamamlamali"
    assert completions[0] == {"rank": 7, "color": "blue", "points": 100,
                              "remaining": 1, "in_hand": False}
    assert all(c["rank"] == 7 for c in completions)
    # Olasilik hesabi icin gereken iki sayi
    assert state["cards_left"] > 0
    assert all(c["remaining"] >= 0 for c in completions)


def test_unseen_counts_support_per_card_odds(client):
    """Her kart icin destede kac adet kaldigi durumda bulunmali."""
    start(client)
    state = deal(client)["state"]
    total = sum(entry["count"] for entry in state["unseen"])
    assert total == state["cards_left"]
    assert all(entry["count"] > 0 for entry in state["unseen"])
    entered = {(1, "red"), (2, "red"), (3, "red"), (5, "blue"), (8, "green")}
    assert not any((e["rank"], e["color"]) in entered for e in state["unseen"])
