# Metin2 Okey — oyun motoru ve öğrenen ajan

Metin2 Okey etkinliğinin kural motoru ve bu oyunu oynamayı öğrenecek bir yapay
zekâ. Hiçbir dış bağımlılık yok — saf Python.

```
okey/
  rules.py      bütün sayılar (puan tabloları, deste, eşikler)
  cards.py      kartların sayıya çevrilmesi + insan okunur yazım
  scoring.py    önceden hesaplanmış "üçlü → puan" tablosu
  engine.py     tur akışı, eylem uzayı, geçerli hamle maskesi
tests/          her kural için bir test
```

```powershell
# Terminalden elle oyna — kuralları gözle doğrulamak için
.\.venv\Scripts\python.exe play.py
.\.venv\Scripts\python.exe play.py --seed 42      # aynı desteyi tekrar oyna
.\.venv\Scripts\python.exe play.py --random 500   # 500 turu rastgele oynat

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

## Ölçümler

| | Ortalama puan |
|---|---|
| Rastgele oynayan | ~84 |

Motor saf Python'da **~6.200 oyun/saniye** çalışıyor (rastgele ajanla). Bir
milyon oyun ≈ 2.7 dakika — RL eğitimi için fazlasıyla yeterli.

## Yol haritası

- [x] **Faz 1** — Motor, puanlama, eylem uzayı, testler
- [ ] **Faz 2** — Ölçüm altyapısı + referans oyuncular (rastgele / açgözlü /
      ileri-bakışlı). Hepsi aynı destelerde eşleştirilmiş karşılaştırma.
- [ ] **Faz 3** — RL ortamı: `reset / step / observation / action_mask / reward`
- [ ] **Faz 4** — Öğrenen ajan: özellik tabanlı lineer Q-öğrenme
- [ ] **Faz 5** — Arayüz (yeni kurallara göre)
- [ ] **Faz 6** — Ekran okuma ve otomatik oynatma

Önceki sürüm (LLM danışmanı + web arayüzü) git geçmişinde `85801bc` commit'inde
duruyor.
