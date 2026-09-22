"""LLM agent'a gonderilen sistem/kullanici mesajlarini uretir."""
from __future__ import annotations

from typing import Dict, List

from ..cards import Card, CardCodec
from ..engine import OkeyGame
from ..rules import Rules
from ..solver import combo_templates

SYSTEM_PROMPT = """Sen Metin2 Okey mini oyununu oynayan bir uzmansin. Amacin TEK TURDA
mumkun olan en yuksek toplam puani toplamak. Gecmis turlar onemsizdir.

OYUN NASIL ISLIYOR
- Elinde en fazla {hand_size} acik kart var.
- Onunde TEK BIR uclu alan var (3 yer). Kartlari ancak buraya koyabilirsin.
- Uclu dolunca puanlanip KILITLENIR ve yerine yeni bos bir uclu acilir.
  Dolmadan bir sonraki ucluye gecemezsin.
- Bir karti AT'arsan kart kalici olarak yok olur.
- Desteden kart cekebilmen icin ya ucluyu tamamlaman ya da kart atman gerekir.
  Ucluye koydugun ama henuz tamamlamadigin kartlarin yerine kart gelmez.
- Deste bitince oyun biter.

BIR KART ATMANIN BEDELI
Her 3 kart, bir uclu demektir. Attigin her 3 kart, kuramayacagin bir uclu
anlamina gelir; yani bir kart atmak yaklasik bir uclunun UCTE BIRI kadar puana
mal olur. Sirf "daha iyi kart gelsin" diye kart atma; attigin kart, acik ucluye
koysan kac puan getirecegiyle karsilastir.

PUANLAMA
{scoring_table}

STRATEJI
- Acik ucluye hangi karti koyacagin en kritik karar. Uclu dolunca kilitlenir.
- Ayni renkli buyuk seriler (6-7-8 ayni renk = 100) ve yuksek gruplar
  (8-8-8 = 90) en degerlidir.
- Ucluye ikinci karti koymadan once dusun: ucuncu karti tamamlayacak kart
  destede hala var mi? Sana "DESTEDE KALANLAR" listesi veriliyor.
- Tamamlanamaz hale gelmis bir ucluyu (0 puan) kapatmak icin en degersiz
  kartlari kullan, iyi kartlarini harcama.
- Dusuk puanli ama garanti bir uclu, tamamlanma ihtimali dusuk yuksek puanli bir
  ucluden cogu zaman daha iyidir.

CEVAP BICIMI
Sadece gecerli JSON dondur, baska hicbir sey yazma:
{{"plan": [{{"action": "place", "card": "8r"}}, {{"action": "discard", "card": "1g"}}],
  "reason": "<en fazla 15 kelimelik gerekce>"}}

- "action" sadece "place" veya "discard" olabilir.
- "card" elindeki kartlardan biri olmali, sana gosterilen yazimla (or. "7r").
- plan icinde 1 ile {hand_size} arasinda adim olabilir; adimlar sirayla uygulanir.
- Acik uclu dolduktan SONRASI icin adim ekleme; yeni kartlari gormeden karar verme.
- Emin degilsen tek adimlik plan ver."""


def scoring_table_text(rules: Rules) -> str:
    groups = ", ".join(f"{r}-{r}-{r}={p}" for r, p in sorted(rules.group_scores.items()))
    mixed = ", ".join(f"{s}-{s+1}-{s+2}={p}" for s, p in sorted(rules.run_mixed_scores.items()))
    same = ", ".join(f"{s}-{s+1}-{s+2}={p}" for s, p in sorted(rules.run_same_color_scores.items()))
    return (
        f"- Grup (ayni sayidan 3 kart): {groups}\n"
        f"- Seri (ardisik 3 sayi, en az biri farkli renk): {mixed}\n"
        f"- Seri (ardisik 3 sayi, ucu de ayni renk): {same}\n"
        f"- Bunlarin disindaki her uclu: {rules.invalid_score} puan"
    )


