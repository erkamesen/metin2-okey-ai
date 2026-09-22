"""Ogrenen ajanlar icin oyun ortami.

Pekistirmeli ogrenmede ortam uc soruyu cevaplar:

    reset()        -> yeni tur basla, ilk gozlemi ver
    step(eylem)    -> eylemi uygula; yeni gozlem, odul ve bitti-mi dondur
    action_mask()  -> su an hangi eylemler yapilabilir

Bu dosya oyun kurallarini **bilmez**; motoru sarmalar. Ayirmanin sebebi:
kurallar degisirse ortam degismez, odul tanimi degisirse motor degismez.

    python -m okey.env      gozlem vektorunun ne oldugunu satir satir yazar


GOZLEM NE ICERIR

    [ 0:24]  el          — her kart icin "elimde mi" (1/0)
    [24:48]  destede     — her kart icin "hala gelebilir mi" (1/0)
    [48]     kalan kart orani
    [49]     su ana kadarki puan (olceklenmis)
    [50]     kurulan uclu orani
    [51]     eldeki kart orani

Bir kartin silinmis ya da uclu yapilmis olmasi ayri bir alan istemiyor:
hem elde hem destede 0 ise o kart gitmis demektir.

**Bu gozlem yeterli.** Ajanin bilmedigi tek sey destenin sirasi; ama sira
rastgele oldugu icin "hangi kartlar kaldi" bilgisi karar vermek icin yeterli
olan her seyi tasiyor. Yani eksik bilgiyle oynuyor gibi gorunse de aslinda
bilinebilecek her seyi biliyor.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .engine import Okey, OkeyGame
from .rules import DEFAULT_RULES, Rules

Observation = List[float]


@dataclass(frozen=True)
class RewardConfig:
    """Odul tanimi — yani ajanin **neyi** en yuksege cikarmaya calisacagi.

    Varsayilan hali oyunun gercek amaciyla birebir ayni: her hamlede kazanilan
    puan. Turun toplam odulu, turun toplam puanina esit oluyor.

    Diger iki secenek "odul sekillendirme". Ogrenmeyi hizlandirabilirler ama
    **amaci degistirirler** — bu yuzden varsayilan olarak kapalilar:

    * `leftover_penalty`: tur sonunda elde kalan her kart icin ceza. Ajani
      kartlari bosa harcamamaya iter. Riski: ajan puan getirmeyecek olsa bile
      kart harcamaya baslar.
    * `gold_bonus`: toplam `gold_threshold` puani gecerse tek seferlik odul.
      Amaci "ortalama puani en yuksege cikar"dan "altin sandik sansini en
      yuksege cikar"a cevirir. Bunlar ayni sey degil: altin pesindeki ajan
      daha cok kumar oynar, ortalamasi duser ama 400+ turlarin orani artar.
      Hangisini istedigine karar vermen gereken bir yer.
    """

    leftover_penalty: float = 0.0
    gold_bonus: float = 0.0
    gold_threshold: int = 400

    @property
    def is_plain(self) -> bool:
        """Sekillendirme yok mu — odul tam olarak oyunun puani mi?"""
        return self.leftover_penalty == 0.0 and self.gold_bonus == 0.0


class OkeyEnv:
    """Motoru ogrenen ajanlarin bekledigi arayuze sarar."""

    def __init__(self, okey: Optional[Okey] = None,
                 rules: Rules = DEFAULT_RULES,
                 reward: Optional[RewardConfig] = None):
        self.okey = okey or Okey(rules)
        self.rules = self.okey.rules
        self.reward_config = reward or RewardConfig()
        self.deck_size = self.okey.deck.size
        self.game: Optional[OkeyGame] = None

    # ------------------------------------------------------------ boyutlar

    @property
    def n_actions(self) -> int:
        return self.okey.n_actions

    @property
    def observation_size(self) -> int:
        return 2 * self.deck_size + 4

    # --------------------------------------------------------------- akis

    def reset(self, seed: Optional[int] = None) -> Observation:
        self.game = self.okey.new_game(seed)
        return self.observe()

    def step(self, action: int) -> Tuple[Observation, float, bool, Dict]:
        """Eylemi uygular. (gozlem, odul, bitti, bilgi) dondurur."""
        game = self._require_game()
        move = game.apply(action)

        reward = float(move.points)
        config = self.reward_config
        if game.is_over:
            if config.leftover_penalty:
                reward -= config.leftover_penalty * len(game.hand)
            if config.gold_bonus and game.score >= config.gold_threshold:
                reward += config.gold_bonus

        info = {
            "puan": game.score,          # oyunun gercek puani (odulden bagimsiz)
            "hamle": move.kind,
            "uclu": len(game.melds),
            "kartlar": move.cards,
            "kombinasyon": move.combo,
        }
        return self.observe(), reward, game.is_over, info

    def action_mask(self) -> List[bool]:
        return self._require_game().action_mask()

    def legal_actions(self) -> List[int]:
        return self._require_game().legal_actions()

    # ------------------------------------------------------------- gozlem

    def observe(self) -> Observation:
        """Durumun sayi vektorune cevrilmis hali."""
        game = self._require_game()
        size = self.deck_size

        vector = [0.0] * (2 * size + 4)
        for card in game.hand:
            vector[card] = 1.0
        for card in game.deck:                 # sadece hangi kartlar; sira degil
            vector[size + card] = 1.0

        rules = self.rules
        vector[2 * size + 0] = game.cards_left / size
        vector[2 * size + 1] = game.score / max(1, rules.score_ceiling)
        vector[2 * size + 2] = len(game.melds) / max(1, rules.max_combos)
        vector[2 * size + 3] = len(game.hand) / rules.hand_size
        return vector

    def describe_observation(self, vector: Optional[Observation] = None) -> str:
        """Gozlemi insan okunur hale getirir (ogretim ve hata ayiklama icin)."""
        vector = vector if vector is not None else self.observe()
        deck, size = self.okey.deck, self.deck_size
        hand = [deck.label(c) for c in range(size) if vector[c]]
        unseen = [deck.label(c) for c in range(size) if vector[size + c]]
        gone = [deck.label(c) for c in range(size)
                if not vector[c] and not vector[size + c]]
        return (
            f"  el      ({len(hand):>2}) {' '.join(hand) or '-'}\n"
            f"  destede ({len(unseen):>2}) {' '.join(unseen) or '-'}\n"
            f"  gitmis  ({len(gone):>2}) {' '.join(gone) or '-'}\n"
            f"  kalan orani {vector[2*size+0]:.2f}  puan {vector[2*size+1]:.3f}  "
            f"uclu {vector[2*size+2]:.2f}  el {vector[2*size+3]:.2f}"
        )

    # --------------------------------------------------------------- yardim

    def _require_game(self) -> OkeyGame:
        if self.game is None:
            raise RuntimeError("once reset() cagrilmali")
        return self.game

    @property
    def score(self) -> int:
        """Oyunun gercek puani — odul sekillendirmesinden etkilenmez."""
        return self._require_game().score


# ------------------------------------------------------------------ demo

def _demo() -> None:
    """Bir turu oynatip gozlemin nasil degistigini gosterir."""
    import random
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    env = OkeyEnv()
    rng = random.Random(0)
    env.reset(seed=7)

    print(f"\n  gozlem boyutu : {env.observation_size}")
    print(f"  eylem sayisi  : {env.n_actions}")
    print(f"  odul          : "
          f"{'sade (oyunun puani)' if env.reward_config.is_plain else 'sekillendirilmis'}")

    print("\n  BASLANGIC")
    print(env.describe_observation())

    total_reward = 0.0
    step_no = 0
    while True:
        actions = env.legal_actions()
        action = rng.choice(actions)
        _, reward, done, info = env.step(action)
        total_reward += reward
        step_no += 1
        cards = env.okey.deck.labels(info["kartlar"])
        print(f"  {step_no:>2}. eylem {action:>2}  {info['hamle']:<5} {cards:<12}"
              f"odul {reward:+4.0f}   toplam puan {info['puan']}")
        if done:
            break

    print("\n  SON")
    print(env.describe_observation())
    print(f"\n  toplam odul {total_reward:.0f} = turun puani {env.score}"
          if env.reward_config.is_plain else
          f"\n  toplam odul {total_reward:.0f}, turun puani {env.score}")
    print()


if __name__ == "__main__":
    _demo()
