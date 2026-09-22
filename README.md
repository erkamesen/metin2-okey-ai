# Metin2 Okey — Canlı Danışman

Sen gerçek oyunu oynarsın; gördüğün kartları buraya girersin, uygulama **"şu kartı
açık üçlüye koy, şu kartı yok et"** der. Motor destede hangi kartların kaldığını
takip eder (kart sayma), agent ona göre karar verir, her tur CSV'ye yazılır.

```
okey/
  cards.py      kart, deste, kısa yazım ("7r" = 7 kırmızı)
  rules.py      config/rules.yaml okuyucu
  scoring.py    kombinasyon tipleri ve puan tablosu
  engine.py     oyun akışı — sıralı üçlüler, elle kart girişi, geri alma
  solver.py     deterministik karar motoru (kart sayma + olasılık)
  logbook.py    stages.csv / games.csv yazıcı
  session.py    oyun + agent + log birleştirici
  agents/       LLM (ollama) ve hibrit karar vericiler
  web/          FastAPI sunucu + kart arayüzü
config/rules.yaml   TÜM kurallar burada
logs/               CSV kayıtları
```

## Çalıştırma

```powershell
# Danışman arayüzü -> http://127.0.0.1:8000
.\.venv\Scripts\python.exe run_web.py

# Solver'ı ölçmek / ayarlamak (gerçek oyun değil, simülasyon)
.\.venv\Scripts\python.exe simulate.py --games 400 --agent solver --quiet --no-log

# Testler
.\.venv\Scripts\python.exe -m pytest tests -q
```

## Nasıl kullanılır

1. **Yeni Tur** → uygulama ilk 5 kartı ister.
2. Kartları gir: sağdaki kart tablosundan tıkla, ya da `7r 4b 1g 3r 3g` diye yaz.
   Girdiğin kart destede kalanlardan düşülür; daha önce görülmüş bir kartı
   giremezsin.
   Kartı üçlüye **sürükleyip bırakabilir**, sol tıkla koyabilir, sağ tıkla yok
   edebilirsin. Üçlüdeki bir karta tıklarsan geri alırsın. Üçlü dolunca yeşil
   **Tamamla** düğmesi çıkar (puanı üstünde yazar); kart çekme hakkın doğunca da
   **Kart Çek** düğmesi.
3. **Öneri Al** → agent planı verir. Kritik bir kararda **Derin Analiz** düğmesi
   aynı pozisyonu Monte-Carlo ile çözer (her aday hamle için turun sonuna kadar
   onlarca simülasyon). Yavaş (~10-20 sn) ama sezgisel değerlendirmenin
   yanıldığı yerlerde isabetli. Örnek plan:
   > *Seri (aynı renk) tamamlanıyor: +100 puan*
   > 1. **6r** kartını açık üçlüye koy
   > 2. **7r** kartını açık üçlüye koy
   > 3. **8r** kartını açık üçlüye koy — üçlü tamamlanır: +100
4. Oyunda yap, **Yaptım** (tek adım) ya da **Hepsini yaptım** de.
5. Yerine gelen kartları gir, 3. adıma dön. Deste bitene kadar böyle sürer.

Yanlış kart girersen **Geri Al** son işlemi (hamle ya da kart girişi) iptal eder.
Öneriye uymak zorunda değilsin: elindeki karta **sol tık** açık üçlüye koyar,
**sağ tık** yok eder.

### Olasılıklar

Ekranın ortasında, destede kalan her kartın gelme şansı yazıyor. Üstteki
**1 / 3 / 5 / 10 çekiş** düğmeleriyle ufku değiştirirsin: *"kırmızı 7 bekliyorum,
destede 17 kart var, 3 çekişte gelme şansı %18."* Altında sayı bazında toplamlar
(*"herhangi bir 7 → %46"*) ve açık üçlünün durumu var:

