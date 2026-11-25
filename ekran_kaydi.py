"""Ekran kaydından yorum kareleri çıkarır.

Kullanıcı telefonda yorumları kaydırırken ekran kaydı alır ve bota gönderir. Buradan saniyede birkaç kare alınır,
birbirinin neredeyse aynısı olan kareler atılır (ekran durduğunda ya da çok yavaş kaydırıldığında), kalanlar
ekran görüntüsü gibi analize girer. Aynı yorum iki karede görünse bile sayım sırasında bir kez sayılır.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from ayarlar import FFMPEG

KARE_HIZI = 3          # saniyede alınan kare
YENI_ESIK = 0.62       # ekran yüksekliğinin bu kadarı kadar kaydırılınca yeni kare tutulur
EN_FAZLA_KARE = 40
SATIR = 240            # karşılaştırma için kare kaç satıra indirgenir


def _profil(yol):
    """Karenin orta bölümünün satır ortalamaları (üst/alt sabit çubuklar hariç)."""
    with Image.open(yol) as im:
        gri = im.convert("L")
        en, boy = gri.size
        orta = gri.crop((0, int(boy * 0.12), en, int(boy * 0.88))).resize((4, SATIR), Image.BOX)
    veri = list(orta.getdata())
    return [veri[i * 4:(i + 1) * 4] for i in range(SATIR)]


def _kayma(onceki, simdiki):
    """İki kare arasında içeriğin kaç satır yukarı kaydığını bulur; eşleşme yoksa None."""
    en_iyi, hata_en = 0, float("inf")
    for s in range(0, int(SATIR * 0.85)):
        ortak = SATIR - s
        hata = sum(abs(a - b) for i in range(0, ortak, 2) for a, b in zip(onceki[i + s], simdiki[i])) / (ortak * 2)
        if hata < hata_en:
            en_iyi, hata_en = s, hata
    return en_iyi if hata_en < 9 else None


def kareleri_cikar(video_yolu, hedef_klasor, onek, en_fazla=EN_FAZLA_KARE):
    """Videodan farklı kareleri hedef klasöre yazar; yazılan dosyaların listesini döndürür."""
    gecici = Path(tempfile.mkdtemp(prefix="kayit_"))
    try:
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(video_yolu),
                        "-vf", f"fps={KARE_HIZI},scale='min(1080,iw)':-2", "-q:v", "3",
                        str(gecici / "k%05d.jpg")], check=True, timeout=300)
        kareler = sorted(gecici.glob("k*.jpg"))
        secilen, onceki, biriken = [], None, 0
        for kare in kareler:
            profil = _profil(kare)
            if onceki is None:
                secilen.append(kare)
            else:
                kayma = _kayma(onceki, profil)
                biriken += SATIR if kayma is None else kayma  # eşleşmezse sayfa değişmiş demektir
                if biriken >= SATIR * YENI_ESIK:
                    secilen.append(kare)
                    biriken = 0
            onceki = profil
        if kareler and secilen[-1] != kareler[-1] and biriken >= SATIR * 0.2:
            secilen.append(kareler[-1])  # kaydın sonu
        if len(secilen) > en_fazla:  # çok uzun kayıtta eşit aralıklarla seç
            adim = len(secilen) / en_fazla
            secilen = [secilen[int(i * adim)] for i in range(en_fazla)]
        hedef_klasor = Path(hedef_klasor)
        yazilan = []
        for i, kare in enumerate(secilen):
            yol = hedef_klasor / f"{onek}_k{i:03d}.jpg"
            with Image.open(kare) as im:  # üstteki durum çubuğu/arama ve alttaki menü yorum değil: kırp
                en, boy = im.size
                im.crop((0, int(boy * 0.08), en, int(boy * 0.93))).save(yol, quality=88)
            yazilan.append(yol)
        return yazilan, len(kareler)
    finally:
        shutil.rmtree(gecici, ignore_errors=True)
