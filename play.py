"""Okey'i terminalden elle oyna.

    python play.py                 rastgele deste
    python play.py --seed 42       ayni desteyi tekrar oynamak icin
    python play.py --random 500    500 turu rastgele oynat, istatistik yaz

Amaci motoru gozle dogrulamak: kurallar gercek oyunla ayni mi, puanlar
tutuyor mu, eylem listesi mantikli mi.
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys

from okey import Okey

# ----------------------------------------------------------------- renkler

ANSI = {
    "kirmizi": "\033[91m",
    "mavi": "\033[94m",
    "sari": "\033[93m",
}
DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"


class Screen:
    """Yaziyi renklendirir; renk kapaliysa sade metne duser."""

    def __init__(self, okey: Okey, color: bool = True):
        self.okey = okey
        self.deck = okey.deck
        self.color = color

    def _paint(self, text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if self.color else text

    def card(self, card: int) -> str:
        label = self.deck.label(card)
        return self._paint(f"{label:>3}", ANSI.get(self.deck.color_name(card), ""))

    def cards(self, cards) -> str:
        return " ".join(self.card(c) for c in cards)

    def dim(self, text: str) -> str:
        return self._paint(text, DIM)

    def bold(self, text: str) -> str:
        return self._paint(text, BOLD)


# ------------------------------------------------------------------ ekran

def show(screen: Screen, game) -> None:
    okey = screen.okey
    ceiling = okey.rules.score_ceiling
    print()
    print(screen.bold(
        f"  PUAN {game.score:>4}   {game.chest():<6}   "
        f"uclu {len(game.melds)}   destede {game.cards_left:>2}   "
        f"hamle {game.move_no}"))
    print(screen.dim(f"  {'-' * 62}"))

    if game.melds:
        for cards, combo in game.melds:
            print(f"  {screen.cards(cards)}   {screen.dim(combo.label)}  +{combo.points}")
        print(screen.dim(f"  {'-' * 62}"))

    print(f"  ELIN   {screen.cards(game.hand)}")
    indexes = "".join(f"[{i}]".rjust(4) for i in range(len(game.hand)))
    print(f"         {indexes}")
    if game.discarded:
        print(f"  SILDIN {screen.dim(screen.deck.labels(game.discarded))}")
    print()

    if game.is_over:
        return

    melds, discards = [], []
    for action in game.legal_actions():
        if okey.is_discard(action):
            discards.append(action)
        else:
            melds.append(action)

    if melds:
        print(screen.bold("  UCLU KURABILECEKLERIN"))
        for action in sorted(melds, key=lambda a: -_points(okey, game, a)):
            slot = okey.meld_slot(action)
            triple = tuple(sorted(game.hand[i] for i in slot))
            combo = okey.table.combo(triple)
            print(f"   {action:>2}   {screen.cards(triple)}   "
                  f"{combo.label:<24} {screen.bold(f'+{combo.points}')}")
    else:
        print(screen.dim("  (bu elde gecerli uclu yok)"))

    if discards:
        print(screen.bold("\n  KART SILEBILIRSIN"))
        print("   " + "   ".join(
            f"{a:>2} {screen.card(game.hand[a])}" for a in discards))
    print()


def _points(okey: Okey, game, action: int) -> int:
    slot = okey.meld_slot(action)
    return okey.table.points(tuple(sorted(game.hand[i] for i in slot)))


def show_remaining(screen: Screen, game) -> None:
    """Kart sayma: hangi kartlar hala destede."""
    deck = screen.deck
    unseen = set(game.unseen())
    print(f"\n  DESTEDE KALAN {len(unseen)} KART")
    for color_index, color in enumerate(deck.colors):
        row = []
        for rank in deck.ranks:
            card = deck.card(rank, color)
            row.append(screen.card(card) if card in unseen else screen.dim("  ."))
        print(f"   {color:<8} {' '.join(row)}")
    print(screen.dim("   (nokta = bu kart artik gelmeyecek)"))
    print()


def show_summary(screen: Screen, game) -> None:
    summary = game.summary()
    print(screen.bold(f"\n  TUR BITTI — {summary['puan']} puan, {summary['sandik']} sandik"))
    print(f"  {summary['uclu']} uclu kuruldu, {summary['silinen']} kart silindi, "
          f"elde {summary['elde_kalan']} kart kaldi")
    if game.hand:
        print(f"  kullanilamayan: {screen.cards(game.hand)}")
    compare_with_agents(screen, game)
    print()


def compare_with_agents(screen: Screen, game) -> None:
    """Ayni desteyi referans ajanlar oynasa kac alirdi.

    Ortalamalara bakmak soyut kaliyor; ayni destede senin kac aldiginla
    ajanlarin kac aldigini yan yana gormek cok daha ogretici.
    """
    try:
        from okey.agents import GreedyAgent, LookaheadAgent, play_game
    except ImportError:
        return

    print(screen.dim("\n  Ayni destede referans oyuncular:"))
    rows = [("sen", game.score)]
    for agent in (GreedyAgent(), LookaheadAgent(rollouts=12)):
        rows.append((agent.name, play_game(game.okey, agent, game.seed).score))

    best = max(score for _, score in rows)
    for name, score in sorted(rows, key=lambda row: -row[1]):
        mark = screen.bold("  <-- en iyi") if score == best else ""
        print(f"   {name:<18}{score:>5} puan{mark}")
    print(screen.dim(f"   (ayni destede tekrar dene: python play.py --seed {game.seed})"))
    print(screen.dim(f"   (ajanlarin hamlelerini izle: python replay.py --seed {game.seed})"))


# ------------------------------------------------------------------- oyun

HELP = """
  KOMUTLAR
   <sayi>   o eylemi yap (yukaridaki listeden)
   k        destede kalan kartlari goster
   y        yeni tur
   q        cikis
