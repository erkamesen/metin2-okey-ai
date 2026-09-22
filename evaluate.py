"""Ajanlari ayni desteler uzerinde karsilastirir.

    python evaluate.py                       varsayilan: 300 tur, uc ajan
    python evaluate.py --games 1000
    python evaluate.py --agents acgozlu ileri --rollouts 20
    python evaluate.py --csv sonuclar.csv    her turu satir satir yaz

NEDEN AYNI DESTELER?
    Tur puanlarinin standart sapmasi ~60. Iki ajani farkli desteler uzerinde
    oynatirsan, aradaki 20 puanlik gercek farki gormek icin binlerce tur
    gerekir. Ayni desteleri oynatinca fark **eslestirilmis** olculuyor: her
    tur icin "A bu destede B'den kac puan fazla aldi" diyebiliyoruz ve
    destenin sansi iki taraftan da ayni sekilde cikiyor.

    Cikti bu ikisini yan yana gosteriyor, farki gozunle gor.
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
import time
from typing import Dict, List, Sequence

from okey import Okey
from okey.agents import REGISTRY, Agent, play_game


# --------------------------------------------------------------- olcumler

class Result:
    """Bir ajanin butun turlardaki sonucu."""

    def __init__(self, agent: Agent, scores: List[int], chests: List[str],
                 melds: List[int], seconds: float):
        self.agent = agent
        self.scores = scores
        self.chests = chests
        self.melds = melds
        self.seconds = seconds

    @property
    def mean(self) -> float:
        return statistics.mean(self.scores)

    @property
    def stdev(self) -> float:
        return statistics.stdev(self.scores) if len(self.scores) > 1 else 0.0

    @property
    def stderr(self) -> float:
        """Ortalamanin belirsizligi — **eslestirilmemis** olcum."""
        return self.stdev / math.sqrt(len(self.scores)) if self.scores else 0.0

    def chest_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for chest in self.chests:
            counts[chest] = counts.get(chest, 0) + 1
        return counts


def run(okey: Okey, agent: Agent, seeds: Sequence[int]) -> Result:
    scores, chests, melds = [], [], []
    started = time.perf_counter()
    for seed in seeds:
        game = play_game(okey, agent, seed)
        scores.append(game.score)
        chests.append(game.chest())
        melds.append(len(game.melds))
    return Result(agent, scores, chests, melds, time.perf_counter() - started)


class Paired:
    """Iki ajanin ayni desteler uzerindeki farki."""

    def __init__(self, better: Result, worse: Result):
        self.better = better
        self.worse = worse
        self.diffs = [a - b for a, b in zip(better.scores, worse.scores)]

    @property
    def mean(self) -> float:
        return statistics.mean(self.diffs)

    @property
    def stderr(self) -> float:
        """Farkin belirsizligi — **eslestirilmis** olcum.

        Eslestirilmemis olcumde iki ajanin belirsizligi toplanir; burada ise
        destenin sansi farkta birbirini goturdugu icin cok daha kucuk cikar.
        """
        if len(self.diffs) < 2:
            return 0.0
        return statistics.stdev(self.diffs) / math.sqrt(len(self.diffs))

    @property
    def unpaired_stderr(self) -> float:
        """Ayni farki eslestirmeden olcseydik belirsizlik ne olurdu."""
        return math.sqrt(self.better.stderr ** 2 + self.worse.stderr ** 2)

    @property
    def win_rate(self) -> float:
        wins = sum(1 for d in self.diffs if d > 0)
        return wins / len(self.diffs) if self.diffs else 0.0

    @property
    def is_clear(self) -> bool:
        """Fark, olcum belirsizliginin iki katindan buyuk mu (kabaca %95)."""
        return abs(self.mean) > 2 * self.stderr


# ------------------------------------------------------------------ cikti

def print_table(results: List[Result], seeds: Sequence[int]) -> None:
    print(f"\n  {len(seeds)} tur, ayni desteler (seed {seeds[0]}..{seeds[-1]})\n")
    header = (f"  {'ajan':<20}{'ortalama':>10}{'medyan':>8}{'std':>7}"
              f"{'en iyi':>8}{'en kotu':>9}{'uclu':>7}   sandiklar{'':>8}{'ms/tur':>9}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for result in sorted(results, key=lambda r: -r.mean):
        counts = result.chest_counts()
        chests = " ".join(f"{name}:{counts.get(name, 0)}"
                          for name in ("bronz", "gumus", "altin"))
        print(f"  {result.agent.name:<20}{result.mean:>10.1f}"
              f"{statistics.median(result.scores):>8.0f}{result.stdev:>7.1f}"
              f"{max(result.scores):>8}{min(result.scores):>9}"
              f"{statistics.mean(result.melds):>7.1f}   {chests:<20}"
              f"{result.seconds / len(seeds) * 1000:>9.1f}")


def print_pairs(results: List[Result]) -> None:
    ordered = sorted(results, key=lambda r: -r.mean)
    if len(ordered) < 2:
        return

    print("\n  ESLESTIRILMIS KARSILASTIRMA")
    print("  (ayni destede A kac puan fazla aldi)\n")
    for i, better in enumerate(ordered):
        for worse in ordered[i + 1:]:
            pair = Paired(better, worse)
            mark = "" if pair.is_clear else "   (belirsiz — fark gurultuden kucuk)"
            print(f"  {better.agent.name:<20} - {worse.agent.name:<20}"
                  f"{pair.mean:>+8.1f}  +-{pair.stderr:>5.1f}"
                  f"   turlarin %{pair.win_rate * 100:.0f}'sinde daha iyi{mark}")

    # Ogretici kisim: eslestirmenin etkisini **en yakin iki ajan** uzerinde
    # gosteriyoruz. Esleme, birbirine benzeyen ajanlarda ise yarar: ikisi de
    # ayni destede iyi ya da kotu oynar, destenin sansi farkta birbirini
    # goturur. Cok farkli iki ajanda (or. rastgele vs digerleri) puanlar
    # zaten ilintisiz oldugu icin kazanc kucuk kalir.
    sample = Paired(ordered[0], ordered[1])
    factor = sample.unpaired_stderr / max(sample.stderr, 1e-9)
    print(f"\n  Eslestirmenin etkisi ({ordered[0].agent.name} - "
          f"{ordered[1].agent.name}, fark {sample.mean:+.1f}):")
    print(f"    ayni desteler (eslestirilmis) : +-{sample.stderr:.1f} puan")
    print(f"    farkli desteler olsaydi       : +-{sample.unpaired_stderr:.1f} puan")
    print(f"    -> belirsizlik {factor:.1f} kat kucuk, yani ayni guvenle "
          f"{factor ** 2:.1f} kat az tur yetiyor")


def write_csv(path: str, results: List[Result], seeds: Sequence[int]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["seed", "ajan", "puan", "uclu", "sandik"])
        for result in results:
            for seed, score, meld, chest in zip(
                    seeds, result.scores, result.melds, result.chests):
                writer.writerow([seed, result.agent.name, score, meld, chest])
    print(f"\n  kayit: {path}")


# ------------------------------------------------------------------- giris

def build_agent(name: str, rollouts: int, seed: int) -> Agent:
    cls = REGISTRY[name]
    if name == "ileri":
        return cls(rollouts=rollouts, seed=seed)
    if name == "rastgele":
        return cls(seed=seed)
    return cls()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ajanlari ayni destelerde karsilastir")
    parser.add_argument("--games", type=int, default=300, help="kac tur oynansin")
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--agents", nargs="+", default=list(REGISTRY),
                        choices=list(REGISTRY))
    parser.add_argument("--rollouts", type=int, default=12,
                        help="ileri-bakisli ajanin simulasyon sayisi")
    parser.add_argument("--csv", default=None, help="her turu bu dosyaya yaz")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    okey = Okey()
    seeds = list(range(args.seed_start, args.seed_start + args.games))
    results = []
    for name in args.agents:
        agent = build_agent(name, args.rollouts, args.seed_start)
        print(f"  {agent.name} oynuyor...", end="", flush=True)
        result = run(okey, agent, seeds)
        print(f"\r  {' ' * 40}\r", end="")
        results.append(result)

    print_table(results, seeds)
    print_pairs(results)
    if args.csv:
        write_csv(args.csv, results, seeds)
    print()


if __name__ == "__main__":
    main()