> Üçlüyü tamamlayacak 3 kart var — 3 çekişte gelme şansı **%46**, en iyisi
> **7b** (+100).

Açık üçlünün altındaki rozetler hangi kartın kaç puana tamamladığını ve o kartın
gelme şansını gösterir; kart elindeyse *elinde* yazar. Hesap hipergeometrik
dağılımla yapılıyor, yani kart sayma ile tutarlı.

## Oyun modeli

Motorun varsaydığı akış — bu yanlışsa `config/rules.yaml`'ı düzelt:

- Elinde en fazla 5 açık kart var.
- Önünde **tek bir üçlü alan** var; kart ancak oraya konur.
- Üçlü dolunca **kendiliğinden puanlanmaz**: `Tamamla` ile kilitlenir, sonra yeni
  boş üçlü açılır. Kilitlenmeden bir sonrakine geçilmez.
- Kilitlenene kadar koyduğun kartları geri alabilirsin (kartın üstüne tıkla).
- Kart yok edersen kalıcı olarak gider.
- **Kart çekmek otomatik değil.** Ancak üçlüyü tamamladıysan ya da kart yok
  ettiysen çekebilirsin; el tekrar 5'e tamamlanır:

| Ne yaptın | Elde kalan | Çekebileceğin |
|---|---|---|
| üçlüyü tamamladın | 2 | 3 |
| 1 kart yok ettin | 4 | 1 |
| 2 kart yok ettin | 3 | 2 |
| 2 kart koydun, tamamlamadın | 3 | **0** — o kartların yeri belli |

- Deste bitince tur biter.

Buradan çıkan en önemli ekonomi: **her 3 kart = bir üçlü.** Attığın her 3 kart,
kuramayacağın bir üçlü demek — yani bir kart atmak ortalama bir üçlünün üçte biri
kadar puana mal oluyor. Hem solver hem de LLM prompt'u bu bedeli açıkça hesaba
katıyor.

## Puanlama

| Grup | Puan | | Seri (karışık renk) | Puan | | Seri (aynı renk) | Puan |
|---|---|---|---|---|---|---|---|
| 1-1-1 … 8-8-8 | 20 … 90 | | 1-2-3 … 6-7-8 | 10 … 60 | | 1-2-3 … 6-7-8 | 50 … 100 |

Sandık: `<300` bronz, `300-399` gümüş, `≥400` altın.

**Doğrulanması gereken tek sayı:** `deck.colors`. Şu an 3 renk varsayıldı
(8 sayı × 3 renk = 24 kart, yani en fazla 8 üçlü). Oyunda 4. bir renk varsa
config'e ekle — kaç üçlü kurulabileceği (`board.slots: auto`) kendini günceller.

## Agent

`config/rules.yaml` → `agent:` bölümünden yönetilir.

```yaml
agent:
  model: "qwen3.5:9b"
  think: false               # kritik, aşağıya bak
  num_predict: 250
  max_retries: 2
  fallback_to_solver: true
```

Her adımda modele verilenler: elin, açık üçlünün içeriği, onu hangi kartın kaç
puana tamamlayacağı, **destede kalan kartların tam listesi**, attığın kartlar,
kaç üçlü hakkın kaldığı ve puan tablosu. Model kart adlarıyla bir plan döndürür:

```json
{"plan": [{"action": "place", "card": "8r"}, {"action": "discard", "card": "1g"}],
 "reason": "..."}
```

Geçersiz JSON, elde olmayan bir kart ya da zaman aşımı olursa `max_retries` kadar
tekrar denenir; sonra **solver devralır**. Planın geçerli olan ön eki yine de
kullanılır. Her adımın kararını kimin verdiği CSV'ye yazılır
(`games.csv` → `llm_moves`, `solver_moves`, `llm_share`).

### Solver vetosu

