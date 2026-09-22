# Metin2 Okey — oyun motoru ve öğrenen ajan

Metin2 Okey etkinliğinin kural motoru ve bu oyunu oynamayı öğrenecek bir yapay
zekâ. Hiçbir dış bağımlılık yok — saf Python.

```
okey/
  rules.py      bütün sayılar (puan tabloları, deste, eşikler)
  cards.py      kartların sayıya çevrilmesi + insan okunur yazım
  scoring.py    önceden hesaplanmış "üçlü → puan" tablosu
  engine.py     tur akışı, eylem uzayı, geçerli hamle maskesi
  env.py        öğrenen ajanlar için ortam (reset / step / ödül)
  agents/       referans oyuncular
play.py         terminalden elle oyna
evaluate.py     ajanları aynı destelerde karşılaştır
replay.py       ajanları hamle hamle izle, nerede ayrıldıklarını gör
tests/          her kural için bir test
```

```powershell
# Terminalden elle oyna — tur bitince ajanlarla kıyaslar
.\.venv\Scripts\python.exe play.py --seed 25

# Ajanları karşılaştır / izle
.\.venv\Scripts\python.exe evaluate.py
.\.venv\Scripts\python.exe replay.py --seed 25 --quiet

# Testler
.\.venv\Scripts\python.exe -m pytest tests -q
```

`play.py` içinde: eylem numarasını yaz, `k` ile destede kalan kartları gör
(kart sayma), `y` yeni tur, `q` çıkış.

## Oyunun kuralları

**Deste.** 3 renk (kırmızı, mavi, sarı) × 1-8 sayı = **24 kart**, her karttan
birer tane.

**Akış.** Elinde 5 kart vardır. Her hamlede ya bir kartı **silersin** (kalıcı
olarak oyundan çıkar) ya da elinden **tam 3 kart seçip üçlü kurarsın**. Her
hamleden sonra el desteden tekrar 5'e tamamlanır. Deste bitip elde geçerli üçlü
kalmayınca tur biter.

**Geçersiz üçlü kurulamaz.** Oyun izin vermez — yani "0 puanlık üçlü" diye bir
şey yok. Bu, oyunun tek gerçek kararını netleştiriyor: **hangi kartı sileceğin.**

**Puanlama.**

| Aynı sayı | | Aynı renk seri | | Karışık seri | |
|---|---|---|---|---|---|
| 1-1-1 | 20 | 1-2-3 | 50 | 1-2-3 | 10 |
| 2-2-2 | 30 | 2-3-4 | 60 | 2-3-4 | 20 |
| 3-3-3 | 40 | 3-4-5 | 70 | 3-4-5 | 30 |
| 4-4-4 | 50 | 4-5-6 | 80 | 4-5-6 | 40 |
| 5-5-5 | 60 | 5-6-7 | 90 | 5-6-7 | 50 |
| 6-6-6 | 70 | 6-7-8 | 100 | 6-7-8 | 60 |
| 7-7-7 | 80 | | | | |
| 8-8-8 | 90 | | | | |

Sandık: `<300` bronz, `300-399` gümüş, `≥400` altın.

Toplam 170 geçerli üçlü var: 8 grup, 18 aynı renk seri, 144 karışık seri.

## Tasarımın üç kararı

**Kartlar tamsayı.** `renk × 8 + (sayı − 1)` → 0..23. Nesne yerine tamsayı
kullanmak karşılaştırmayı, kopyalamayı ve sıralamayı kat kat ucuzlatıyor.
Milyonlarca oyun simüle edeceğimiz için bu fark belirleyici. İnsan tarafı için
`deck.label(kart)` → `"5k"`, `deck.parse("5k")` → kart numarası.

**Puan tablosu önceden hesaplanıyor.** 24 karttan 3'lü seçmenin 2024 ihtimali
var; hepsinin puanı oyun başlarken bir kez çıkarılıyor. Oyun sırasında "bu üçlü
geçerli mi, kaç puan" sorusu tek sözlük bakışına iniyor. Tabloda olmayan üçlü =
geçersiz.

**Eylemler tamsayı ve maskeli.** Her hamle tek bir sayı:

```
0..4    eldeki o indeksteki kartı sil
5..14   o numaralı indeks üçlüsüyle (0,1,2), (0,1,3) … kombinasyon kur
```

Toplam 15 eylem. `game.action_mask()` her eylem için "şu anda yapılabilir mi"
döndürüyor. Bu, öğrenen ajan için hayati: ajan sadece geçerli hamleler arasından
seçtiği için **kuralları öğrenmekle vakit kaybetmiyor**, doğrudan stratejiye
odaklanıyor. El her hamleden sonra sıralandığı için de indeksler kararlı — "0
numaralı kart" her zaman elindeki en küçük karttır.

