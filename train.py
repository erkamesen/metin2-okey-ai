"""Ogrenen ajani egitir.

    python train.py                         varsayilan egitim
    python train.py --episodes 50000
    python train.py --alpha 0.02 --epsilon 0.4

ALGORITMA: sonraki-durum uzerinde TD ogrenme (Q-learning'in bir bicimi)

    Ajan her adimda "bu eylemi yaparsam ortaya cikan durum ne kadar deger?"
    diye sorar. Deger tahmini:  V(durum) = agirliklar . ozellikler

    Eylem secimi:      en yuksek (hemen kazanilan puan + V(sonraki durum))
    Ogrenme hedefi:    kart cekildikten sonra ayni hesabin verdigi deger
    Guncelleme:        agirliklar += alpha * (hedef - tahmin) * ozellikler

    Yani ajan kendi tahminini, bir adim sonra gordugu daha iyi bilgiye dogru
    ceker. Buna "bootstrapping" deniyor: nihai sonucu beklemeden ogrenir.

EGITIM VE OLCUM DESTELERI AYRI
    Egitim rastgele destelerde yapilir, olcum ise **hic gormedigi** sabit bir
    deste kumesinde. Ayni desteleri kullansaydik ajan o desteleri ezberleyip
    gercekte olmadigi kadar iyi gorunurdu.
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from typing import List, Optional, Sequence

from okey import Okey
from okey.agents import GreedyAgent, LinearAgent, play_game
from okey.env import OkeyEnv, RewardConfig
from okey.features import N_FEATURES

#: Olcum desteleri: egitimde ASLA kullanilmaz.
EVAL_SEED_START = 900_000


def evaluate(okey: Okey, agent: LinearAgent, count: int) -> float:
    """Gormedigi destelerde ortalama puan."""
    saved, agent.epsilon = agent.epsilon, 0.0      # olcumde kesif yok
    try:
        scores = [play_game(okey, agent, EVAL_SEED_START + i).score
                  for i in range(count)]
    finally:
        agent.epsilon = saved
    return statistics.mean(scores)


def train(okey: Okey, episodes: int, alpha: float, epsilon_start: float,
          epsilon_end: float, eval_every: int, eval_games: int,
          reward: RewardConfig, seed: int = 0) -> tuple:
    env = OkeyEnv(okey, reward=reward)
    agent = LinearAgent(okey, seed=seed)
    rng = random.Random(seed)
    history: List[tuple] = []

    started = time.perf_counter()
    for episode in range(1, episodes + 1):
        # Kesif orani basta yuksek, sonra dusuk: once dene, sonra kullan.
        agent.epsilon = epsilon_start + (epsilon_end - epsilon_start) * (
            episode / episodes)
        env.reset(seed=rng.randrange(1 << 30))

        while True:
            game = env.game
            # Kesif: bazen rastgele oyna ki hic denemedigi hamleleri gorsun
            if rng.random() < agent.epsilon:
                action = rng.choice(game.legal_actions())
                _, _, vector = next(
                    (c for c in agent.candidates(game) if c[0] == action), (0, 0, None))
            else:
                action, _, vector = agent.evaluate(game)

            _, step_reward, done, _ = env.step(action)

            # Hedef: kart cekildikten SONRA en iyi eylemin degeri.
            # Tur bittiyse gelecek yok, hedef sifir.
            if done:
                target = 0.0
            else:
                # evaluate() zaten olcekli deger donduruyor
                _, target, _ = agent.evaluate(env.game)

            prediction = agent.value(vector)
            error = target - prediction
            for index in range(N_FEATURES):
                agent.weights[index] += alpha * error * vector[index]

            if done:
                break

        if eval_every and episode % eval_every == 0:
            score = evaluate(okey, agent, eval_games)
            elapsed = time.perf_counter() - started
            history.append((episode, score))
            print(f"  {episode:>7} tur   olcum {score:>6.1f} puan   "
                  f"({elapsed:.0f} sn)")

    return agent, history


def main() -> None:
    parser = argparse.ArgumentParser(description="Ogrenen ajani egit")
    parser.add_argument("--episodes", type=int, default=20000)
    parser.add_argument("--alpha", type=float, default=0.01, help="ogrenme hizi")
    parser.add_argument("--epsilon", type=float, default=0.30,
                        help="baslangic kesif orani")
    parser.add_argument("--epsilon-end", type=float, default=0.02)
    parser.add_argument("--eval-every", type=int, default=2000)
    parser.add_argument("--eval-games", type=int, default=150)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="agirliklar.json")
    parser.add_argument("--leftover-penalty", type=float, default=0.0)
    parser.add_argument("--gold-bonus", type=float, default=0.0)
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    okey = Okey()
    reward = RewardConfig(leftover_penalty=args.leftover_penalty,
                          gold_bonus=args.gold_bonus)

    print(f"\n  EGITIM  {args.episodes} tur, alpha {args.alpha}, "
          f"kesif {args.epsilon} -> {args.epsilon_end}")
    print(f"  odul: {'sade (oyunun puani)' if reward.is_plain else reward}")
    print(f"  olcum destesi: seed {EVAL_SEED_START}.. "
          f"(egitimde kullanilmiyor)\n")

    agent, history = train(
        okey, args.episodes, args.alpha, args.epsilon, args.epsilon_end,
        args.eval_every, args.eval_games, reward, args.seed)

    final = evaluate(okey, agent, 300)
    greedy = statistics.mean(
        play_game(okey, GreedyAgent(), EVAL_SEED_START + i).score for i in range(300))

    print(f"\n  SONUC (300 gorulmemis deste)")
    print(f"    ogrenen : {final:.1f}")
    print(f"    acgozlu : {greedy:.1f}")
    print(f"    fark    : {final - greedy:+.1f}")

    print(f"\n  OGRENILEN AGIRLIKLAR\n")
    print(agent.explain())

    agent.save(args.out, extra={
        "tur": args.episodes, "alpha": args.alpha,
        "olcum_puani": round(final, 1), "gecmis": history,
    })
    print(f"\n  kayit: {args.out}\n")


if __name__ == "__main__":
    main()
