"""Hand-written commentary (Turkish, report text) for the ten selected games, keyed by Steam appid.

Every observation restates a number from the stored run or a plain reading of it. Remarks that
draw on outside knowledge are marked as such. Wording is hedged on purpose: the data is a single
scan and the unit estimates are review-based. The notes belong to the analysis version with
parameters_version e5e095876f70 and must be rewritten if the selection changes.
"""
from __future__ import annotations

GAME_NOTES: dict[int, dict[str, object]] = {
    1671210: {  # DELTARUNE
        "observations": [
            "Havuzun en yüksek tahmini net gelirine (yaklaşık $56.4M) ve en yüksek E değerine sahip. Tahmini 3.22M adedi Funny arketipinin medyanının (62,505 adet) yaklaşık 51 katı, yani arketipin tipik bir üyesi değil.",
            "$24.99 fiyatla havuzun 99. yüzdeliğinde, 87,082 yorumla (%98.3 olumlu) yorum sayısında birinci. Orta tahmin SteamSpy bandının (1M ile 2M) üzerinde, dolayısıyla gelir olduğundan yüksek olabilir.",
            "C değeri 0.307 ile havuzda 84. yüzdelikte, seçimin en yüksek C değeri ve basit alt küme eşiğinin (0.322) hemen altında. Başarım sayısı saklanan veride eksikti ve tahmin edilerek (imputed) dolduruldu.",
            "Geliştiricinin saklanan veride bir başka başlığı var (dev_title_count = 1). Genel bilgiye göre bu, geliştiricinin daha önce çok büyük bir kitleye ulaşmış bir oyunun devamı. Veri önceden var olan kitlenin payını ayıramıyor, ancak bu sonuca katkıda bulunmuş olabilir.",
            "En çok oy alan tag'ler Story Rich (1,715 oy), Great Soundtrack, Pixel Graphics, Funny ve RPG. Arketipin etiket tag'lerinden yalnızca Funny'yi taşıyor.",
        ],
        "reading": "Mevcut bir kitlesi olmayan küçük bir ekip için doğrudan bir şablon olması olası değil. Listedeki toplamları ve sıralamayı belirgin biçimde yukarı çekiyor, bu yüzden özetteki toplamlar bu oyun olmadan da okunmalı (§6).",
    },
    2231450: {  # Pizza Tower
        "observations": [
            "Havuzun ikinci en yüksek tahmini net gelirine (yaklaşık $21.3M) sahip ve C değeri 0.237. Havuzda 32. yüzdelik, yani düşük uçta değil. Konumu çok düşük bir karmaşıklık skorundan değil, hacimden geliyor.",
            "Tahmini 2.28M adedi, Funny arketipinin medyanının (62,505 adet) yaklaşık 36 katı. Arketipin talep skoru bir medyan olduğu için tipik bir üyeyi anlatmıyor.",
            "Boxleiter orta tahmini SteamSpy sahip bandının (1M ile 2M) üzerinde kalıyor, bu yüzden gelir rakamı olduğundan yüksek olabilir.",
            "En çok oy alan tag'ler Great Soundtrack (980 oy), 2D Platformer, Fast-Paced, Cartoony ve Funny. Veri, müziğin, sanat stilinin ve oynanışın oyunun karşılanmasındaki payını ayıramıyor.",
            "$13.39 fiyatı havuzun 87. yüzdeliğinde ve oyun yine de yorum sayısında üst yüzdelikte (99.). Bu, oyuna olan talebin fiyatla güçlü biçimde sınırlanmamış olabileceğini düşündürüyor.",
        ],
        "reading": "Güçlü bir ses ve görsel kimliği olan stilize bir 2D platform oyununun orta bir fiyatla geniş bir kitleye ulaşabileceğini gösteriyor olabilir. Kendi arketipinde medyanın çok üzerinde kaldığı için şablon olarak alınırsa hayatta kalma yanlılığı riski taşıyor.",
    },
    813230: {  # ANIMAL WELL
        "observations": [
            "35 MB kurulum boyutu havuzun 1. yüzdeliğinde ve 0.162'lik düşük C değerinin (havuzda 3. yüzdelik) ana nedeni. Kurulum boyutu varlıkların nasıl üretildiğine ve sıkıştırıldığına da bağlı olduğu için bu büyük olasılıkla üretim eforunu yansıtmıyor.",
            "$17.49 ile fiyatta 94. yüzdelikte, 13,049 yorumla ve %95.3 olumlu. Yani bu arketipte premium bir fiyat güçlü bir karşılanmayla bağdaşmış.",
            "652k adetlik orta tahmin SteamSpy bandının (200k ile 500k) üzerinde, dolayısıyla gerçek rakam banda daha yakın olabilir. Platformer arketipinin medyanının (43,845 adet) yaklaşık 15 katı.",
            "Yayıncısı Bigmode, yani kendi yayıncısı değil. Arketipinin üç etiket tag'inden yalnızca birini (Platformer) taşıyor, en çok oy alan tag'leri Metroidvania, Exploration ve Puzzle.",
        ],
        "reading": "Ticari sonuç veride net, ancak C değeri on oyun içinde en az güvenilir olanı. Düşük eforlu bir şablondan çok, premium fiyatlı bir puzzle-platformer'ın iyi satabileceğinin kanıtı olarak okunması daha uygun.",
    },
    1262350: {  # SIGNALIS
        "observations": [
            "Geliştirici (rose-engine) ve yayıncı (Balor Games) farklı, yani kendi yayıncısı olan bir sonuç değil.",
            "$13.99 fiyatla 21,517 yorumu (%96.8 olumlu) ve tahmini 1.08M adedi var. Orta tahmin SteamSpy bandının (1M ile 2M) içinde, bu yüzden en çok doğrulanan tahminlerden biri.",
            "C değeri 0.239 (havuzda 34. yüzdelik). Kurulum boyutu 2 GB (havuzda 80. yüzdelik), 8 dil ve 13 başarım listeliyor.",
            "En çok oy alan tag'ler Survival Horror (940 oy), Psychological Horror (855), Female Protagonist, Sci-fi ve Lovecraftian. Oyun yine de Mystery / Point & Click / Investigation arketipine atanmış ve bu arketipin etiket tag'lerinden yalnızca Mystery'yi (598 oy) taşıyor, dolayısıyla arketipe uyumu gevşek.",
            "Tahmini adedi arketipin medyanının (6,100 adet) yaklaşık 176 katı. Arketipin Ω değeri (+0.15) bu oyunu anlatmıyor, çünkü oyun arketipin tipik bir üyesi değil.",
            "Çıkış tarihi (2022-10-27) 48 aylık pencerenin başlangıcına (2022-10-03) çok yakın.",
        ],
        "reading": "Veri, tür kimliği net bir korku oyununun premium fiyatla büyük bir kitleye ulaşabileceğini düşündürüyor. Arketip skoru bu sonucun nedeni olarak okunmamalı.",
    },
    2027330: {  # GoreBox
        "observations": [
            "$8.99 fiyatla 8,322 yorumu ve tahmini 416k adedi var. Orta tahmin SteamSpy bandının (500k ile 1M) altında, bu da yorum tabanlı rakamın temkinli olabileceğini düşündürüyor.",
            "Olumlu yorum oranı %88.1 ile seçimin en düşüklerinden biri (havuzda 42. yüzdelik) ve %80 eşiğine en yakın oyunlardan biri.",
            "C değeri 0.217. Tek dil, 24 başarım listeliyor, kategorileri yalnızca Single-player ve bir seviye düzenleyicisi içeriyor. Geliştirici ve yayıncı aynı (F2Games).",
            "En çok oy alan tag'ler Gore (753 oy), Sandbox, Violent, Physics ve FPS. Yani oyun, tek bir mekanik fikir etrafında kurulu bir sandbox.",
            "FPS / Difficult / Violent arketipi 9 oyun içeriyor ve +2.00'lık Ω değeriyle seçimdeki en yüksek skor. Bu skor, medyanı 74,250 adet olan dokuz oyuna dayanıyor, dolayısıyla küçük örneklem nedeniyle kırılgan.",
        ],
        "reading": "Veri, tek bir fikri ve fiziği öne çıkaran düşük kapsamlı bir sandbox oyununun orta fiyatla büyük bir kitleye ulaşabileceğini düşündürüyor. Daha düşük olumlu oran, kitlenin geniş ama daha az memnun olduğuna işaret ediyor olabilir.",
    },
    1562700: {  # SANABI
        "observations": [
            "Geliştirici (WONDER POTION) ve yayıncı (NEOWIZ) farklı, yani bu kendi yayıncısı olan bir sonuç değil.",
            "Tahmini 239k adet SteamSpy bandının (500k ile 1M) altında. Bu, yorum tabanlı rakamın temkinli olabileceğini ya da bandın kitleyi olduğundan büyük gösterdiğini düşündürüyor. Platformer arketipinin medyanının (43,845 adet) yaklaşık 5.5 katı.",
            "11 dil ve 21 başarım listeliyor. 1 GB kurulum boyutu havuzun 48. yüzdeliğinde. C değeri 0.262.",
            "Tag'ler arasında Pixel Graphics, Story Rich ve Cyberpunk en çok oyu alıyor. Platformer arketipinin üç etiket tag'inin üçünü de taşıyor.",
        ],
        "reading": "Yukarıdaki oyunlara göre daha geleneksel bir üretim profili var, yerelleştirme ve bir yayıncı içeriyor. Çok küçük, kendi kaynağıyla çalışan bir ekip için daha az doğrudan bir referans olabilir.",
    },
    824600: {  # HROT
        "observations": [
            "$6.79 fiyatla 3,794 yorumu (%96.1 olumlu) ve tahmini 190k adedi var. Bu, Retro arketipinin medyanının (36,100 adet) yaklaşık 5 katı. Orta tahmin SteamSpy bandının (200k ile 500k) hemen altında, düşük-yüksek aralığı (152k ile 247k) ise bandla kesişiyor.",
            "C değeri 0.185 (havuzda 7. yüzdelik). 2 dil, 55 başarım, Steam Trading Cards ve uzun bir erişilebilirlik seçenekleri listesi var.",
            "En çok oy alan tag'ler Retro, FPS, Shooter ve Boomer Shooter. Yani kitlesi türü adıyla tanıyan, tanımlı bir nişte duruyor.",
            "Geliştirici ve yayıncı aynı isim, bu da kendi yayıncısı olduğu bir çıkışa işaret ediyor.",
        ],
        "reading": "Mütevazı fiyatlı, kompakt bir retro nişancı oyunu. Veri, açıkça adlandırılmış bir nişin bu büyüklükte kendi yayıncısı olan bir çıkışı destekleyebileceğini düşündürüyor.",
    },
    2637990: {  # Duck Detective
        "observations": [
            "$7.49 fiyatla 4,840 yorumu (%95.0 olumlu) ve tahmini 179k adedi var, bu SteamSpy bandının (100k ile 200k) içinde. Mystery / Point & Click arketipinin medyanının (6,100 adet) yaklaşık 29 katı.",
            "Bu arketipin Ω değeri +0.15 ile seçimdeki beş arketip içinde en zayıf pozitif skor. Yani oyun, zayıf desteklenen bir arketipin güçlü bir üyesi.",
            "Tag'ler arasında Detective, Investigation, Casual, Short (98 oy), Cute ve Noir var. Kısa süre, kapsamı küçük tutuyor olabilir.",
            "On oyun içinde üç platform listeleyen tek oyun ve 19 Steam kategori girdisi var, çoğu erişilebilirlik ve kontrolcü seçeneği. Yalnızca 7 başarımı ve 4 dili var.",
        ],
        "reading": "Veri, kısa ve kapsamı sıkı tutulmuş bir anlatı oyununun orta ölçekli bir kitleye ulaşabileceğini düşündürüyor. Üç platformlu çıkış C değerini bir miktar yükseltiyor.",
    },
    2121980: {  # Void Stranger
        "observations": [
            "Geliştirici ve yayıncı aynı (System Erasure). $11.99 fiyatla 2,833 yorumu (%91.0 olumlu) ve tahmini 105k adedi var. Orta tahmin SteamSpy bandının (100k ile 200k) alt sınırında.",
            "Yalnızca 1 başarım listeliyor ve 2 dili var. C değeri 0.217 (havuzda 23. yüzdelik).",
            "En çok oy alan tag'ler Mystery, Puzzle, Sokoban ve Adventure. Oyun FPS / Difficult / Violent arketipine atanmış ancak bu arketipin etiket tag'lerinden yalnızca Difficult'ı (24 oy) taşıyor, dolayısıyla atama gevşek ve oyun, arketipin dayandığı nişancı oyunlarına benzemiyor.",
            "Tahmini adedi arketipin medyanının (74,250 adet) yaklaşık 1.4 katı, yani arketipin tipik bir üyesi. E değeri düşük C ve $12 fiyattan geliyor, hacimden değil.",
        ],
        "reading": "Arketip etiketi bu oyun için bilgi vermiyor. Oyunun kendi verisi, bir bulmaca-gizem oyununun mütevazı ama pozitif bir sonuç verebileceğini düşündürüyor.",
    },
    2160220: {  # Shipwrecked 64
        "observations": [
            "Geliştirici (Squeaks D'Corgeh) ve yayıncı (Cogware Games) farklı. $7.99 fiyatla 2,179 yorumu (%95.0 olumlu) ve tahmini 80.6k adedi var. Orta tahmin SteamSpy bandının (200k ile 500k) altında.",
            "C değeri 0.246 (havuzda 41. yüzdelik) ile 2 GB kurulum boyutu (80. yüzdelik) ve 8 GB RAM gereksinimi var. Tek dil ve 16 başarım listeliyor.",
            "En çok oy alan tag'ler Horror, Exploration, Puzzle ve Psychological Horror. Retro arketipinin etiket tag'lerinden yalnızca 1990's'u (146 oy) taşıyor, bu yüzden arketipe uyumu kısmi.",
            "Tahmini adedi Retro arketipinin medyanının (36,100 adet) yaklaşık 2.2 katı. Tahmini net geliri yaklaşık $451k ile seçimdeki en küçük.",
        ],
        "reading": "On oyun içinde en zayıf kanıtı taşıyor ve listede arketip başına iki oyun kuralı sayesinde yer alıyor. Mütevazı bir sonuç olarak okunmalı.",
    },
}
