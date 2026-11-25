"""Analiz, ses ve ekran görüntülerinden dikey (1080x1920) Shorts videosu kurgular."""
import re
import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from analiz import ROLLER
import ayarlar as A
from ayarlar import FFMPEG, font_bul

G, Y, FPS = 1080, 1920, 30
KENAR = 90
SAG = G - 150  # sağdaki TikTok/Shorts düğmelerine çarpmasın
YESIL = (46, 204, 113)
KIRMIZI = (235, 87, 70)
SARI = (255, 200, 40)
BEYAZ = (246, 246, 246)
GRI = (185, 185, 185)
KOYU = (14, 15, 18)
HUKUM_RENK = {"ALINIR": YESIL, "ALINMAZ": KIRMIZI, "DİKKATLİ AL": SARI}

_fontlar = {}


def F(boyut, kalin=True):
    anahtar = (boyut, kalin)
    if anahtar not in _fontlar:
        _fontlar[anahtar] = ImageFont.truetype(font_bul(kalin), boyut)
    return _fontlar[anahtar]


def tr_buyuk(metin):
    return metin.replace("i", "İ").replace("ı", "I").upper()


def yumusak(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def sar(cizim, metin, font, genislik):
    satirlar, simdiki = [], ""
    for kelime in metin.split():
        deneme = f"{simdiki} {kelime}".strip()
        if cizim.textlength(deneme, font=font) <= genislik:
            simdiki = deneme
        else:
            if simdiki:
                satirlar.append(simdiki)
            simdiki = kelime
    if simdiki:
        satirlar.append(simdiki)
    return satirlar


def ortala(cizim, satirlar, font, y, renk, aralik, kontur=0):
    for i, satir in enumerate(satirlar):
        en = cizim.textlength(satir, font=font)
        cizim.text(((G - en) / 2, y + i * aralik), satir, font=font, fill=renk,
                   stroke_width=kontur, stroke_fill=(0, 0, 0))
    return y + len(satirlar) * aralik


def kapla(resim, en, boy, merkez=(0.5, 0.5)):
    """Resmi kırparak verilen boyutu tamamen kaplayacak şekilde ölçekler."""
    return ImageOps.fit(resim, (en, boy), Image.LANCZOS, centering=merkez)


def yuvarlak_maske(en, boy, yaricap):
    maske = Image.new("L", (en, boy), 0)
    ImageDraw.Draw(maske).rounded_rectangle((0, 0, en - 1, boy - 1), yaricap, fill=255)
    return maske


class Kurgu:
    def __init__(self, veri, resimler, no):
        self.veri = veri
        self.no = no
        with Image.open(resimler[0]) as ilk:
            self.urun = ImageOps.exif_transpose(ilk).convert("RGB")
        arka = kapla(self.urun, G, Y).filter(ImageFilter.GaussianBlur(40))
        self.arka = Image.blend(arka, Image.new("RGB", (G, Y), KOYU), 0.78)
        self._ust_bilgi(self.arka)
        self.kart = self._urun_karti()
        self.sabitler = {}

    # --- sabit katmanlar -------------------------------------------------
    def _ust_bilgi(self, resim):
        c = ImageDraw.Draw(resim)
        c.text((KENAR, 175), f"{A.KANAL_ADI}  ·  Yorum dosyası #{self.no}", font=F(38), fill=GRI)

    def _urun_karti(self):
        en = G - 2 * 110
        oran = self.urun.height / self.urun.width
        boy = min(int(en * oran), 690)
        kart = kapla(self.urun, en, boy, (0.5, 0.3)) if en * oran > 690 else self.urun.resize((en, boy), Image.LANCZOS)
        return kart

    def _baglam_sabit(self):
        resim = self.arka.copy()
        c = ImageDraw.Draw(resim)
        satirlar = sar(c, self.veri["urun_adi"], F(78), G - 2 * KENAR)[:3]
        y = ortala(c, satirlar, F(78), 330, BEYAZ, 92)
        return resim, y + 60

    # --- sahneler --------------------------------------------------------
    def acilis(self, t, sure):
        resim = self.arka.copy()
        c = ImageDraw.Draw(resim)
        olcek = 1.0 + 0.07 * (t / max(sure, 0.1))
        kart = self.kart
        en, boy = int(kart.width * olcek), int(kart.height * olcek)
        buyuk = kart.resize((en, boy), Image.BILINEAR)
        sol, ust = (en - kart.width) // 2, (boy - kart.height) // 2
        kirpik = buyuk.crop((sol, ust, sol + kart.width, ust + kart.height))
        metin = tr_buyuk(self.veri["ekran_acilis"])
        for boyut in (84, 74, 64):
            yazi = sar(c, metin, F(boyut), G - 2 * KENAR)
            if len(yazi) <= 2:
                break
        yazi = yazi[:3]
        aralik = int(boyut * 1.18)
        kutu_boy = len(yazi) * aralik + 40
        x, y = (G - kart.width) // 2, 250 + kutu_boy + 40
        resim.paste(kirpik, (x, y), yuvarlak_maske(kart.width, kart.height, 28))
        c.rounded_rectangle((KENAR - 20, 250, G - KENAR + 20, 250 + kutu_boy), 24, fill=(0, 0, 0))
        ortala(c, yazi, F(boyut), 268, SARI, aralik)
        return resim

    def baglam(self, t, sure):
        if "baglam" not in self.sabitler:
            self.sabitler["baglam"] = self._baglam_sabit()
        taban, y0 = self.sabitler["baglam"]
        resim = taban.copy()
        c = ImageDraw.Draw(resim)
        satirlar = []
        if self.veri.get("fiyat"):
            satirlar.append(("Fiyat", self.veri["fiyat"]))
        if self.veri.get("puan"):
            satirlar.append(("Puan", f"{self.veri['puan']} / 5"))
        if self.veri.get("toplam_yorum"):
            satirlar.append(("Toplam değerlendirme", str(self.veri["toplam_yorum"])))
        urun = self.veri.get("urun_yorumu", self.veri["okunan_yorum"])
        satirlar.append(("Ürünü anlatan yorum", f"{urun} / {self.veri['okunan_yorum']}"))
        for i, (etiket, deger) in enumerate(satirlar):
            ilerleme = yumusak((t - i * 0.18) / 0.35)
            if ilerleme <= 0:
                continue
            y = y0 + i * 150 + int((1 - ilerleme) * 40)
            c.rounded_rectangle((KENAR, y, SAG, y + 125), 22, fill=(32, 34, 40))
            c.text((KENAR + 40, y + 38), etiket, font=F(44, False), fill=GRI)
            en = c.textlength(deger, font=F(60))
            c.text((SAG - 40 - en, y + 28), deger, font=F(60), fill=BEYAZ)
        return resim

    def _cubuklar(self, t, baslik, renk, ogeler):
        resim = self.arka.copy()
        c = ImageDraw.Draw(resim)
        ortala(c, [baslik], F(70), 330, renk, 80)
        okunan = max(1, self.veri.get("urun_yorumu", self.veri["okunan_yorum"]))
        for i, oge in enumerate(ogeler):
            y = 520 + i * 300
            ilerleme = yumusak((t - 0.15 - i * 0.35) / 0.6)
            konu = sar(c, oge["konu"], F(58), SAG - KENAR)[:2]
            for j, satir in enumerate(konu):
                c.text((KENAR, y + j * 66), satir, font=F(58), fill=BEYAZ)
            cy = y + len(konu) * 66 + 24
            c.rounded_rectangle((KENAR, cy, SAG, cy + 50), 25, fill=(52, 54, 60))
            dolu = int((SAG - KENAR) * oge["sayi"] / okunan * ilerleme)
            if dolu > 50:
                c.rounded_rectangle((KENAR, cy, KENAR + dolu, cy + 50), 25, fill=renk)
            if ilerleme > 0.05:
                etiket = f"{oge['sayi']} / {okunan} yorum"
                c.text((KENAR, cy + 66), etiket, font=F(42, False), fill=GRI)
        return resim

    def ovgu(self, t, sure):
        return self._cubuklar(t, "EN ÇOK ÖVÜLEN", YESIL, self.veri["ovulenler"])

    def sikayet(self, t, sure):
        return self._cubuklar(t, "EN ÇOK ŞİKÂYET EDİLEN", KIRMIZI, self.veri["sikayetler"])

    def hukum(self, t, sure):
        resim = self.arka.copy()
        c = ImageDraw.Draw(resim)
        renk = HUKUM_RENK[self.veri["hukum"]]
        metin = self.veri["hukum"]
        font = F(150 if len(metin) <= 8 else 118)
        sol, ust, sag, alt = c.textbbox((0, 0), metin, font=font)
        en, boy = sag - sol + 120, alt - ust + 90
        damga = Image.new("RGBA", (en, boy), (0, 0, 0, 0))
        dc = ImageDraw.Draw(damga)
        dc.rounded_rectangle((6, 6, en - 6, boy - 6), 30, outline=renk + (255,), width=14)
        dc.text((60 - sol, 45 - ust), metin, font=font, fill=renk + (255,))
        damga = damga.rotate(-7, expand=True, resample=Image.BICUBIC)
        olcek = 1.0 + 0.6 * (1 - yumusak(t / 0.35))
        damga = damga.resize((int(damga.width * olcek), int(damga.height * olcek)), Image.BICUBIC)
        if damga.width > G - 40:
            oran = (G - 40) / damga.width
            damga = damga.resize((int(damga.width * oran), int(damga.height * oran)), Image.BICUBIC)
        resim.paste(damga, ((G - damga.width) // 2, 640 - damga.height // 2), damga)
        if self.veri.get("kime_uygun") and t > 0.3:
            satirlar = sar(c, self.veri["kime_uygun"], F(56, False), G - 2 * KENAR)[:3]
            ortala(c, satirlar, F(56, False), 900, BEYAZ, 70)
        return resim

    def kapanis(self, t, sure):
        resim = self.arka.copy()
        c = ImageDraw.Draw(resim)
        ortala(c, ["Link profilde"], F(104), 470, BEYAZ, 120)
        ortala(c, [f"Yorum dosyası #{self.no}"], F(66), 620, SARI, 80)
        ortala(c, ["Profildeki link satış ortaklığı linkidir."], F(36, False), 740, GRI, 46)
        return resim


def _zamanlar(tam_metin, segmentler, hiz):
    bas, bit = hiz["baslangic"], hiz["bitis"]
    n = len(bas)
    oran = n / max(1, len(tam_metin))

    def zaman(indeks, liste):
        return liste[max(0, min(n - 1, int(indeks * oran)))]

    sahne_baslangic, konum = [], 0
    for _, metin in segmentler:
        sahne_baslangic.append(zaman(konum, bas))
        konum += len(metin) + 1
    toplam = bit[-1] + 0.6

    kelimeler = [(m.group(0), zaman(m.start(), bas), zaman(m.end() - 1, bit))
                 for m in re.finditer(r"\S+", tam_metin)]
    parcalar, grup = [], []
    for kelime in kelimeler:
        grup.append(kelime)
        if len(grup) >= 3 or kelime[0][-1] in ".,!?;:":
            parcalar.append(grup)
            grup = []
    if grup:
        parcalar.append(grup)
    altyazi = []
    for i, grup in enumerate(parcalar):
        bitis = parcalar[i + 1][0][1] if i + 1 < len(parcalar) else toplam
        altyazi.append((grup[0][1], bitis, " ".join(k[0] for k in grup)))
    sahne_baslangic[0] = 0.0
    return sahne_baslangic, toplam, altyazi


def _altyazi_ciz(resim, metin):
    c = ImageDraw.Draw(resim)
    satirlar = sar(c, metin, F(70), 780)[:2]
    ortala(c, satirlar, F(70), 1290, BEYAZ, 84, kontur=7)


def videoyu_kurgula(veri, resimler, ses_yolu, hiz, no, cikti):
    segmentler = [(rol, veri["senaryo"][rol]) for rol in ROLLER]
    tam_metin = " ".join(m for _, m in segmentler)
    baslangiclar, toplam, altyazi = _zamanlar(tam_metin, segmentler, hiz)
    kurgu = Kurgu(veri, resimler, no)
    sahneler = [getattr(kurgu, rol) for rol, _ in segmentler]

    komut = [FFMPEG, "-y", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{G}x{Y}", "-r", str(FPS), "-i", "-",
             "-i", str(ses_yolu),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(cikti)]
    islem = subprocess.Popen(komut, stdin=subprocess.PIPE)
    kare_sayisi = int(toplam * FPS)
    sahne, ay = 0, 0
    try:
        for k in range(kare_sayisi):
            t = k / FPS
            while sahne + 1 < len(sahneler) and t >= baslangiclar[sahne + 1]:
                sahne += 1
            son = baslangiclar[sahne + 1] if sahne + 1 < len(sahneler) else toplam
            kare = sahneler[sahne](t - baslangiclar[sahne], son - baslangiclar[sahne])
            while ay + 1 < len(altyazi) and t >= altyazi[ay + 1][0]:
                ay += 1
            if altyazi and altyazi[ay][0] <= t < altyazi[ay][1]:
                _altyazi_ciz(kare, altyazi[ay][2])
            islem.stdin.write(kare.tobytes())
    finally:
        islem.stdin.close()
        islem.wait()
    if islem.returncode != 0:
        raise RuntimeError("ffmpeg videoyu oluşturamadı. ffmpeg kurulu mu?")
    return cikti
