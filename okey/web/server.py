"""FastAPI sunucusu: kart UI'ini servis eder, motoru API olarak acar."""
from __future__ import annotations

import os
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agents.hybrid import advice_solver, build_agent
from ..agents.ollama_agent import OllamaClient, OllamaConfig
from ..cards import Card
from ..engine import DISCARD, PLACE, Action
from ..logbook import logger_from_rules
from ..rules import DEFAULT_CONFIG_PATH, load_rules
from ..scoring import all_scoring_combos
from ..session import GameSession
from ..solver import Solver

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class NewGameRequest(BaseModel):
    seed: Optional[int] = None
    agent_mode: Optional[str] = None


class CardsRequest(BaseModel):
    """Kartlar ya metin ("7r 4b") ya da {rank,color} listesi olarak gelir."""

    text: Optional[str] = None
    cards: Optional[List[dict]] = None


class MoveRequest(BaseModel):
    type: str
    card_index: int


class ApplyRequest(BaseModel):
    count: int = 1


class TakeBackRequest(BaseModel):
    position: int = 0


def create_app(config_path: str = DEFAULT_CONFIG_PATH, log_dir: str = ".") -> FastAPI:
    rules = load_rules(config_path)
    logger = logger_from_rules(rules, base_dir=log_dir)
    solver = Solver(rules)            # hizli, sadece yan paneldeki siralama icin
    advisor = advice_solver(rules)    # oneri ve veto: Monte-Carlo dogrulamali

    state = {"agent_mode": "hybrid"}
    state["session"] = GameSession(
        rules, build_agent(rules, "hybrid", advisor), logger, solver, live=True)

    def set_mode(mode: str) -> None:
        mode = (mode or "hybrid").lower()
        if mode not in ("hybrid", "llm", "solver"):
            raise HTTPException(400, f"bilinmeyen agent modu: {mode}")
        if mode == state["agent_mode"]:
            return
        state["agent_mode"] = mode
        agent = build_agent(rules, mode, advisor)
        state["session"] = GameSession(rules, agent, logger, solver, live=True)

    def session() -> GameSession:
        return state["session"]

    app = FastAPI(title="Metin2 Okey Danismani", version="0.2.0")

    @app.get("/api/config")
    def get_config():
        codec = session().codec
        return {
            "ranks": list(rules.ranks),
            "colors": list(rules.colors),
            "color_codes": codec.to_code,
            "deck_size": rules.deck_size,
            "max_combos": rules.slots,
            "combo_size": rules.combo_size,
            "hand_size": rules.hand_size,
            "max_score": rules.max_score,
            "scoring": all_scoring_combos(rules),
            "rewards": [
                {"min_score": t.min_score, "chest": t.chest, "label": t.label}
                for t in sorted(rules.rewards, key=lambda t: -t.min_score)
            ],
            "agent_mode": state["agent_mode"],
            "model": (rules.agent or {}).get("model", ""),
        }

    @app.get("/api/agent")
    def agent_status():
        client = OllamaClient(OllamaConfig.from_rules(rules))
        available = client.is_available()
        return {
            "mode": state["agent_mode"],
            "name": session().agent_name,
            "ollama_up": available,
            "models": client.installed_models() if available else [],
            "model": client.config.model,
        }

    @app.get("/api/state")
    def get_state():
        return session().state()

    @app.post("/api/new")
    def new_game(req: NewGameRequest):
        if req.agent_mode:
            set_mode(req.agent_mode)
        return session().new_game(seed=req.seed, live=True)

    @app.post("/api/cards")
    def provide_cards(req: CardsRequest):
        current = session()
        if req.cards is not None:
            try:
                cards = [Card(int(c["rank"]), str(c["color"])) for c in req.cards]
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(400, f"kart okunamadi: {exc}")
            return current.provide_cards(cards)
        return current.provide_text(req.text or "")

    @app.post("/api/draw")
    def draw():
        return session().request_draw()

    @app.post("/api/complete")
    def complete():
        return session().complete_combo()

    @app.post("/api/take-back")
    def take_back(req: TakeBackRequest):
        return session().take_back(req.position)

    @app.post("/api/no-more-cards")
    def no_more_cards():
        return session().stop_waiting()

    @app.get("/api/advice")
    def advice(refresh: bool = False):
        return session().get_advice(refresh=refresh)

    @app.post("/api/deep-advice")
    def deep_advice():
        return session().get_deep_advice()

    @app.post("/api/apply")
    def apply_steps(req: ApplyRequest):
        return session().apply_steps(count=req.count)

    @app.post("/api/apply-all")
    def apply_all():
        return session().apply_all()

    @app.post("/api/move")
    def move(req: MoveRequest):
        kind = req.type.lower()
        if kind not in (PLACE, DISCARD):
            raise HTTPException(400, "type 'place' veya 'discard' olmali")
        return session().manual_move(Action(kind, req.card_index, None))

    @app.post("/api/undo")
    def undo():
        return session().undo()

    @app.get("/api/hints")
    def hints(top: int = 4):
        return {"hints": session().hints(top=top)}

    @app.get("/api/log")
    def log(limit: int = 12):
        return {"games": logger.recent_games(limit=limit), "stats": logger.stats()}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    return app


app = create_app()
