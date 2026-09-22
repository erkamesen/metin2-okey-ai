"""Solver tabanli agent ve LLM + solver yedekli hibrit agent."""
from __future__ import annotations

import time
from dataclasses import replace
from typing import Optional

from ..engine import DISCARD, OkeyGame, clone_for_search
from ..rules import Rules
from ..solver import Solver, SolverConfig
from .base import SOLVER, Advice, annotate_plan
from .ollama_agent import AgentError, OllamaAgent, OllamaConfig


class SolverAgent:
    """Sadece deterministik solver. Baseline ve yedek olarak kullanilir."""

    def __init__(self, rules: Rules, solver: Optional[Solver] = None):
        self.rules = rules
        self.solver = solver or Solver(rules)
        self.name = "solver"

    def advise(self, game: OkeyGame) -> Advice:
        started = time.perf_counter()
        actions = self.solver.plan(game)
        if not actions:
            raise AgentError("oynanabilecek hamle yok")
        steps = annotate_plan(game, actions)
        return Advice(
            steps=steps,
            source=SOLVER,
            reason=self._reason(game, steps),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def _reason(self, game: OkeyGame, steps) -> str:
        if not steps:
            return ""
        last = steps[-1]
        if last.completes:
            if last.points:
                return f"{last.completes.label} tamamlaniyor: +{last.points} puan"
            return "bu uclu artik puan getirmiyor, en degersiz kartlarla kapat"
        if last.action.type == DISCARD:
            return f"bu kart acik ucluye yaramiyor · {self.solver.describe_target(game)}"
        after = clone_for_search(game, planning=True)
        for step in steps:
            after.apply(step.action)
        return self.solver.describe_target(after)


class HybridAgent:
    """Plani LLM kurar; gecersiz/zaman asimi durumunda solver devralir.

    CSV'ye her adimda kararin LLM'den mi solver'dan mi geldigi yazilir, boylece
    modelin gercek katkisi olculebilir.
    """

    def __init__(
        self,
        rules: Rules,
        llm: Optional[OllamaAgent] = None,
        solver_agent: Optional[SolverAgent] = None,
        fallback: bool = True,
        veto_margin: float = 0.25,
    ):
        self.rules = rules
        self.llm = llm or OllamaAgent(rules)
        self.solver_agent = solver_agent or SolverAgent(rules)
        self.fallback = fallback
        # Modelin ilk adimi, solver'in deger araliginin bu kadar altina duserse
        # oneri reddedilir. 0 = veto kapali.
        self.veto_margin = veto_margin
        self.name = f"hybrid({self.llm.name}+solver)"
        self.llm_plans = 0
        self.fallback_plans = 0
        self.vetoed_plans = 0

    def advise(self, game: OkeyGame) -> Advice:
        try:
            advice = self.llm.advise(game)
        except AgentError as exc:
            if not self.fallback:
                raise
            self.fallback_plans += 1
            advice = self.solver_agent.advise(game)
            advice.fallback_reason = str(exc)[:200]
            return advice

        veto = self._veto_reason(game, advice)
        if veto:
            self.vetoed_plans += 1
            replacement = self.solver_agent.advise(game)
            replacement.fallback_reason = veto
            return replacement

        self.llm_plans += 1
        return advice

    def _veto_reason(self, game: OkeyGame, advice: Advice) -> str:
        """Modelin ilk adimi acikca kotuyse nedenini dondurur, degilse bos.

        LLM zaman zaman gereksiz yere iyi bir karti harcayan ya da atan hamleler
        oneriyor. Solver'in siralamasinda alt siralarda kalan bir hamle, oyuncuya
        gosterilmeden once reddedilir; CSV'ye solver karari olarak yazilir.
        """
        if self.veto_margin <= 0 or not advice.steps:
            return ""
        ranked = self.solver_agent.solver.evaluate_actions(game)
        if len(ranked) < 2:
            return ""

        best, worst = ranked[0], ranked[-1]
        spread = best.value - worst.value
        if spread <= 0:
            return ""

        first = advice.steps[0]
        chosen = max(
            (r.value for r in ranked
             if r.action.type == first.action.type
             and game.hand[r.action.card_index] == first.card),
            default=None,
        )
        if chosen is None or best.value - chosen <= spread * self.veto_margin:
            return ""
        verb = "atmak" if first.action.type == DISCARD else "oynamak"
        return f"model {first.card} kartini {verb} istedi, solver bunu zayif buldu"


def advice_solver(rules: Rules) -> Solver:
    """Oneriyi ve vetoyu veren solver.

    Varsayilan olarak Monte-Carlo dogrulamasi acik. Olcumde belirgin fark
    yapiyor (225 -> 307 puan) ve karar basina yalnizca ~4 saniye suruyor.
    `agent.solver_rollouts: 0` ile kapatilip saf sezgisele dusulebilir.
    """
    rollouts = int((rules.agent or {}).get("solver_rollouts", 12))
    base = SolverConfig()
    if rollouts <= 0:
        return Solver(rules, base)
    return Solver(rules, replace(base, rollouts=rollouts, rollout_candidates=0, rollout_seed=1))


def build_agent(rules: Rules, mode: str = "hybrid", solver: Optional[Solver] = None):
    """mode: hybrid | llm | solver"""
    mode = (mode or "hybrid").lower()
    solver = solver or advice_solver(rules)
    if mode == "solver":
        return SolverAgent(rules, solver)
    llm = OllamaAgent(rules, OllamaConfig.from_rules(rules))
    if mode == "llm":
        return llm
    fallback = bool((rules.agent or {}).get("fallback_to_solver", True))
    return HybridAgent(rules, llm=llm, solver_agent=SolverAgent(rules, solver),
                       fallback=fallback,
                       veto_margin=float((rules.agent or {}).get("veto_margin", 0.25)))