def build_system_prompt(rules: Rules) -> str:
    return SYSTEM_PROMPT.format(
        scoring_table=scoring_table_text(rules), hand_size=rules.hand_size
    )


def _completion_hints(game: OkeyGame, codec: CardCodec) -> str:
    """Acik ucluyu hangi kart kac puana tamamlar."""
    slot = game.active_slot
    if slot is None or not slot.cards:
        return ""
    templates = combo_templates(game.rules)
    options: Dict[str, int] = {}
    for template in templates:
        remaining = _remaining_for(template, slot.cards)
        if remaining is None or len(remaining) != 1:
            continue
        rank = remaining[0]
        colors = [template.color] if template.color else list(game.rules.colors)
        for color in colors:
            card = Card(rank, color)
            available = game.unseen.get(card, 0)
            in_hand = any(c == card for c in game.hand)
            where = "ELINDE" if in_hand else (f"destede {available}" if available else "yok")
            label = f"{codec.label(card)}({where})"
            if template.points > options.get(label, -1):
                options[label] = template.points
    if not options:
        return "    tamamlanamaz -> bu uclu 0 puan, en degersiz kartlarla kapat"
    ranked = sorted(options.items(), key=lambda kv: -kv[1])
    return "    tamamlayanlar: " + ", ".join(f"{k}={v}p" for k, v in ranked[:8])


def _remaining_for(template, cards) -> List[int] | None:
    remaining = list(template.ranks)
    for card in cards:
        if template.color is not None and card.color != template.color:
            return None
        if card.rank not in remaining:
            return None
        remaining.remove(card.rank)
    return remaining


def _unseen_text(game: OkeyGame, codec: CardCodec) -> str:
    by_color: Dict[str, List[int]] = {c: [] for c in game.rules.colors}
    for card, count in game.unseen.items():
        by_color.setdefault(card.color, []).extend([card.rank] * count)
    parts = []
    for color, ranks in by_color.items():
        code = codec.to_code.get(color, color)
        parts.append(f"{color} ({code}): {sorted(ranks) if ranks else '-'}")
    return "\n  ".join(parts)


def _locked_text(game: OkeyGame, codec: CardCodec) -> str:
    rows = []
    for slot in game.slots:
        if slot.is_full and slot.result:
            cards = " ".join(codec.label(c) for c in slot.cards)
            rows.append(f"  #{len(rows) + 1}: {cards} -> {slot.result.label} {slot.result.points}p")
    return "\n".join(rows) if rows else "  (henuz yok)"


def build_user_prompt(game: OkeyGame, codec: CardCodec, with_hints: bool = True) -> str:
    slot = game.active_slot
    placed = " ".join(codec.label(c) for c in slot.cards) if slot and slot.cards else "-"
    free = slot.free if slot else 0
    hand = " ".join(codec.label(c) for c in game.hand) or "-"
    discards = " ".join(codec.label(c) for c in game.discards) or "-"
    hints = _completion_hints(game, codec) if with_hints else ""

    return (
        f"DURUM\n"
        f"  toplam puan: {game.total_score}\n"
        f"  tamamlanan uclu: {game.combos_done}\n"
        f"  destede kalan kart: {game.cards_left}\n"
        f"  bu kartlarla en fazla {game.combos_possible} uclu daha kurabilirsin\n"
        f"  attigin kartlar: {discards}\n\n"
        f"ACIK UCLU (tek acik alan)\n"
        f"    icinde: [{placed}]  ({free} bos yer)\n"
        f"    su an desteden cekebilecegin kart: {game.draw_count}\n"
        f"{hints}\n\n"
        f"KILITLENEN UCLULER\n{_locked_text(game, codec)}\n\n"
        f"ELIN: {hand}\n"
        f"  (yazim: sayi + renk kodu, or. 7r = 7 kirmizi)\n\n"
        f"DESTEDE KALANLAR (henuz gorulmemis)\n  {_unseen_text(game, codec)}\n\n"
        f"Acik ucluyu en yuksek puanla kapatmayi hedefle. Planini JSON olarak ver."
    )
