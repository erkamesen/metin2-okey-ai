"""Durumu, ogrenen ajanin anlayabilecegi sayilara cevirir.

NEDEN HAM GOZLEM YETMIYOR
    `env.observe()` 52 sayi veriyor: hangi kartlar elimde, hangileri destede.
    Bu bilgi **eksiksiz** ama **lineer** bir model icin kullanissiz. Cunku
    "6k + 7k + 8k birlikte 100 puan eder" bilgisi uc kartin ETKILESIMI ve
    lineer model etkilesim goremez — her karta ayri bir agirlik verip toplar,
    o kadar. Elinde 6k ve 7k varken 8k'nin cok degerli olmasi, 8k tek basina
    oldugunda olmamasi: lineer model bunu ifade edemez.

    Cozum: yapiyi biz cikarip ajana hazir veriyoruz. "Elindeki en iyi ikili
    kac puanlik bir ucluyu bekliyor" gibi sorulari biz cevapliyoruz, ajan da
    bu cevaplara ne kadar deger verecegini ogreniyor.

NE OGRENIYOR PEKI
    Agirliklari. Daha once bu projede `empty_slot_factor` ve `look_factor`
    gibi katsayilari elle izgara taramasiyla ayarlamistik — saatler surmustu
    ve sadece iki katsayiydi. Ajan ayni isi kendi yapiyor, üstelik 11 katsayi
    icin ayni anda. Ogrendigi agirliklar okunabilir oldugu icin de "neyi
    onemli bulmus" diye bakabiliyoruz.

SONRAKI DURUM (afterstate)
    Ajan "bu eylemi yaparsam ortaya cikan durum ne kadar iyi" diye soruyor.
    Eylemden hemen sonraki, ama daha kart cekilmemis durumu degerlendiriyoruz.
    Kart cekme rastgele oldugu icin bu ayrim onemli: eylemin kendisi kesin,
    sonrasi sans. Ikisini ayirinca ogrenme cok daha kararli oluyor.
"""
from __future__ import annotations

from itertools import combinations
from typing import Dict, List, Sequence, Tuple

from .rules import Rules
from .scoring import ScoreTable

#: Ozelliklerin adlari — ogrenilen agirliklari okurken bunlari kullaniyoruz.
FEATURE_NAMES: Tuple[str, ...] = (
    "sabit",                # her durumda 1; modelin baslangic noktasi
    "eldeki_kart",          # kac kart elde kaldi
    "destedeki_kart",       # deste ne kadar dolu
    "hazir_uclu",           # su an kurulabilecek en iyi uclu
    "en_iyi_ikili",         # en iyi ikilinin bekledigi uclu
    "ikinci_ikili",         # ondan bagimsiz ikinci ikili
    "canlilik_ort",         # kartlarin ortalama ise yararligi
    "canlilik_min",         # en zayif kartin ise yararligi
    "olu_kart",             # hicbir ucluye giremeyen kart sayisi
    "kalan_uclu_hakki",     # kalan kartlarla kac uclu daha kurulabilir
    "tamamlanan_uclu",      # su ana kadar kac uclu kuruldu
)

N_FEATURES = len(FEATURE_NAMES)


class FeatureExtractor:
    """Bir durumu `N_FEATURES` sayilik vektore cevirir.

    Butun degerler kabaca 0..1 araliginda tutuluyor. Ayni olcekte olmalari
    ogrenmeyi kolaylastiriyor: tek bir ogrenme hizi hepsine uyuyor.
    """

    __slots__ = ("table", "rules", "deck_size", "_scale")

    def __init__(self, table: ScoreTable, rules: Rules):
        self.table = table
        self.rules = rules
        self.deck_size = table.deck.size
        self._scale = float(max(1, table.best_points()))   # en yuksek uclu puani

    def extract(self, hand: Sequence[int], available: frozenset,
                cards_left: int, melds_done: int) -> List[float]:
        """Ozellik vektoru.

        `hand`      : eylemden sonra elde kalan kartlar
        `available` : hala oyunda olan kartlar (el + deste)
        `cards_left`: destede kalan kart sayisi
        `melds_done`: su ana kadar kurulan uclu sayisi
        """
        table = self.table
        rules = self.rules
        scale = self._scale
        size = len(hand)

        # --- kartlarin tek tek ise yararligi
        alive = [table.best_use_of(card, available) for card in hand]
        alive_mean = (sum(alive) / size / scale) if size else 0.0
        alive_min = (min(alive) / scale) if size else 0.0
        dead = sum(1 for value in alive if value == 0)

        # --- ikililer: "iki kartim var, ucuncusunu bekliyorum"
        pair_values: Dict[Tuple[int, int], int] = {}
        for first, second in combinations(range(size), 2):
            points = table.best_pair_points(hand[first], hand[second], available)
            if points:
                pair_values[(first, second)] = points

        best_pair, second_pair = self._two_best_pairs(pair_values)

        # --- su an kurulabilecek hazir uclu
        ready = 0
        if size >= rules.combo_size:
            for triple in combinations(hand, rules.combo_size):
                points = table.points(tuple(sorted(triple)))
                if points > ready:
                    ready = points

        usable = size + cards_left
        return [
            1.0,
            size / rules.hand_size,
            cards_left / self.deck_size,
            ready / scale,
            best_pair / scale,
            second_pair / scale,
            alive_mean,
            alive_min,
            dead / rules.hand_size,
            (usable // rules.combo_size) / max(1, rules.max_combos),
            melds_done / max(1, rules.max_combos),
        ]

    @staticmethod
    def _two_best_pairs(pair_values: Dict[Tuple[int, int], int]) -> Tuple[int, int]:
        """En iyi ikili ve onunla **kart paylasmayan** ikinci en iyi ikili.

        Kart paylasmama sarti onemli: ayni karti iki ucluye birden koyamazsin,
        dolayisiyla "elimde iki ayri firsat var" demek ancak kartlar ayriysa
        dogru olur.
        """
        if not pair_values:
            return 0, 0
        best_pair = max(pair_values, key=pair_values.get)
        best = pair_values[best_pair]
        used = set(best_pair)
        second = max(
            (points for pair, points in pair_values.items() if not used & set(pair)),
            default=0,
        )
        return best, second
