"""Oyun + agent + CSV loglamayi birlestiren oturum katmani.

Canli akis (asil kullanim):

    1. new_game()                -> motor ilk {hand_size} karti ister
    2. provide_cards([...])      -> oyuncu gercek oyundaki kartlari girer
    3. advise()                  -> agent "sunu koy, sunu at" plani verir
    4. apply_steps(n)            -> oyuncu gercek oyunda yapar, motor isler
    5. provide_cards([...])      -> yerine gelen kartlar girilir
    ... uclu dolunca puanlanir, yeni uclu acilir; deste bitene kadar devam
"""
from __future__ import annotations

import threading
from dataclasses import replace
import time
from typing import Dict, List, Optional, Sequence

from .agents.base import HUMAN, SOLVER, Advice, PlanStep, annotate_plan
from .agents.hybrid import SolverAgent
from .agents.ollama_agent import AgentError
from .cards import Card, CardCodec
from .engine import COMPLETE_ACTION, Action, InvalidCard, InvalidMove, OkeyGame
from .logbook import CsvLogger
from .rules import Rules
from .solver import Solver


class GameSession:
    """Tek bir turu yonetir; tur bitince otomatik olarak CSV'ye yazar."""

    def __init__(self, rules: Rules, agent, logger: CsvLogger, solver: Optional[Solver] = None,
                 live: bool = True):
        self.rules = rules
        self.agent = agent
        self.logger = logger
        # Uc ayri solver: hizli olan yan paneldeki siralama icin, Monte-Carlo'lu
        # olan "Derin Analiz" dugmesi icin. Asil oneriyi veren solver'i sunucu
        # kurup agent'a veriyor (bkz. build_solvers).
        self.solver = solver or Solver(rules)
        self.deep_solver = Solver(rules, replace(
            self.solver.config,
            rollouts=int((rules.agent or {}).get("deep_rollouts", 40)),
            rollout_candidates=int((rules.agent or {}).get("deep_candidates", 0)),
            rollout_seed=1,
        ))
        self.codec = CardCodec(rules.colors)
        self.live = live
        self.game: Optional[OkeyGame] = None
        self.advice: Optional[Advice] = None
        self.applied_sources: List[str] = []
        self.events: List[Dict] = []
        self.started_at = 0.0
        self._logged = False
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ akis

    @property
    def agent_name(self) -> str:
        return getattr(self.agent, "name", "agent")

    def _require_game(self) -> OkeyGame:
        if self.game is None:
            raise RuntimeError("once yeni bir tur baslatilmali")
        return self.game

    def new_game(self, seed: Optional[int] = None, live: Optional[bool] = None) -> Dict:
        with self._lock:
            self.live = self.live if live is None else live
            self.game = OkeyGame(self.rules, seed=seed, live=self.live)
            self.advice = None
            self.applied_sources = []
            self.events = []
            self.started_at = time.perf_counter()
            self._logged = False
            return self.state()

    # -------------------------------------------------------------- kart giris

    def provide_cards(self, cards: Sequence[Card]) -> Dict:
        """Oyuncunun gordugu kartlari motora bildirir."""
        with self._lock:
            game = self._require_game()
            try:
                added = game.provide_cards(cards)
            except (InvalidCard, InvalidMove) as exc:
                return {"state": self.state(), "error": str(exc)}
            self.advice = None          # el degisti, eski oneri gecersiz
            return {"state": self.state(), "added": [self.codec.label(c) for c in added],
                    "error": None}

    def provide_text(self, text: str) -> Dict:
        try:
            cards = self.codec.parse_many(text)
        except ValueError as exc:
            return {"state": self.state(), "error": str(exc)}
        if not cards:
            return {"state": self.state(), "error": "kart girilmedi"}
        return self.provide_cards(cards)

    def request_draw(self) -> Dict:
        """Desteden kart ister. Acik uclu tamamlanmadan ya da kart yok
        edilmeden kart cekilemez; o durumda motor sifir dondurur."""
        with self._lock:
            game = self._require_game()
            if game.request_draw() == 0 and game.pending_draws == 0:
                return {"state": self.state(),
                        "error": "once acik ucluyu tamamla ya da kart yok et"}
            self.advice = None
            return {"state": self.state(), "error": None}

    def complete_combo(self) -> Dict:
        """Acik ucluyu puanlayip kilitler."""
        with self._lock:
            game = self._require_game()
            if not game.can_complete:
                return {"state": self.state(), "error": "uclu henuz dolmadi"}
            source = self.advice.source if self.advice else HUMAN
            self._commit(COMPLETE_ACTION, source, "uclu tamamlandi", 0, "")
            self.advice = None
            summary = self._finish() if game.is_over else None
            return {"state": self.state(), "summary": summary, "error": None}

    def take_back(self, position: int) -> Dict:
        """Ucluye konmus bir karti ele geri alir."""
        with self._lock:
            game = self._require_game()
            try:
                game.take_back(position)
            except InvalidMove as exc:
                return {"state": self.state(), "error": str(exc)}
            self.advice = None
            return {"state": self.state(), "error": None}

    def stop_waiting(self) -> Dict:
        with self._lock:
            game = self._require_game()
            game.stop_waiting()
            self.advice = None
            summary = self._finish() if game.is_over else None
            return {"state": self.state(), "summary": summary, "error": None}

    # ------------------------------------------------------------------ oneri

    def get_advice(self, refresh: bool = False) -> Dict:
        """Agent'tan plan ister. Uygulamaz, sadece gosterir."""
        with self._lock:
            game = self._require_game()
            if game.is_over:
                return {"state": self.state(), "advice": None, "error": "tur bitti"}
            if game.pending_draws:
                return {"state": self.state(), "advice": None,
                        "error": f"once {game.pending_draws} kart gir"}
            if self.advice is not None and not refresh:
                return {"state": self.state(), "advice": self.advice.to_dict(self.codec),
                        "error": None}
            try:
                self.advice = self.agent.advise(game)
            except AgentError as exc:
                return {"state": self.state(), "advice": None, "error": str(exc)}
            return {"state": self.state(), "advice": self.advice.to_dict(self.codec), "error": None}

    def get_deep_advice(self) -> Dict:
        """Monte-Carlo ile dogrulanmis oneri (yavas, ~10-20 sn).

        Agent modundan bagimsiz calisir: her hamle icin turun sonuna kadar
        defalarca simulasyon yapip gercekten en yuksek puani getiren hamleyi
        secer. Sezgisel degerlendirmenin yanildigi yerlerde isabetli.
        """
        with self._lock:
            game = self._require_game()
            if game.is_over:
                return {"state": self.state(), "advice": None, "error": "tur bitti"}
            if game.pending_draws:
                return {"state": self.state(), "advice": None,
                        "error": f"once {game.pending_draws} kart gir"}
            agent = SolverAgent(self.rules, self.deep_solver)
            try:
                self.advice = agent.advise(game)
            except AgentError as exc:
                return {"state": self.state(), "advice": None, "error": str(exc)}
            self.advice.source = SOLVER
            self.advice.reason = f"derin analiz · {self.advice.reason}"
            return {"state": self.state(), "advice": self.advice.to_dict(self.codec), "error": None}

    # ---------------------------------------------------------------- uygulama

    def apply_steps(self, count: int = 1) -> Dict:
        """Onerinin ilk `count` adimini uygular."""
        with self._lock:
            game = self._require_game()
            if self.advice is None or not self.advice.steps:
                return {"state": self.state(), "error": "once oneri al"}

            source = self.advice.source
            reason = self.advice.reason
            fallback = self.advice.fallback_reason
            latency = self.advice.latency_ms
            applied = 0
            for step in self.advice.steps[:max(0, count)]:
                if not game.is_legal(step.action):
                    break
                self._commit(step.action, source, reason if applied == 0 else "",
                             latency if applied == 0 else 0, fallback)
                applied += 1

            remaining = self.advice.steps[applied:]
            # Kalan adimlar kayan indekslerle gecersizlesir; yeniden hesapla
            self.advice = self._reannotate(remaining, source, reason, fallback) if remaining else None
            summary = self._finish() if game.is_over else None
            return {"state": self.state(), "applied": applied,
                    "advice": self.advice.to_dict(self.codec) if self.advice else None,
                    "summary": summary, "error": None if applied else "adim uygulanamadi"}

    def apply_all(self) -> Dict:
        return self.apply_steps(count=len(self.advice.steps) if self.advice else 0)

    def _reannotate(self, steps: List[PlanStep], source: str, reason: str,
                    fallback: str) -> Optional[Advice]:
        game = self._require_game()
        actions: List[Action] = []
        for step in steps:
            if step.card is None:                 # TAMAMLA adimi
                actions.append(COMPLETE_ACTION)
                continue
            try:
                index = game.find_card(step.card)
            except InvalidCard:
                break
            actions.append(Action(step.action.type, index))
        fresh = annotate_plan(game, actions)
        if not fresh:
            return None
        return Advice(steps=fresh, source=source, reason=reason, fallback_reason=fallback)

    def manual_move(self, action: Action) -> Dict:
        """Oyuncunun kendi sectigi hamle (oneriye uymadan)."""
        with self._lock:
            game = self._require_game()
            if not game.is_legal(action):
                return {"state": self.state(), "error": "gecersiz hamle"}
            self._commit(action, HUMAN, "manuel", 0, "")
            self.advice = None
            summary = self._finish() if game.is_over else None
            return {"state": self.state(), "summary": summary, "error": None}

    def _commit(self, action: Action, source: str, reason: str, latency: int,
                fallback: str) -> None:
        game = self._require_game()
        outcome = game.apply(action)
        self.applied_sources.append(source)
        self.logger.log_stage(
            game, outcome, source=source, reason=reason,
            latency_ms=latency, fallback_reason=fallback, agent_name=self.agent_name,
        )
        self.events.append({
            **outcome.to_dict(),
            "card_label": self.codec.label(outcome.card) if outcome.card else "",
            "source": source,
            "reason": reason,
            "fallback_reason": fallback,
        })

    # ------------------------------------------------------------- geri alma

    def undo(self) -> Dict:
        with self._lock:
            game = self._require_game()
            if game.is_over:
                return {"state": self.state(), "error": "tur bitti, geri alinamaz"}
            if not game.undo():
                return {"state": self.state(), "error": "geri alinacak islem yok"}
            self.advice = None
            if self.events and len(self.events) > game.move_no:
                self.events = self.events[:game.move_no]
                self.applied_sources = self.applied_sources[:game.move_no]
            return {"state": self.state(), "error": None}

    # ------------------------------------------------------------ tur bitisi

    def _finish(self) -> Dict:
        game = self._require_game()
        if self._logged:
            return game.summary()
        self._logged = True
        row = self.logger.log_game(
            game, agent_name=self.agent_name, sources=self.applied_sources,
            duration_s=time.perf_counter() - self.started_at,
        )
        summary = game.summary()
        summary["csv_row"] = row
        return summary

    # ------------------------------------------------- simulasyon (benchmark)

    def play_out(self, max_moves: int = 500) -> Dict:
        """Simulasyon modunda turu sonuna kadar agent ile oynatir."""
        with self._lock:
            game = self._require_game()
            if game.live:
                return {"state": self.state(), "error": "otomatik oynatma sadece simulasyon modunda"}
            game.open_deck()
            moves = 0
            while not game.is_over and moves < max_moves:
                result = self.get_advice(refresh=True)
                if result.get("error"):
                    return result
                applied = self.apply_all()
                if applied.get("error") and not applied.get("applied"):
                    return applied
                moves += max(1, applied.get("applied", 1))
            return {"state": self.state(),
                    "summary": self._finish() if game.is_over else None, "error": None}

    # ----------------------------------------------------------------- durum

    def hints(self, top: int = 4) -> List[Dict]:
        game = self.game
        if game is None or game.is_over or not game.legal_actions():
            return []
        out = []
        for item in self.solver.explain(game, top=top):
            index = item["action"]["card_index"]
            if 0 <= index < len(game.hand):
                item["card_label"] = self.codec.label(game.hand[index])
            out.append(item)
        return out

    def state(self) -> Dict:
        game = self.game
        if game is None:
            return {"phase": "none", "agent": self.agent_name}
        data = game.to_dict()
        data["agent"] = self.agent_name
        data["hand_labels"] = [self.codec.label(c) for c in game.hand]
        data["color_codes"] = self.codec.to_code
        data["completions"] = self.solver.completions(game)
        data["target"] = self.solver.describe_target(game) if not game.is_over else ""
        data["events"] = self.events[-12:]
        data["source_counts"] = self._source_counts()
        data["has_advice"] = self.advice is not None
        return data

    def _source_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for source in self.applied_sources:
            counts[source] = counts.get(source, 0) + 1
        return counts