## Referans oyuncular

Üçü de öğrenmiyor; elle yazılmış kurallarla oynuyorlar. Öğrenen ajanın yenmesi
gereken çıta bunlar. Her biri bir öncekine tek bir fikir ekliyor:

| Ajan | Fikir | Ortalama | ms/tur |
|---|---|---|---|
| **rastgele** | geçerli hamleler arasından rastgele | 83.5 | 0.2 |
| **açgözlü** | üçlü varsa en yükseğini kur, yoksa en ölü kartı sil | 271.6 | 0.2 |
| **öğrenen** | özelliklerin ağırlıklarını kendi öğrenir | 289.1 | 1.1 |
| **ileri-bakışlı** | her hamleyi deneyip turu sonuna kadar simüle et | 297.5 | 93.9 |

400 tur, hepsi aynı destelerde. Eşleştirilmiş farklar:

```
ileri-bakisli - ogrenen     +8.4  ±2.9   turların %52'sinde daha iyi
ogrenen       - acgozlu    +17.4  ±3.0   turların %57'sinde daha iyi
acgozlu       - rastgele  +188.1  ±3.9   turların %100'ünde daha iyi
```

```powershell
.\.venv\Scripts\python.exe evaluate.py
.\.venv\Scripts\python.exe evaluate.py --games 1000 --rollouts 20
.\.venv\Scripts\python.exe evaluate.py --csv sonuclar.csv
```

**Açgözlü**nün "en ölü kartı sil" kuralı şu: her kart için "elde ve destede
kalanlarla bu kart en iyi hangi üçlüyü kurabilir" hesaplanıyor, en düşüğü
gidiyor. Hiçbir üçlü kuramayan kart 0 alır ve ilk o silinir.

**İleri-bakışlı** Monte-Carlo yapıyor: her aday hamleden sonra görülmemiş
kartları rastgele sıralayıp turu sonuna kadar oynatıyor, ortalaması en yüksek
hamleyi seçiyor. İki nokta kritik — ajan destenin gerçek sırasına bakmaz
(`game.with_deck`), ve bütün adaylar **aynı** deste sıralarında denenir.

İlginç bir ayrıntı: ileri-bakışlı ve öğrenen daha **az** üçlü kuruyor (4.6 ve
4.5 vs açgözlünün 5.0) ama daha çok puan alıyor. Yani bazen küçük bir üçlüyü
kurmayıp beklemek daha iyi — açgözlünün göremediği şey bu.

### Neden hep aynı desteler?

Tur puanlarının standart sapması ~50. İki ajanı farklı destelerde oynatırsan
aradaki gerçek farkı görmek çok daha fazla tur gerektirir. `evaluate.py` bütün
ajanları aynı seed listesinde oynatıp farkı **eşleştirilmiş** ölçüyor: her tur
için "A bu destede B'den kaç puan fazla aldı" diyebiliyoruz. Çıktı, aynı farkı
eşleştirmeden ölçseydik belirsizliğin ne olacağını da yazıyor.

Motor saf Python'da **~6.200 oyun/saniye** çalışıyor (rastgele ajanla). Bir
milyon oyun ≈ 2.7 dakika — RL eğitimi için fazlasıyla yeterli.

## RL ortamı

`okey/env.py` motoru öğrenen ajanların beklediği arayüze sarıyor:

```python
from okey.env import OkeyEnv
env = OkeyEnv()
obs = env.reset(seed=1)
obs, reward, done, info = env.step(action)
mask = env.action_mask()
```

```powershell
.\.venv\Scripts\python.exe -m okey.env    # gözlemin ne olduğunu satır satır yazar
```

**Gözlem — 52 sayı.** İlk 24'ü "bu kart elimde mi", sonraki 24'ü "bu kart hâlâ
gelebilir mi", son 4'ü ölçeklenmiş sayaçlar (kalan kart, puan, üçlü, el).
Silinmiş kart ayrı alan istemiyor: hem elde hem destede 0 ise o kart gitmiş.

Bu gözlem **yeterli**. Ajanın bilmediği tek şey destenin sırası, ama sıra
rastgele olduğu için "hangi kartlar kaldı" bilgisi karar vermek için gereken her
şeyi taşıyor. Gözlem destenin sırasını asla sızdırmıyor — bunu bir test
doğruluyor.

**Ödül — varsayılan olarak oyunun kendi puanı.** Her hamlede kazanılan puan;
turun toplam ödülü turun toplam puanına eşit oluyor. Yani ajanın en yükseğe
çıkardığı şey oyunun gerçek amacıyla birebir aynı.

İki isteğe bağlı *ödül şekillendirmesi* var, ikisi de kapalı:

