"""Tur ve asama kayitlarini CSV'ye yazar.

- stages.csv : her hamle (asama) icin bir satir
- games.csv  : her tur icin bir ozet satiri
"""
from __future__ import annotations

import csv
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from .agents.base import HUMAN, LLM, SOLVER
from .engine import MoveOutcome, OkeyGame
from .scoring import GROUP, INVALID, RUN_MIXED, RUN_SAME

STAGE_FIELDS = [
    "timestamp", "game_id", "agent", "move_no", "combo_no", "action", "card",
    "combo_after", "combo_kind", "combo_key", "points", "total_score",
    "cards_left", "hand_after", "source", "latency_ms", "fallback_reason", "reason",
]

GAME_FIELDS = [
    "timestamp", "game_id", "seed", "agent", "mode", "total_score", "chest",
    "moves", "placements", "discards", "combos_done", "groups",
    "runs_same_color", "runs_mixed", "invalid_combos",
    "llm_moves", "solver_moves", "human_moves", "llm_share", "duration_s",
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class CsvLogger:
    def __init__(self, stages_path: str, games_path: str):
        self.stages_path = stages_path
        self.games_path = games_path
        self._lock = threading.Lock()
        for path, fields in ((stages_path, STAGE_FIELDS), (games_path, GAME_FIELDS)):
            self._ensure(path, fields)

    @staticmethod
    def _ensure(path: str, fields: List[str]) -> None:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                csv.DictWriter(handle, fieldnames=fields).writeheader()

    def _append(self, path: str, fields: List[str], row: Dict) -> None:
        with self._lock:
            with open(path, "a", newline="", encoding="utf-8") as handle:
                csv.DictWriter(handle, fieldnames=fields).writerow(row)

    # -------------------------------------------------------------- asamalar

    def log_stage(
        self,
        game: OkeyGame,
        outcome: MoveOutcome,
        source: str = "",
        reason: str = "",
        latency_ms: int = 0,
        fallback_reason: str = "",
        agent_name: str = "",
    ) -> None:
        combo_after = ""
        combo_no = ""
        if outcome.slot_index is not None:
            slot = game.slots[outcome.slot_index]
            combo_after = " ".join(str(c) for c in slot.cards)
            combo_no = outcome.slot_index + 1
        self._append(self.stages_path, STAGE_FIELDS, {
            "timestamp": _now(),
            "game_id": game.game_id,
            "agent": agent_name,
            "move_no": outcome.move_no,
            "combo_no": combo_no,
            "action": outcome.action.type,
            "card": str(outcome.card) if outcome.card else "",
            "combo_after": combo_after,
            "combo_kind": outcome.completed.kind if outcome.completed else "",
            "combo_key": outcome.completed.key if outcome.completed and outcome.completed.key else "",
            "points": outcome.points,
            "total_score": outcome.total_score,
            "cards_left": outcome.cards_left,
            "hand_after": " ".join(str(c) for c in game.hand),
            "source": source,
            "latency_ms": latency_ms or "",
            "fallback_reason": (fallback_reason or "")[:120],
            "reason": (reason or "").replace("\n", " ")[:300],
        })

    # ------------------------------------------------------------------ tur

    def log_game(
        self,
        game: OkeyGame,
        agent_name: str = "",
        sources: Optional[Sequence[str]] = None,
        duration_s: float = 0.0,
    ) -> Dict:
        sources = list(sources or [])
        kinds = {GROUP: 0, RUN_SAME: 0, RUN_MIXED: 0, INVALID: 0}
        for slot in game.slots:
            if slot.result:
                kinds[slot.result.kind] = kinds.get(slot.result.kind, 0) + 1

        llm_moves = sources.count(LLM)
        solver_moves = sources.count(SOLVER)
        human_moves = sources.count(HUMAN)
        summary = game.summary()

        row = {
            "timestamp": _now(),
            "game_id": game.game_id,
            "seed": game.seed,
            "agent": agent_name,
            "mode": "canli" if game.live else "simulasyon",
            "total_score": game.total_score,
            "chest": summary["chest"]["chest"],
            "moves": summary["moves"],
            "placements": summary["placements"],
            "discards": summary["discards"],
            "combos_done": summary["filled_slots"],
            "groups": kinds.get(GROUP, 0),
            "runs_same_color": kinds.get(RUN_SAME, 0),
            "runs_mixed": kinds.get(RUN_MIXED, 0),
            "invalid_combos": kinds.get(INVALID, 0),
            "llm_moves": llm_moves,
            "solver_moves": solver_moves,
            "human_moves": human_moves,
            "llm_share": round(llm_moves / len(sources), 3) if sources else "",
            "duration_s": round(duration_s, 2),
        }
        self._append(self.games_path, GAME_FIELDS, row)
        return row

    # ---------------------------------------------------------------- okuma

    def recent_games(self, limit: int = 20) -> List[Dict]:
        if not os.path.exists(self.games_path):
            return []
        with open(self.games_path, "r", newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        return rows[-limit:][::-1]

    def stats(self) -> Dict:
        rows = self.recent_games(limit=10_000)
        scores = [int(r["total_score"]) for r in rows if r.get("total_score", "").isdigit()]
        if not scores:
            return {"games": 0}
        chests: Dict[str, int] = {}
        for row in rows:
            chests[row.get("chest", "?")] = chests.get(row.get("chest", "?"), 0) + 1
        return {
            "games": len(scores),
            "avg_score": round(sum(scores) / len(scores), 1),
            "best_score": max(scores),
            "worst_score": min(scores),
            "chests": chests,
        }


class NullLogger(CsvLogger):
    """Hicbir sey yazmaz. Benchmark'in gercek kayitlari kirletmemesi icin."""

    def __init__(self) -> None:
        self.stages_path = "(kapali)"
        self.games_path = "(kapali)"
        self._lock = threading.Lock()
        self._games: List[Dict] = []

    def _append(self, path: str, fields: List[str], row: Dict) -> None:
        if path == self.games_path:
            self._games.append(row)

    def recent_games(self, limit: int = 20) -> List[Dict]:
        return self._games[-limit:][::-1]


def logger_from_rules(rules, base_dir: str = ".") -> CsvLogger:
    cfg = rules.logging or {}
    return CsvLogger(
        os.path.join(base_dir, cfg.get("stages_csv", "logs/stages.csv")),
        os.path.join(base_dir, cfg.get("games_csv", "logs/games.csv")),
    )
