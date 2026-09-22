"""Ajanlari ayni destede hamle hamle izle.

    python replay.py --seed 42
    python replay.py --seed 42 --agents acgozlu ileri
    python replay.py --seed 42 --quiet        sadece ayrildiklari yeri goster

Ortalamalar "hangi ajan daha iyi" der ama **neden** daha iyi oldugunu
soylemez. Bu betik ayni desteyi iki ajana oynatip her hamlesini yaziyor, en
sonunda da ilk kez farkli karar verdikleri ani gosteriyor. Ogrenilecek sey
orada.
"""
from __future__ import annotations

import argparse
import sys
from typing import List, NamedTuple, Optional

from okey import Okey
from okey.agents import REGISTRY, Agent


class Step(NamedTuple):
    """Bir hamlenin oncesi ve sonrasi."""

    hand: str
    action: int
    text: str
    points: int
    total: int
    drawn: str


class Run(NamedTuple):
    agent_name: str
    steps: List[Step]
    score: int
    melds: int
    chest: str
    leftover: str


def run_agent(okey: Okey, agent: Agent, seed: int) -> Run:
    game = okey.new_game(seed)
    agent.reset()
    steps: List[Step] = []
    while not game.is_over and len(steps) < 200:
        hand = okey.deck.labels(game.hand)
        action = agent.act(game)
        move = game.apply(action)
        if move.combo:
            text = (f"uclu {okey.deck.labels(move.cards)} -> "
                    f"{move.combo.label} +{move.points}")
        else:
            text = f"sil  {okey.deck.label(move.cards[0])}"
        steps.append(Step(hand, action, text, move.points, move.total_score,
                          okey.deck.labels(move.drawn)))
    return Run(agent.name, steps, game.score, len(game.melds), game.chest(),
               okey.deck.labels(game.hand))


def print_run(run: Run) -> None:
    print(f"\n  {'-' * 3} {run.agent_name} {'-' * (56 - len(run.agent_name))}")
    for number, step in enumerate(run.steps, 1):
        print(f"  {number:>2}. el {step.hand}")
        print(f"      {step.text:<44}toplam {step.total}")
        if step.drawn:
            print(f"      geldi: {step.drawn}")
    print(f"  SONUC  {run.score} puan, {run.melds} uclu, {run.chest} sandik"
          + (f", elde kalan: {run.leftover}" if run.leftover else ""))


def print_divergence(runs: List[Run]) -> None:
    """Iki ajanin ilk kez farkli karar verdigi an.

    Bu noktadan sonra oyunlar tamamen ayrisiyor (farkli kartlar cekiliyor),
    o yuzden karsilastirilabilir tek an bu.
    """
    if len(runs) < 2:
        return
    first, second = runs[0], runs[1]

    for index in range(min(len(first.steps), len(second.steps))):
        a, b = first.steps[index], second.steps[index]
        if a.action == b.action:
            continue
        print(f"\n  ILK AYRILDIKLARI HAMLE: {index + 1}.")
        print(f"  elde: {a.hand}")
        print(f"    {first.agent_name:<20} {a.text}")
        print(f"    {second.agent_name:<20} {b.text}")
        return
    print("\n  Ayni destede bastan sona ayni oynadilar.")


def print_summary(runs: List[Run]) -> None:
    print(f"\n  {'ajan':<22}{'puan':>7}{'uclu':>7}   sandik")
    print("  " + "-" * 48)
    for run in sorted(runs, key=lambda r: -r.score):
        print(f"  {run.agent_name:<22}{run.score:>7}{run.melds:>7}   {run.chest}")
    if len(runs) > 1:
        best, worst = max(runs, key=lambda r: r.score), min(runs, key=lambda r: r.score)
        if best.score != worst.score:
            print(f"\n  FARK: {best.agent_name} bu destede "
                  f"{best.score - worst.score} puan onde")


def build_agent(name: str, okey: Okey, rollouts: int = 12, seed: int = 0,
                weights: str = "agirliklar.json") -> Agent:
    """Isimden ajan kurar. Ogrenen ajan egitilmis agirliklari yukler."""
    cls = REGISTRY[name]
    if name == "ileri":
        return cls(rollouts=rollouts, seed=seed)
    if name == "rastgele":
        return cls(seed=seed)
    if name == "ogrenen":
        agent = cls.load_if_trained(okey, weights)
        if agent is None:
            raise SystemExit(
                f"  '{weights}' bulunamadi. Once egit:  python train.py")
        return agent
    return cls()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ajanlari ayni destede izle")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--agents", nargs="+", default=["acgozlu", "ileri"],
                        choices=list(REGISTRY))
    parser.add_argument("--rollouts", type=int, default=12)
    parser.add_argument("--weights", default="agirliklar.json")
    parser.add_argument("--quiet", action="store_true",
                        help="hamleleri yazma, sadece ozet ve ayrilma noktasi")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    okey = Okey()
    print(f"\n  SEED {args.seed} — ayni deste, {len(args.agents)} ajan")

    runs = [run_agent(okey, build_agent(name, okey, args.rollouts, 0, args.weights),
                      args.seed)
            for name in args.agents]
    if not args.quiet:
        for run in runs:
            print_run(run)
    print_summary(runs)
    print_divergence(runs)
    print(f"\n  Ayni desteyi sen de oyna:  python play.py --seed {args.seed}\n")


if __name__ == "__main__":
    main()