| Ayar | Ne yapar | Riski |
|---|---|---|
| `leftover_penalty` | tur sonunda elde kalan her kart için ceza | ajan puan getirmeyecekken bile kart harcamaya başlar |
| `gold_bonus` | 400+ puanda tek seferlik ödül | amacı "ortalama puan"dan "altın sandık şansı"na çevirir |

Bu ikincisi önemli bir ayrım: **ajan puanı değil ödülü en yükseğe çıkarır.**
Altın peşindeki ajan daha çok kumar oynar, ortalaması düşer ama 400+ turların
oranı artar. Hangisini istediğine karar vermen gereken bir yer.

Geçersiz hamle cezası **yok** — gerek de yok. Ajan `action_mask()` sayesinde
sadece geçerli hamleler arasından seçiyor, dolayısıyla kuralları öğrenmekle
vakit kaybetmiyor.

## Öğrenen ajan

```powershell
.\.venv\Scripts\python.exe train.py                  # ~1 dakika, ağırlıkları kaydeder
.\.venv\Scripts\python.exe evaluate.py               # öğrenen ajan da tabloda
.\.venv\Scripts\python.exe replay.py --seed 25 --agents acgozlu ogrenen --quiet
```

### Neden ham gözlem yetmiyor

`env.observe()` 52 sayı veriyor ve bilgi olarak **eksiksiz**. Ama *lineer* bir
model için kullanışsız: "6k + 7k + 8k birlikte 100 puan eder" bilgisi üç kartın
**etkileşimi**, lineer model ise her karta bir ağırlık verip toplar. Elinde 6k
ve 7k varken 8k'nın çok değerli olması, tek başınayken olmaması — bunu ifade
edemez.

Çözüm: yapıyı biz çıkarıp ajana hazır veriyoruz. `okey/features.py` 11 özellik
üretiyor — "elindeki en iyi ikili kaç puanlık bir üçlüyü bekliyor", "kaç kartın
hiçbir işe yaramıyor" gibi. Ajan bunlara **ne kadar değer vereceğini** öğreniyor.

Bu, daha önce elle yaptığımız işin otomatikleşmiş hali: eski sürümde
`empty_slot_factor` ve `look_factor` katsayılarını ızgara taramasıyla
ayarlamıştık, saatler sürmüştü ve sadece iki katsayıydı. Ajan aynı işi 11 katsayı
için kendi yapıyor, bir dakikada.

### Nasıl öğreniyor

Sonraki-durum (afterstate) üzerinde TD öğrenme. Ajan her adımda "bu eylemi
yaparsam ortaya çıkan durum ne kadar değerli" diye soruyor; değer tahmini
`ağırlıklar · özellikler`. Seçim: en yüksek `hemen kazanılan puan + V(sonraki
durum)`. Öğrenme: kendi tahminini, bir adım sonra gördüğü daha iyi bilgiye doğru
çekiyor.

Eylemin kendisi kesin, kart çekme rastgele — ikisini ayırmak öğrenmeyi belirgin
şekilde kararlı kılıyor.

Eğitim rastgele destelerde, ölçüm ise ajanın **hiç görmediği** sabit destelerde
yapılıyor. Aynı desteleri kullansaydık ajan onları ezberleyip olduğundan iyi
görünürdü.

### Ajan ne öğrendi

Ağırlıklar okunabilir — kara kutu değil:

```
destedeki_kart      +2.326  #######################
canlilik_ort        +1.100  ##########
canlilik_min        -0.420  ####
ikinci_ikili        +0.411  ####
tamamlanan_uclu     -0.349  ###
...
hazir_uclu          -0.071
```

En büyük ağırlık **destedeki kart sayısında**. Ajan kendi başına şunu bulmuş:
*deste senin kaynağın, boşa harcama.* Kimse ona söylemedi.

`hazir_uclu` ağırlığının sıfıra yakın olması da anlamlı — hazır üçlünün değeri
zaten "hemen kazanılan puan" teriminde sayılıyor, değer fonksiyonunun onu tekrar
hesaba katmasına gerek yok. Ajan bunu da kendi keşfetmiş.

## Yol haritası

- [x] **Faz 1** — Motor, puanlama, eylem uzayı, testler
- [x] **Faz 2** — Ölçüm altyapısı + referans oyuncular (rastgele / açgözlü /
      ileri-bakışlı). Hepsi aynı destelerde eşleştirilmiş karşılaştırma.
- [x] **Faz 3** — RL ortamı: `reset / step / observation / action_mask / reward`
- [x] **Faz 4** — Öğrenen ajan: özellik tabanlı TD öğrenme (289.1 puan)
- [ ] **Faz 5** — Arayüz (yeni kurallara göre)
- [ ] **Faz 6** — Ekran okuma ve otomatik oynatma

Önceki sürüm (LLM danışmanı + web arayüzü) git geçmişinde `85801bc` commit'inde
duruyor.