"""


def play(okey: Okey, seed=None, color=True) -> None:
    screen = Screen(okey, color)
    game = okey.new_game(seed)
    print(screen.bold("\n  Metin2 Okey — motor testi"))
    print(screen.dim(f"  deste {okey.deck.size} kart · seed {game.seed}"))
    print(screen.dim(HELP))

    while True:
        show(screen, game)
        if game.is_over:
            show_summary(screen, game)
            answer = input("  yeni tur? (e/h) > ").strip().lower()
            if answer.startswith("e"):
                game = okey.new_game()
                continue
            return

        try:
            command = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if command in ("q", "cik", "exit"):
            return
        if command in ("k", "kalan"):
            show_remaining(screen, game)
            continue
        if command in ("y", "yeni"):
            game = okey.new_game()
            continue
        if command in ("?", "h", "yardim"):
            print(screen.dim(HELP))
            continue

        if not command.isdigit():
            print(screen.dim("  ? anlamadim — sayi gir, ya da k / y / q"))
            continue

        action = int(command)
        if not game.is_legal(action):
            print(screen.dim(
                f"  {action} su an yapilamaz: {okey.describe_action(action, game.hand)}"))
            continue

        move = game.apply(action)
        if move.combo:
            print(f"  -> {move.combo.label} kuruldu, {screen.bold(f'+{move.points} puan')}")
        else:
            print(f"  -> {screen.deck.label(move.cards[0])} silindi")
        if move.drawn:
            print(f"     desteden geldi: {screen.cards(move.drawn)}")


def random_games(okey: Okey, count: int) -> None:
    """Rastgele oynayan ajanla hizli istatistik — motorun saglamlik testi."""
    rng = random.Random(0)
    scores, chests = [], {}
    for seed in range(count):
        game = okey.new_game(seed=seed)
        while not game.is_over:
            game.apply(rng.choice(game.legal_actions()))
        scores.append(game.score)
        chests[game.chest()] = chests.get(game.chest(), 0) + 1

    print(f"\n  {count} tur, rastgele oynayan ajan")
    print(f"  ortalama : {statistics.mean(scores):.1f}")
    print(f"  medyan   : {statistics.median(scores):.0f}")
    print(f"  en iyi   : {max(scores)}   en kotu: {min(scores)}")
    print(f"  sandiklar: {chests}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Okey motorunu elle test et")
    parser.add_argument("--seed", type=int, default=None,
                        help="ayni desteyi tekrar oynamak icin")
    parser.add_argument("--random", type=int, default=0, metavar="N",
                        help="N turu rastgele oynat, istatistik yaz")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    okey = Okey()
    if args.random:
        random_games(okey, args.random)
    else:
        play(okey, args.seed, color=not args.no_color)


if __name__ == "__main__":
    main()