Model bazen iyi bir kartı gereksiz yere harcayan hamleler öneriyor. `veto_margin`
(varsayılan 0.25) bunu engelliyor: modelin ilk adımı solver'ın değer aralığının
%25'inden fazla altında kalıyorsa öneri oyuncuya gösterilmeden reddedilir, yerine
solver'ın planı geçer. CSV'ye solver kararı olarak, `fallback_reason` alanında
nedeniyle birlikte yazılır — yani ölçüm bozulmaz. `veto_margin: 0` ile kapatılır.

Gerçek bir örnek: elde `1m 3k 6k 2m 4k`, açık üçlü boş. Model "6 kırmızıyı oyna,
5-6-7 aynı renk hedefliyorum" dedi. Monte-Carlo (her hamle için 400 simülasyon)
bunun pozisyondaki en kötü hamlelerden biri olduğunu gösteriyor:

| Hamle | Beklenen tur puanı |
|---|---|
| 4k'yı oyna | 248.5 |
| 1m'yi oyna | 247.8 |
| 3k'yı oyna (solver'ın seçimi) | 245.8 |
| **6k'yı oyna (modelin seçimi)** | **231.0** |
| 6k'yı at | 225.3 |

Veto bu öneriyi reddedip solver'ın planına (`3k · 2m · 4k` → 2-3-4, +20 puan)
çeviriyor.

> **`think: false` neden önemli:** `qwen3.5:9b` düşünen bir model. Düşünme
> zinciri açıkken tek bir karar için ~1000 düşünme token'ı üretip **245 saniye**
> sürüyor. Kapalıyken aynı karar **2-10 saniye**. `think` parametresini
> desteklemeyen bir modele geçersen istek otomatik olarak parametresiz tekrarlanır.

### Solver

LLM'in yedeği ve baseline'ı. Her hamle için hamle sonrası durumun değeri:

```
Φ(durum) = kazanılmış puan
         + açık üçlünün beklenen puanı
         + (kalan kart / 3) × henüz başlamamış bir üçlünün beklenen puanı
```

Açık üçlünün beklentisi, onu tamamlayabilecek kombinasyonların puanı ile gereken
kartların gelme olasılığının çarpımıdır; olasılık destede kalan havuzdan
hipergeometrik dağılımla hesaplanır, eldeki kartlar kesin sayılır.

### Monte-Carlo doğrulama

Yukarıdaki değer fonksiyonu sezgisel ve sık yanılıyor. Bu yüzden öneriyi veren
solver, her aday hamleden sonra turu defalarca sonuna kadar simüle edip
gerçekten en yüksek puanı getireni seçiyor. Aynı 45 seed üzerinde eşleştirilmiş
ölçüm:

| Solver | Ortalama | Üçlü | Karar süresi |
|---|---|---|---|
| Saf sezgisel | 245.1 | 5.2 | <1 ms |
| 12 simülasyon × tüm adaylar | **302.9** | 5.2 | ~4 sn |

`agent.solver_rollouts: 0` ile kapatılıp saf sezgisele dönülebilir.
**Derin Analiz** düğmesi aynı işi daha fazla simülasyonla (`deep_rollouts`)
yapar; kritik kararlarda gürültüyü azaltmak için.

İki ayrıntı pahalıya mal olmuştu:

- **Bütün adaylar denenmeli.** Sezgisel sıralamanın ilk 4'ünü simüle etmek
  yetmiyor; sezgiselin son sıraya attığı bir hamle gerçekte en iyilerden biri
  çıkabiliyor. Az simülasyon + tüm adaylar, çok simülasyon + az adaydan hem
  daha hızlı hem daha iyi.
- **Bütün adaylar aynı deste sıralarında denenmeli** (common random numbers).
  Her adaya farklı desteler verildiğinde tur puanının standart sapması (~60)
  karşılaştırmayı yutuyordu: 40 simülasyonla tek bir adayın hatası ±10 puan,
  yani sıralama gürültüden ibaret. Aynı desteler kullanılınca fark
  eşleştirilmiş ölçülüyor.

