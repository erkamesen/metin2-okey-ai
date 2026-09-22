"""Okey mini oyununun kural motoru.

Tur akisi (gercek oyundaki gibi):

    1. Elinde `hand_size` kart var, onunde bos bir 3'lu alan.
    2. Kartlari ucluye KOYarsin (geri de alabilirsin, henuz kilitlenmedi) ya da
       elindeki kartlari YOK EDersin.
    3. Uclu dolunca TAMAMLA ile puanlanip kilitlenir, yerine yeni bos uclu gelir.
    4. Ancak bundan sonra desteden kart CEKebilirsin; el tekrar `hand_size`
       olana kadar kart gelir. Ucluye konmus ama tamamlanmamis kartlar "hala
       masada" sayilir, onlarin yerine kart gelmez.

Iki calisma modu var:

* **canli (live=True)** — asil kullanim. Kartlari oyuncu gercek oyundan okuyup
  girer; motor sadece hangi kartlarin gorulmedigini takip eder (kart sayma).
* **simulasyon (live=False)** — solver'i olcmek icin. Deste karistirilir,
  cekilen kartlar otomatik gelir.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .cards import Card, build_deck, counter_of, shuffled_deck
from .rules import Rules
from .scoring import ComboResult, score_combo

PLACE = "place"
DISCARD = "discard"
COMPLETE = "complete"

PHASE_READY = "ready"              # simulasyon: deste henuz acilmadi
PHASE_AWAITING = "awaiting_cards"  # canli: oyuncunun kart girmesi bekleniyor
PHASE_PLAYING = "playing"
PHASE_FINISHED = "finished"


class InvalidCard(ValueError):
    """Girilen kart destede kalmamis ya da hic yok."""


class InvalidMove(ValueError):
    """Kurallara uymayan hamle."""


@dataclass(frozen=True)
class Action:
    type: str                         # PLACE | DISCARD | COMPLETE
    card_index: int = -1              # eldeki kartin indeksi (COMPLETE icin -1)
    slot_index: Optional[int] = None  # PLACE icin hedef alan (None = acik uclu)

    def to_dict(self) -> dict:
        return {"type": self.type, "card_index": self.card_index, "slot_index": self.slot_index}

    @classmethod
    def from_dict(cls, data: dict) -> "Action":
        slot = data.get("slot_index")
        return cls(
            type=str(data["type"]).lower(),
            card_index=int(data.get("card_index", -1)),
            slot_index=None if slot is None else int(slot),
        )

    def __str__(self) -> str:
        if self.type == PLACE:
            return f"place(card={self.card_index}, slot={self.slot_index})"
        if self.type == COMPLETE:
            return "complete()"
        return f"discard(card={self.card_index})"


COMPLETE_ACTION = Action(COMPLETE)


@dataclass
class Slot:
    """Tahtadaki tek bir 3'lu kombinasyon alani.

    `result` doldugu anda degil, TAMAMLA ile puanlandiginda dolar. O ana kadar
    kartlar geri alinabilir.
    """

    index: int
    capacity: int
    cards: List[Card] = field(default_factory=list)
    result: Optional[ComboResult] = None

    @property
    def is_full(self) -> bool:
        return len(self.cards) >= self.capacity

    @property
    def is_locked(self) -> bool:
        return self.result is not None

    @property
    def free(self) -> int:
        return self.capacity - len(self.cards)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "capacity": self.capacity,
            "cards": [c.to_dict() for c in self.cards],
            "is_full": self.is_full,
            "is_locked": self.is_locked,
            "result": self.result.to_dict() if self.result else None,
        }


@dataclass
class MoveOutcome:
    """Bir hamlenin sonucu; loglama ve UI bu nesneyi kullanir."""

    move_no: int
    action: Action
    card: Optional[Card]
    slot_index: Optional[int]
    completed: Optional[ComboResult]
    points: int
    total_score: int
    cards_left: int
    draw_count: int
    finished: bool

    def to_dict(self) -> dict:
        return {
            "move_no": self.move_no,
            "action": self.action.to_dict(),
            "card": self.card.to_dict() if self.card else None,
            "slot_index": self.slot_index,
            "completed": self.completed.to_dict() if self.completed else None,
            "points": self.points,
            "total_score": self.total_score,
            "cards_left": self.cards_left,
            "draw_count": self.draw_count,
            "finished": self.finished,
        }


class OkeyGame:
    """Tek bir okey turu. Her tur bagimsizdir, gecmis tur bilgisi tasimaz."""

    def __init__(
        self,
        rules: Rules,
        seed: Optional[int] = None,
        game_id: Optional[str] = None,
        live: bool = True,
    ):
        self.rules = rules
        self.live = live
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.rng = random.Random(self.seed)
        self.game_id = game_id or f"g{self.seed:010d}"

        # Henuz gorulmemis kartlar; kart sayma mekanizmasinin tek dogruluk kaynagi.
        self.unseen: Dict[Card, int] = counter_of(
            build_deck(rules.ranks, rules.colors, rules.copies)
        )
        # Sadece simulasyonda: hangi kartin sirada oldugu.
        self.deck: List[Card] = (
            [] if live else shuffled_deck(rules.ranks, rules.colors, rules.copies, self.rng)
        )

        self.hand: List[Card] = []
        self.discards: List[Card] = []
        self.slots: List[Slot] = [Slot(i, rules.combo_size) for i in range(rules.slots)]
        self.total_score = 0
        self.move_no = 0
        self.pending_draws = 0
        self.planning = False        # plan uretirken kart cekmeyi kapatir
        self.history: List[MoveOutcome] = []
        self._undo_stack: List[dict] = []

        if live:
            self.phase = PHASE_AWAITING
            self.pending_draws = min(rules.hand_size, self.cards_left)
        else:
            self.phase = PHASE_READY

    # ------------------------------------------------------------------ durum

    @property
    def cards_left(self) -> int:
        """Destede kalan (henuz gorulmemis) kart sayisi."""
        return sum(self.unseen.values())

    @property
    def is_over(self) -> bool:
        return self.phase == PHASE_FINISHED

    @property
    def active_slot(self) -> Optional[Slot]:
        """Onunde duran uclu — kilitlenmemis ilk alan.

        Ayni anda tek bir uclu aciktir; tamamlanip kilitlenmeden sonrakine
        gecilmez.
        """
        for slot in self.slots:
            if not slot.is_locked:
                return slot
        return None

    @property
    def active_slot_index(self) -> Optional[int]:
        slot = self.active_slot
        return None if slot is None else slot.index

    @property
    def can_complete(self) -> bool:
        slot = self.active_slot
        return slot is not None and slot.is_full and not slot.is_locked

    @property
    def pending_combo(self) -> Optional[ComboResult]:
        """Acik uclu doluysa TAMAMLA'nin getirecegi puan (henuz islenmedi)."""
        if not self.can_complete:
            return None
        return score_combo(self.active_slot.cards, self.rules)

    @property
    def combos_done(self) -> int:
        return sum(1 for slot in self.slots if slot.is_locked)

    filled_slots = combos_done   # eski isim

    @property
    def staged(self) -> List[Card]:
        """Ucluye konmus ama henuz tamamlanmamis kartlar."""
        slot = self.active_slot
        return list(slot.cards) if slot and not slot.is_locked else []

    @property
    def draw_count(self) -> int:
        """Su anda desteden kac kart cekebilirsin.

        Ucluye konmus ama tamamlanmamis kartlar hala masada sayilir; onlarin
        yerine kart gelmez. Bu yuzden ucluyu tamamlamadan ya da kart yok
        etmeden kart cekilemez.
        """
        if self.phase == PHASE_FINISHED:
            return 0
        room = self.rules.hand_size - len(self.hand) - len(self.staged) - self.pending_draws
        return max(0, min(room, self.cards_left))

    @property
    def usable_cards(self) -> int:
        """Elde + masada + gelecek + destede kalan kart sayisi."""
        return len(self.hand) + len(self.staged) + self.pending_draws + self.cards_left

    @property
    def combos_possible(self) -> int:
        """Su andan itibaren en fazla kac uclu daha tamamlanabilir.

        Attigin her 3 kart bu sayiyi 1 azaltir; bir kart atmanin gercek bedeli
        budur.
        """
        active = self.active_slot
        if active is None:
            return 0
        need = active.free
        usable = self.usable_cards - len(self.staged)   # masadakiler zaten yerinde
        if usable < need:
            return 0
        open_slots = sum(1 for slot in self.slots if not slot.is_locked)
        return min(open_slots, 1 + (usable - need) // self.rules.combo_size)

    def unseen_counts(self) -> Dict[Card, int]:
        return dict(self.unseen)

    # ------------------------------------------------------------- kart akisi

    def open_deck(self) -> None:
        """Simulasyonda 'desteye tikla, ilk kartlari ac' adimi."""
        if self.phase != PHASE_READY:
            return
        self.phase = PHASE_PLAYING
        self._draw_simulated()
        self._check_finished()

    def _take_unseen(self, card: Card) -> None:
        remaining = self.unseen.get(card, 0)
        if remaining <= 0:
            raise InvalidCard(f"{card} destede kalmadi (zaten gorulmus ya da hic yok)")
        if remaining == 1:
            del self.unseen[card]
        else:
            self.unseen[card] = remaining - 1

    def _draw_simulated(self) -> None:
        while self.draw_count > 0 and self.deck:
            card = self.deck.pop()
            self._take_unseen(card)
            self.hand.append(card)

    def request_draw(self) -> int:
        """Desteden kart ister; kac kart bekledigini dondurur."""
        if self.phase == PHASE_FINISHED:
            return 0
        if not self.live:
            self._draw_simulated()
            return 0
        count = self.draw_count
        if count <= 0:
            return 0
        self._push_undo()
        self.pending_draws += count
        self.phase = PHASE_AWAITING
        return self.pending_draws

    def provide_cards(self, cards: Sequence[Card]) -> List[Card]:
        """Oyuncunun gordugu kartlari ele ekler ve destede kalanlardan duser.

        Beklenenden az kart girilebilir; kalanlar icin beklemeye devam edilir.
        """
        if not self.live:
            raise InvalidMove("kart girisi sadece canli modda kullanilir")
        if self.phase == PHASE_FINISHED:
            raise InvalidMove("tur bitti")
        if not cards:
            return []
        if self.pending_draws == 0:
            if self.draw_count == 0:
                raise InvalidMove(
                    "simdi kart cekemezsin — once acik ucluyu tamamla ya da kart yok et"
                )
            self.pending_draws = self.draw_count
        if len(cards) > self.pending_draws:
            raise InvalidCard(
                f"{self.pending_draws} kart bekleniyor, {len(cards)} kart girildi"
            )

        self._push_undo()
        added: List[Card] = []
        try:
            for card in cards:
                self._take_unseen(card)
                self.hand.append(card)
                self.pending_draws -= 1
                added.append(card)
        except InvalidCard:
            self.undo()          # yarim kalan girisi geri al
            raise

        if self.pending_draws == 0:
            self.phase = PHASE_PLAYING
        self._check_finished()
        return added

    def stop_waiting(self) -> None:
        """'Destede kart kalmamis, yeni kart gelmedi' durumu."""
        if not self.live:
            return
        self._push_undo()
        self.pending_draws = 0
        self.unseen.clear()
        if self.phase == PHASE_AWAITING:
            self.phase = PHASE_PLAYING
        self._check_finished()

    def _check_finished(self) -> None:
        if self.phase == PHASE_FINISHED:
            return
        active = self.active_slot
        if active is None:                       # tum ucluler tamamlandi
            self.phase = PHASE_FINISHED
        elif not active.is_full and self.usable_cards < active.free:
            self.phase = PHASE_FINISHED          # acik uclu artik tamamlanamaz

    # -------------------------------------------------------------- hamleler

    @property
    def can_act(self) -> bool:
        """Kart bekleniyor olsa bile eldeki kartlarla oynanabilir."""
        return self.phase != PHASE_FINISHED

    def legal_actions(self) -> List[Action]:
        if not self.can_act:
            return []
        active = self.active_slot
        if active is None:
            return []

        if self.can_complete:
            # Uclu dolu: ya tamamla ya da elinden kart yok et
            actions = [COMPLETE_ACTION]
        else:
            actions = [Action(PLACE, index) for index in range(len(self.hand))]
        if self.cards_left or self.pending_draws:
            actions += [Action(DISCARD, index) for index in range(len(self.hand))]
        return actions

    def is_legal(self, action: Action) -> bool:
        if not self.can_act:
            return False
        active = self.active_slot
        if active is None:
            return False

        if action.type == COMPLETE:
            return self.can_complete
        if not (0 <= action.card_index < len(self.hand)):
            return False
        if action.type == DISCARD:
            return bool(self.cards_left or self.pending_draws)
        if action.type != PLACE:
            return False
        if active.is_full:
            return False
        return action.slot_index in (None, active.index)

    def find_card(self, card: Card) -> int:
        """Eldeki kartin indeksi. Kopya varsa ilkini verir."""
        for index, held in enumerate(self.hand):
            if held == card:
                return index
        raise InvalidCard(f"{card} elinde yok")

    def apply(self, action: Action) -> MoveOutcome:
        if not self.is_legal(action):
            raise InvalidMove(f"gecersiz hamle: {action} (faz={self.phase})")

        self._push_undo()
        self.move_no += 1
        slot = self.active_slot
        card: Optional[Card] = None
        completed: Optional[ComboResult] = None
        points = 0
        slot_index = None

        if action.type == COMPLETE:
            completed = score_combo(slot.cards, self.rules)
            slot.result = completed
            points = completed.points
            self.total_score += points
            slot_index = slot.index
        elif action.type == PLACE:
            card = self.hand.pop(action.card_index)
            slot.cards.append(card)
            slot_index = slot.index
        else:
            card = self.hand.pop(action.card_index)
            self.discards.append(card)

        if not self.planning and not self.live:
            self._draw_simulated()

        self._check_finished()
        outcome = MoveOutcome(
            move_no=self.move_no,
            action=action,
            card=card,
            slot_index=slot_index,
            completed=completed,
            points=points,
            total_score=self.total_score,
            cards_left=self.cards_left,
            draw_count=self.draw_count,
            finished=self.phase == PHASE_FINISHED,
        )
        self.history.append(outcome)
        return outcome

    def complete(self) -> MoveOutcome:
        """Acik ucluyu puanlayip kilitler."""
        return self.apply(COMPLETE_ACTION)

    def take_back(self, position: int) -> Card:
        """Ucluye konmus bir karti ele geri alir (henuz tamamlanmadiysa)."""
        slot = self.active_slot
        if slot is None or slot.is_locked:
            raise InvalidMove("geri alinacak kart yok")
        if not (0 <= position < len(slot.cards)):
            raise InvalidMove(f"ucluede {position}. sirada kart yok")
        self._push_undo()
        card = slot.cards.pop(position)
        self.hand.append(card)
        return card

    # ------------------------------------------------------------- geri alma

    def _push_undo(self, limit: int = 60) -> None:
        if self.planning:
            return
        self._undo_stack.append({
            "hand": list(self.hand),
            "slots": [(list(s.cards), s.result) for s in self.slots],
            "discards": list(self.discards),
            "unseen": dict(self.unseen),
            "deck": list(self.deck),
            "pending_draws": self.pending_draws,
            "phase": self.phase,
            "total_score": self.total_score,
            "move_no": self.move_no,
            "history_len": len(self.history),
        })
        del self._undo_stack[:-limit]

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def undo(self) -> bool:
        """Son islemi (hamle, kart girisi ya da geri alma) iptal eder."""
        if not self._undo_stack:
            return False
        snapshot = self._undo_stack.pop()
        self.hand = snapshot["hand"]
        for slot, (cards, result) in zip(self.slots, snapshot["slots"]):
            slot.cards = cards
            slot.result = result
        self.discards = snapshot["discards"]
        self.unseen = snapshot["unseen"]
        self.deck = snapshot["deck"]
        self.pending_draws = snapshot["pending_draws"]
        self.phase = snapshot["phase"]
        self.total_score = snapshot["total_score"]
        self.move_no = snapshot["move_no"]
        del self.history[snapshot["history_len"]:]
        return True

    # ----------------------------------------------------------------- ozet

    def chest(self) -> dict:
        tier = self.rules.chest_for(self.total_score)
        return {"chest": tier.chest, "label": tier.label, "min_score": tier.min_score}

    def to_dict(self) -> dict:
        pending = self.pending_combo
        return {
            "game_id": self.game_id,
            "seed": self.seed,
            "live": self.live,
            "phase": self.phase,
            "move_no": self.move_no,
            "total_score": self.total_score,
            "max_score": self.rules.max_score,
            "hand": [c.to_dict() for c in self.hand],
            "slots": [s.to_dict() for s in self.slots],
            "discards": [c.to_dict() for c in self.discards],
            "cards_left": self.cards_left,
            "pending_draws": self.pending_draws,
            "draw_count": self.draw_count,
            "can_complete": self.can_complete,
            "pending_combo": pending.to_dict() if pending else None,
            "combos_done": self.combos_done,
            "total_slots": self.rules.slots,
            "active_slot": self.active_slot_index,
            "combos_possible": self.combos_possible,
            "usable_cards": self.usable_cards,
            "hand_size": self.rules.hand_size,
            "unseen": sorted(
                ({"rank": c.rank, "color": c.color, "count": n} for c, n in self.unseen.items()),
                key=lambda d: (d["rank"], d["color"]),
            ),
            "can_undo": self.can_undo and not self.is_over,
            "is_over": self.is_over,
            "chest": self.chest(),
        }

    def summary(self) -> dict:
        kinds: Dict[str, int] = {}
        for slot in self.slots:
            if slot.result:
                kinds[slot.result.kind] = kinds.get(slot.result.kind, 0) + 1
        placements = sum(1 for h in self.history if h.action.type == PLACE)
        discards = sum(1 for h in self.history if h.action.type == DISCARD)
        return {
            "game_id": self.game_id,
            "seed": self.seed,
            "total_score": self.total_score,
            "max_score": self.rules.max_score,
            "moves": self.move_no,
            "placements": placements,
            "discards": discards,
            "filled_slots": self.combos_done,
            "total_slots": self.rules.slots,
            "combo_kinds": kinds,
            "chest": self.chest(),
        }


def clone_for_search(game: OkeyGame, planning: bool = False) -> OkeyGame:
    """Solver'in ileriye bakmasi icin hafif kopya.

    `planning=True` ise kopya yeni kart cekmez; boylece eldeki kartlarla
    yapilabilecek hamle dizisi (plan) uretilebilir.
    """
    copy = OkeyGame.__new__(OkeyGame)
    copy.rules = game.rules
    copy.live = game.live
    copy.seed = game.seed
    copy.rng = random.Random(0)
    copy.game_id = game.game_id
    copy.unseen = dict(game.unseen)
    copy.deck = list(game.deck)
    copy.hand = list(game.hand)
    copy.discards = list(game.discards)
    copy.slots = [Slot(s.index, s.capacity, list(s.cards), s.result) for s in game.slots]
    copy.total_score = game.total_score
    copy.move_no = game.move_no
    copy.pending_draws = game.pending_draws
    copy.planning = planning
    copy.phase = game.phase
    copy.history = []
    copy._undo_stack = []
    return copy
