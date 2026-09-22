"""Deterministik karar motoru.

LLM agent gecersiz hamle uretir veya zaman asimina ugrarsa bu solver devreye
girer. Ayni zamanda LLM'in performansini olcecegimiz temel cizgi (baseline).

Yaklasim: her yasal hamle icin hamle sonrasi durumun potansiyeli hesaplanir.

    Phi(state) = kazanilmis puan + toplam(acik slotlarin beklenen puani)

Bir slotun beklenen puani, o slotu tamamlayabilecek kombinasyonlarin puani ile
gerekli kartlarin gelme olasiliginin carpimidir. Olasilik, destede kalan kart
havuzundan (kart sayma) hipergeometrik dagilimla tahmin edilir.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .cards import Card
from .engine import (
    COMPLETE, COMPLETE_ACTION, DISCARD, PHASE_FINISHED, PHASE_PLAYING,
    Action, OkeyGame, Slot, clone_for_search,
)
from .rules import Rules
from .scoring import GROUP, RUN_MIXED, RUN_SAME, score_combo

# --------------------------------------------------------------- olasiliklar


def _hyper_at_least(successes: int, pool: int, draws: int, need: int) -> float:
    """`pool` kartlik havuzdan `draws` kart cekilince en az `need` isabet olasiligi."""
    if need <= 0:
        return 1.0
    if successes < need or pool <= 0:
        return 0.0
    draws = max(0, min(draws, pool))
    if draws < need:
        return 0.0
    total = math.comb(pool, draws)
    if total == 0:
        return 0.0
    miss = 0
    for hits in range(need):
        if hits > successes or draws - hits > pool - successes:
            continue
        miss += math.comb(successes, hits) * math.comb(pool - successes, draws - hits)
    return max(0.0, 1.0 - miss / total)


# ------------------------------------------------------------- kombinasyonlar


@dataclass(frozen=True)
class ComboTemplate:
    """Bir slotun hedefleyebilecegi kombinasyon sablonu."""

    kind: str
    key: int
    points: int
    color: Optional[str]      # RUN_SAME icin sabit renk, digerleri icin None
    ranks: Tuple[int, ...]    # gereken sayilar (grupta ayni sayi 3 kez)


def combo_templates(rules: Rules) -> List[ComboTemplate]:
    templates: List[ComboTemplate] = []
    for rank, points in rules.group_scores.items():
        templates.append(ComboTemplate(GROUP, rank, int(points), None, (rank, rank, rank)))
    for start, points in rules.run_mixed_scores.items():
        templates.append(
            ComboTemplate(RUN_MIXED, start, int(points), None, (start, start + 1, start + 2))
        )
    for start, points in rules.run_same_color_scores.items():
        for color in rules.colors:
            templates.append(
                ComboTemplate(RUN_SAME, start, int(points), color, (start, start + 1, start + 2))
            )
    return templates


def _matches(template: ComboTemplate, cards: Sequence[Card]) -> Optional[List[int]]:
    """Slottaki kartlar sablona uyuyorsa, geriye kalan sayilari dondurur."""
    remaining = list(template.ranks)
    for card in cards:
        if template.color is not None and card.color != template.color:
            return None
        if card.rank not in remaining:
            return None
        remaining.remove(card.rank)
    if template.kind == RUN_MIXED and len(cards) == 3:
        # Uc kart da ayni renk olursa bu sablon degil, RUN_SAME gecerlidir
        if len({c.color for c in cards}) == 1:
            return None
    return remaining


# ----------------------------------------------------------------- degerleme


@dataclass
class SolverConfig:
    """Varsayilanlar parametre taramasiyla secildi (24 kart / en fazla 8 uclu).

    `empty_slot_factor` iki yerde birden kullaniliyor ve bu **bilincli**: hem
    acik ama bos ucluye hem de henuz baslamamis uclulere ayni deger veriliyor.
    Ikisi ayni sey cunku bir uclu tamamlandiginda yerine yeni bos bir uclu
    aciliyor. Ayri katsayilar denendiginde deger fonksiyonu tutarsizlasiyor:
    uclu tamamlamak sahte bir bedel kazaniyor, solver ucluleri kapatmaktan
    kacinip kart atmaya basliyor (245.9 -> 132.9 puan, 5.5 -> 3.3 uclu).

    `look_factor` acik uclu icin gorulmesi beklenen kart sayisi. Buyudukce
    solver "nasil olsa dogru kart gelir" diye dusunup fazla kart atiyor:
    look=4'te 3.4 uclu / 181 puan, look=1.2'de 4.8 uclu / 219 puan. Kart cekmek
    artik bedava olmadigi (uclu tamamlamak ya da kart atmak gerektigi) icin bu
    etki eskisinden daha sert.

    Her iki katsayi da sezgisel; gercekten iyi karar icin `rollouts` ac.
    """

    empty_slot_factor: float = 0.2     # henuz baslamamis bir uclunun degeri
    look_factor: float = 1.2           # acik uclu icin gorulmesi beklenen kart sayisi
    dead_slot_penalty: float = 0.0     # tamamlanamaz uclu icin ek ceza
    rollouts: int = 0                  # >0 ise Monte-Carlo ile dogrula (yavas ama iyi)
    rollout_candidates: int = 0        # 0 = TUM adaylari simule et. Sezgiselin ilk N'ini
                                       # almak, onun yanildigi hamleleri hic denememek demek.
    rollout_seed: Optional[int] = None


@dataclass
class ActionValue:
    action: Action
    value: float
    immediate_points: int
    note: str

    def to_dict(self) -> dict:
        return {
            "action": self.action.to_dict(),
            "value": round(self.value, 2),
            "immediate_points": self.immediate_points,
            "note": self.note,
        }


class Solver:
    def __init__(self, rules: Rules, config: Optional[SolverConfig] = None):
        self.rules = rules
        self.config = config or SolverConfig()
        self.templates = combo_templates(rules)
        self._best_points = max((t.points for t in self.templates), default=0)

    # ------------------------------------------------------------ potansiyel

    def _slot_potential(
        self,
        slot: Slot,
        unseen: Dict[Card, int],
        pool: int,
        hand: Sequence[Card],
        look: float,
    ) -> Tuple[float, str]:
        if slot.is_locked:
            return float(slot.result.points), "kilitli"
        if slot.is_full:
            # Dolu ama henuz tamamlanmamis: TAMAMLA'nin getirecegi puan
            pending = score_combo(slot.cards, self.rules)
            return float(pending.points), f"tamamla: {pending.label} +{pending.points}"

        cards = slot.cards
        if not cards:
            return self.config.empty_slot_factor * self._best_available(unseen), "bos"

        draws = max(1, int(round(look)))
        best_value = 0.0
        best_note = "olu"

        for template in self.templates:
            missing = _matches(template, cards)
            if missing is None:
                continue
            prob = 1.0
            hand_pool = list(hand)
            for rank in missing:
                # Elde uygun kart varsa o gereksinim kesin karsilanir
                held = next(
                    (c for c in hand_pool
                     if c.rank == rank and (template.color is None or c.color == template.color)),
                    None,
                )
                if held is not None:
                    hand_pool.remove(held)
                    continue
                successes = sum(
                    n for c, n in unseen.items()
                    if c.rank == rank and (template.color is None or c.color == template.color)
                )
                prob *= _hyper_at_least(successes, pool, draws, 1)
                if prob <= 0.0:
                    break
            value = template.points * prob
            if value > best_value:
                best_value = value
                best_note = f"{template.kind}:{template.key} p={prob:.2f}"

        if best_value <= 0.0:
            return -self.config.dead_slot_penalty, best_note
        return best_value, best_note

    def _best_available(self, unseen: Dict[Card, int]) -> float:
        """Kalan havuzda hala kurulabilecek en yuksek puanli kombinasyon."""
        best = 0
        for template in self.templates:
            ok = True
            needed: Dict[Tuple[int, Optional[str]], int] = {}
            for rank in template.ranks:
                needed[(rank, template.color)] = needed.get((rank, template.color), 0) + 1
            for (rank, color), count in needed.items():
                available = sum(
                    n for c, n in unseen.items()
                    if c.rank == rank and (color is None or c.color == color)
                )
                if available < count:
                    ok = False
                    break
            if ok and template.points > best:
                best = template.points
        return float(best)

    def potential(self, game: OkeyGame) -> float:
        """Durumun degeri: kazanilmis puan + acik uclunun beklentisi + gelecek uclular.

        Alanlar sirayla acildigi icin tek bir "acik uclu" vardir. Geriye kalan
        kartlar ise henuz baslamamis kombinasyonlara donusur; her 3 kart bir
        kombinasyon eder. Bir kart atmanin gercek bedeli bu yuzden bir
        kombinasyonun ucte biridir.
        """
        active = game.active_slot
        if active is None:
            return float(game.total_score)

        # Ucluye konmus kartlar artik "serbest" degil; gelecek uclulerin
        # hesabinda sayilmazlar, cunku yerleri belli.
        usable = game.usable_cards - len(game.staged)
        if usable < active.free:
            return float(game.total_score)

        unseen = game.unseen_counts()
        pool = game.cards_left
        total = float(game.total_score)
        value, _ = self._slot_potential(
            active, unseen, pool, game.hand, self._look_for(active)
        )
        total += value

        open_slots = sum(1 for slot in game.slots if not slot.is_locked)
        future = min(
            float(open_slots - 1),
            max(0.0, (usable - active.free) / self.rules.combo_size),
        )
        total += future * self.config.empty_slot_factor * self._best_available(unseen)
        return total

    def _look_for(self, slot: Slot) -> float:
        """Bu uclu icin gorulmesi beklenen kart sayisi."""
        return self.config.look_factor * max(1, slot.free)

    # --------------------------------------------------------------- hamleler

    def evaluate_actions(self, game: OkeyGame) -> List[ActionValue]:
        results: List[ActionValue] = []
        seen_signatures: set = set()

        for action in game.legal_actions():
            # Ayni karti iki kez degerlendirme (el kopya kart tasiyabilir)
            card = game.hand[action.card_index] if action.type != COMPLETE else None
            signature = (action.type, card)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)

            child = clone_for_search(game, planning=True)
            outcome = child.apply(action)
            value = self.potential(child)
            note = ""
            if outcome.completed:
                note = f"{outcome.completed.label} +{outcome.completed.points}"
            elif action.type == DISCARD:
                note = "kart at"
            elif outcome.slot_index is not None:
                slot = child.slots[outcome.slot_index]
                _, note = self._slot_potential(
                    slot, child.unseen_counts(), child.cards_left, child.hand,
                    self._look_for(slot),
                )
            results.append(ActionValue(action, value, outcome.points, note))

        results.sort(key=lambda r: (-r.value, -r.immediate_points))

        if self.config.rollouts > 0 and len(results) > 1:
            limit = self.config.rollout_candidates or len(results)
            if limit < len(results):
                # On eleme: TUM adaylari az sayida simulasyonla tara. Dogrudan
                # sezgisel siralamanin ilk N'ini almak, sezgiselin yanildigi
                # hamleleri hic denememek anlamina geliyordu.
                results = self._rollout_refine(
                    game, results, max(6, self.config.rollouts // 4), seed_offset=0)
                results.sort(key=lambda r: (-r.value, -r.immediate_points))
            # Finalistler yeni destelerde denenir; ayni desteleri tekrar
            # kullanmak on elemede sansli cikan adayi hakli cikarirdi.
            refined = self._rollout_refine(
                game, results[:limit], self.config.rollouts, seed_offset=1)
            refined.sort(key=lambda r: (-r.value, -r.immediate_points))
            return refined + results[limit:]
        return results

    def best_move(self, game: OkeyGame) -> Optional[Action]:
        ranked = self.evaluate_actions(game)
        return ranked[0].action if ranked else None

    def explain(self, game: OkeyGame, top: int = 5) -> List[dict]:
        return [r.to_dict() for r in self.evaluate_actions(game)[:top]]

    def completions(self, game: OkeyGame) -> List[dict]:
        """Acik ucluyu tek hamlede tamamlayan kartlar ve getirecekleri puan.

        Yalnizca bir bos yer kaldiginda anlamli. Arayuz bu listeden "bu kartlar
        gelirse su kadar puan" ve gelme olasiligini gosteriyor.
        """
        slot = game.active_slot
        if slot is None or slot.free != 1:
            return []

        best: Dict[Card, int] = {}
        for template in self.templates:
            missing = _matches(template, slot.cards)
            if missing is None or len(missing) != 1:
                continue
            rank = missing[0]
            colors = [template.color] if template.color else list(self.rules.colors)
            for color in colors:
                card = Card(rank, color)
                if template.points > best.get(card, -1):
                    best[card] = template.points

        rows = []
        for card, points in best.items():
            remaining = game.unseen.get(card, 0)
            in_hand = card in game.hand
            if not remaining and not in_hand:
                continue
            rows.append({
                "rank": card.rank, "color": card.color, "points": points,
                "remaining": remaining, "in_hand": in_hand,
            })
        rows.sort(key=lambda r: (-r["points"], r["rank"]))
        return rows

    def describe_target(self, game: OkeyGame) -> str:
        """Acik uclunun neyi hedefledigini insan diliyle anlatir."""
        slot = game.active_slot
        if slot is None:
            return "tum ucluler tamamlandi"
        if not slot.cards:
            return "yeni uclu"

        unseen = game.unseen_counts()
        best: Optional[Tuple[float, ComboTemplate, float]] = None
        for template in self.templates:
            missing = _matches(template, slot.cards)
            if missing is None:
                continue
            prob = 1.0
            hand_pool = list(game.hand)
            for rank in missing:
                held = next(
                    (c for c in hand_pool
                     if c.rank == rank and (template.color is None or c.color == template.color)),
                    None,
                )
                if held is not None:
                    hand_pool.remove(held)
                    continue
                successes = sum(
                    n for c, n in unseen.items()
                    if c.rank == rank and (template.color is None or c.color == template.color)
                )
                prob *= _hyper_at_least(successes, game.cards_left,
                                        max(1, int(round(self._look_for(slot)))), 1)
                if prob <= 0.0:
                    break
            value = template.points * prob
            if best is None or value > best[0]:
                best = (value, template, prob)

        if best is None or best[0] <= 0.0:
            return "bu uclu tamamlanamaz, 0 puan"
        _, template, prob = best
        pattern = (f"{template.key}-{template.key}-{template.key}" if template.kind == GROUP
                   else f"{template.key}-{template.key + 1}-{template.key + 2}")
        colored = " ayni renk" if template.kind == RUN_SAME else ""
        return f"hedef {pattern}{colored} ({template.points} puan, sans %{prob * 100:.0f})"

    def plan(self, game: OkeyGame, max_steps: Optional[int] = None) -> List[Action]:
        """Eldeki kartlarla yapilacak islem dizisi.

        Plan bilerek kisa tutulur, cunku her islemden sonra yerine yeni bir kart
        gelir ve o kart karari degistirebilir:

        * Ilk hamle bir kart atmaksa plan orada biter (gelen karti gormeden
          ust uste kart atmak, tum eli bosaltmaya kadar gidiyor).
        * Kart koymaksa, ayni acik uclu uzerinde calismaya devam edilir; uclu
          dolunca plan biter.
        """
        limit = max_steps or self.rules.combo_size + 1
        sim = clone_for_search(game, planning=True)
        target_slot = sim.active_slot_index
        actions: List[Action] = []

        while len(actions) < limit and not sim.is_over:
            move = self.best_move(sim)
            if move is None:
                break
            if move.type == COMPLETE:
                sim.apply(move)
                actions.append(move)
                break
            if move.type == DISCARD:
                if actions:
                    break              # koyma dizisinin ardina atma ekleme
                sim.apply(move)
                actions.append(move)
                break                  # tek atma, sonra yeni karta bak
            if sim.active_slot_index != target_slot:
                break                  # baska ucluye gecildi
            sim.apply(move)
            actions.append(move)
            if sim.can_complete:
                # Uclu doldu: tamamlama adimini plana ekle ve dur
                sim.apply(COMPLETE_ACTION)
                actions.append(COMPLETE_ACTION)
                break
        return actions

    # -------------------------------------------------------------- rollouts

    def _rollout_refine(self, game: OkeyGame, candidates: List[ActionValue],
                        rollouts: Optional[int] = None,
                        seed_offset: int = 0) -> List[ActionValue]:
        """Adaylari, destenin bilinmeyen sirasini rastgele ornekleyerek dogrular.

        Butun adaylar **ayni** deste sirasi kumesinde denenir (common random
        numbers). Her adaya farkli desteler verildiginde karsilastirma neredeyse
        tamamen gurultu oluyordu: tur puanlarinin standart sapmasi ~60, yani 40
        simulasyonla tek bir adayin hatasi +-10 puan. Ayni desteler kullanilinca
        adaylar arasindaki fark eslestirilmis olarak olculuyor ve ayni sayida
        simulasyonla cok daha guvenilir siralama cikiyor.
        """
        rng = random.Random((self.config.rollout_seed or 0) + seed_offset)
        greedy = Solver(self.rules, SolverConfig(
            empty_slot_factor=self.config.empty_slot_factor,
            look_factor=self.config.look_factor,
            dead_slot_penalty=self.config.dead_slot_penalty,
            rollouts=0,
        ))
        count = rollouts or self.config.rollouts
        base_pool: List[Card] = [c for c, n in game.unseen.items() for _ in range(n)]
        decks: List[List[Card]] = []
        for _ in range(count):
            deck = list(base_pool)
            rng.shuffle(deck)
            decks.append(deck)

        refined: List[ActionValue] = []
        for candidate in candidates:
            scores: List[int] = []
            for deck in decks:
                sim = simulated_continuation(game, deck=deck)
                sim.apply(candidate.action)
                while not sim.is_over:
                    move = greedy.best_move(sim)
                    if move is None:
                        break
                    sim.apply(move)
                scores.append(sim.total_score)
            mean = sum(scores) / len(scores) if scores else candidate.value
            refined.append(ActionValue(
                candidate.action, mean, candidate.immediate_points,
                f"beklenen tur puani {mean:.0f} ({count} simulasyon)",
            ))
        return refined


def simulated_continuation(game: OkeyGame, rng: Optional[random.Random] = None,
                           deck: Optional[Sequence[Card]] = None) -> OkeyGame:
    """Gorulmemis havuzu rastgele siralayarak oynanabilir bir kopya uretir.

    Canli modda deste sirasi bilinmez; rollout yapabilmek icin havuz karistirilip
    kopya simulasyon moduna alinir. Gercek kart sirasi hakkinda bilgi sizmaz.
    `deck` verilirse o sira kullanilir; boylece farkli adaylar ayni desteler
    uzerinde karsilastirilabilir.

    Kopya bilerek **kart cekmeden** dondurulur: once hamle yapilir, kart sonra
    gelir. Onceden cekilseydi kisa bir el doldurulurken havuz tukenebilir ve ana
    oyunda gecerli olan "kart at" hamlesi kopyada gecersizlesirdi.
    """
    sim = clone_for_search(game)
    if deck is not None:
        pool = list(deck)
    else:
        pool = [card for card, count in sim.unseen.items() for _ in range(count)]
        (rng or random).shuffle(pool)
    sim.deck = pool
    sim.live = False
    sim.planning = False
    sim.pending_draws = 0
    if sim.phase != PHASE_FINISHED:
        sim.phase = PHASE_PLAYING
    return sim


def play_greedy(game: OkeyGame, solver: Solver) -> OkeyGame:
    """Tek turu bastan sona solver ile oynatir (test/benchmark icin)."""
    game.open_deck()
    while not game.is_over:
        move = solver.best_move(game)
        if move is None:
            break
        game.apply(move)
    return game