### Plan uzunluğu

Solver'ın planı bilerek kısa tutulur: ilk hamle kart atmaksa plan orada biter
(gelen kartı görmeden üst üste atmak tüm eli boşaltmaya kadar gidiyordu), kart
koymaksa aynı üçlü üzerinde çalışmaya devam edip üçlü dolunca durur. Bu kuralla
**planı topluca uygulamak ile adım adım uygulamak aynı sonucu veriyor** (200 tur,
ikisi de 242.2 ortalama) — yani "Hepsini yaptım" demek güvenli.

## CSV kayıtları

**`logs/stages.csv`** — her hamle için bir satır:
`timestamp, game_id, agent, move_no, combo_no, action, card, combo_after,
combo_kind, combo_key, points, total_score, cards_left, hand_after, source,
latency_ms, fallback_reason, reason`

**`logs/games.csv`** — her tur için bir özet satırı:
`timestamp, game_id, seed, agent, mode, total_score, chest, moves, placements,
discards, combos_done, groups, runs_same_color, runs_mixed, invalid_combos,
llm_moves, solver_moves, human_moves, llm_share, duration_s`

Her tur bağımsızdır; motor önceki turlardan hiçbir şey taşımaz.

## Ölçümler

Simülasyon modunda (motor kendi destesini kullanır), 24 kart / en fazla 8 üçlü:

| Karar verici | Ortalama puan | Üçlü | Atılan kart | Tur |
|---|---|---|---|---|
| **Solver (Monte-Carlo, varsayılan)** | **302.9** | 5.2 | 7.4 | 45 |
| Solver (saf sezgisel) | 245.1 | 5.2 | 7.0 | 45 |
| qwen3.5:9b (hibrit) | 220 | 7 | 3 | 1 |
| Rastgele | ~80 | — | — | 12 |

LLM turunda 19 planın 18'ini model verdi; karar başına 2-10 sn, tur başına ~1.5
dakika. Solver bir turu 0.03 saniyede bitiriyor, derin analiz tek karar için
~14 saniye.

### Renk sayısı üzerine bir ipucu

3 renk varsayımıyla ödül dağılımı çok bronza kayıyor — bir etkinlik için
mantıksız görünüyor. 4. bir renk eklemek dağılımı çok daha makul yapıyor:

| Varsayım | Ortalama | Bronz | Gümüş | Altın |
|---|---|---|---|---|
| 3 renk / 24 kart / 8 üçlü | 242 | %76 | %22 | %2 |
| 4 renk / 32 kart / 10 üçlü | 296 | %53 | %37 | %10 |

(Bu iki satır saf sezgisel solver ile, 250'şer tur ölçüldü — karşılaştırma kendi
içinde tutarlı. Monte-Carlo solver ikisini de yukarı taşır.)

Bu kesin kanıt değil ama oyunda renk sayısına bakmaya değer. `deck.colors`'a
dördüncü rengi eklemen yeterli, gerisi kendini ayarlar.

`simulate.py --empty-slot-factor X --look-factor Y` ile solver parametreleri
denenebilir. Varsayılanlar 250 turluk taramayla seçildi; taramada geniş bir
plato (238-244) çıktı, ama iki yön net: `look_factor` büyüdükçe solver "nasıl
olsa doğru kart gelir" diye düşünüp fazla kart atıyor, `empty_slot_factor`
büyüdükçe eldeki üçlüyü kapatmaktan kaçınıyor. İkisi de puanı düşürüyor.

## Sırada ne var (Faz 2)

- `vision/` — `mss` ile ekran yakalama, kartları ve açık üçlüyü tanıma
- `control/` — koordinat haritası, güvenli tıklama, "Güvenli Mod" onay penceresi
- Kart girişi elle yapılmak yerine ekrandan okunur; motor ve agent aynen kalır
