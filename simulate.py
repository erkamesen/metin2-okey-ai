"""Toplu tur simulasyonu — solver'i olcmek ve ayarlamak icin.

Gercek kullanim canli danisman arayuzudur (`python run_web.py`); bu betik
sadece motoru/solver'i sayisal olarak degerlendirir.

Ornekler:
    python simulate.py --games 300 --agent solver --quiet
    python simulate.py --games 5   --agent hybrid
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from typing import Dict, List

from okey.agents.hybrid import SolverAgent, build_agent
from okey.logbook import NullLogger, logger_from_rules
from okey.rules import DEFAULT_CONFIG_PATH, load_rules
from okey.session import GameSession
from okey.solver import Solver, SolverConfig


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Metin2 Okey tur simulasyonu")
    parser.add_argument("--games", type=int, default=20, help="oynanacak tur sayisi")
    parser.add_argument("--agent", default="solver", choices=["solver", "llm", "hybrid"])
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--seed-start", type=int, default=None,
                        help="verilirse turlar bu seed'den itibaren tekrarlanabilir olur")
    parser.add_argument("--rollouts", type=int, default=0,
                        help="solver icin Monte-Carlo simulasyon sayisi (yavas ama daha iyi)")
    parser.add_argument("--empty-slot-factor", type=float, default=None)
    parser.add_argument("--look-factor", type=float, default=None)
    parser.add_argument("--no-log", action="store_true",
                        help="CSV yazma (parametre taramasi/benchmark icin)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    rules = load_rules(args.config)
    logger = NullLogger() if args.no_log else logger_from_rules(rules)

    config = SolverConfig(rollouts=args.rollouts)
    if args.empty_slot_factor is not None:
        config.empty_slot_factor = args.empty_slot_factor
    if args.look_factor is not None:
        config.look_factor = args.look_factor

    solver = Solver(rules, config)
    agent = SolverAgent(rules, solver) if args.agent == "solver" else build_agent(rules, args.agent)
    session = GameSession(rules, agent, logger, solver, live=False)

    scores: List[int] = []
    combos: List[int] = []
    discards: List[int] = []
    chests: Dict[str, int] = {}
    started = time.perf_counter()

    for index in range(args.games):
        seed = None if args.seed_start is None else args.seed_start + index
        session.new_game(seed=seed, live=False)
        result = session.play_out()
        if result.get("error"):
            print(f"[{index + 1}/{args.games}] HATA: {result['error']}", file=sys.stderr)
            continue
        summary = result["summary"] or session.game.summary()
        scores.append(summary["total_score"])
        combos.append(summary["filled_slots"])
        discards.append(summary["discards"])
        chest = summary["chest"]["chest"]
        chests[chest] = chests.get(chest, 0) + 1
        if not args.quiet:
            sources = " ".join(f"{k}={v}" for k, v in session._source_counts().items())
            print(
                f"[{index + 1}/{args.games}] {summary['game_id']} "
                f"puan={summary['total_score']:>4} sandik={chest:<6} "
                f"uclu={summary['filled_slots']} atilan={summary['discards']:>2} {sources}"
            )

    if not scores:
        print("hic tur tamamlanamadi", file=sys.stderr)
        return 1

    elapsed = time.perf_counter() - started
    print("\n" + "-" * 62)
    print(f"agent            : {session.agent_name}")
    print(f"solver           : empty={solver.config.empty_slot_factor} "
          f"look={solver.config.look_factor} rollouts={solver.config.rollouts}")
    print(f"tur sayisi       : {len(scores)}")
    print(f"ortalama puan    : {statistics.mean(scores):.1f}")
    print(f"medyan           : {statistics.median(scores):.1f}")
    if len(scores) > 1:
        print(f"std sapma        : {statistics.stdev(scores):.1f}")
    print(f"en iyi / kotu    : {max(scores)} / {min(scores)}")
    print(f"teorik max       : {rules.max_score}")
    print(f"ortalama uclu    : {statistics.mean(combos):.1f} / {rules.slots}")
    print(f"ortalama atilan  : {statistics.mean(discards):.1f}")
    print(f"sandiklar        : {chests}")
    print(f"sure             : {elapsed:.1f} sn ({elapsed / len(scores):.2f} sn/tur)")
    print(f"kayitlar         : {logger.games_path} , {logger.stages_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
