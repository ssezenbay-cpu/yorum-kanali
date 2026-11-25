"""Analiz, ses ve ekran görüntülerinden dikey (1080x1920) Shorts videosu kurgular."""
import subprocess

import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from analiz import ROLLER
import ayarlar as A
import okunus
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


def kapak_uret(urun_adi, hedef, alt_yazi="İnternetteki yorumlar okundu"):
    """Ekran görüntüsü yokken ürün kartı yerine kullanılacak sade kapak görseli."""
    en, boy = 1200, 900
    resim = Image.new("RGB", (en, boy), KOYU)
    c = ImageDraw.Draw(resim)
    ust, alt = (38, 44, 58), (14, 15, 18)
    for y in range(boy):
        o = y / boy
        c.line([(0, y), (en, y)], fill=tuple(int(ust[i] + (alt[i] - ust[i]) * o) for i in range(3)))
    c.rounded_rectangle((60, 60, en - 60, boy - 60), 40, outline=SARI, width=6)
    font = F(92)
    satirlar = sar(c, urun_adi, font, en - 220)[:3]
    aralik = 108
    y = (boy - len(satirlar) * aralik) // 2 - 50
    for satir in satirlar:
        genislik = c.textlength(satir, font=font)
        c.text(((en - genislik) / 2, y), satir, font=font, fill=BEYAZ)
        y += aralik
    kucuk = F(44, False)
    genislik = c.textlength(alt_yazi, font=kucuk)
    c.text(((en - genislik) / 2, y + 40), alt_yazi, font=kucuk, fill=SARI)
    resim.save(hedef)
    return hedef


# --- yerleşim (1080x1920) ---------------------------------------------------
PANEL = (70, 230, G - 70, 770)          # ürün paneli: üstte, sürekli görünür
ETIKET_Y = 786                          # fiyat / puan etiketleri
ICERIK_Y, ICERIK_ALT = 860, 1240        # bilgi alanı; altyazı 1290'da başlar
KARE_ARALIK, GECIS = 2.4, 0.35          # ürün panelinde kadraj değişimi sıklığı ve geçiş süresi
KADRAJLAR = [(1.00, 0.50, 0.50), (1.16, 0.50, 0.42), (1.08, 0.44, 0.56), (1.20, 0.56, 0.48)]


def urun_gorseli_kirp(resim, kutu=None):
    """Analizin verdiği kutuyla ürün fotoğrafını kırpar; kutu yoksa makul bir tahmin yapar."""
    en, boy = resim.size
    if kutu:
        x1, y1, x2, y2 = kutu
        pay_x, pay_y = 0.02 * en, 0.02 * boy
        return resim.crop((max(0, int(x1 * en - pay_x)), max(0, int(y1 * boy - pay_y)),
                           min(en, int(x2 * en + pay_x)), min(boy, int(y2 * boy + pay_y))))
    if boy / en > 1.5:  # telefon ekran görüntüsü: ürün fotoğrafı genelde üst yarıda
        return resim.crop((0, int(boy * 0.08), en, int(boy * 0.55)))
    return resim


def _zemin(resim):
    """Kenar piksellerinden zemin rengini ve kenarların ne kadarının bu renkte olduğunu bulur."""
    en, boy = resim.size
    adim_x, adim_y = max(1, en // 40), max(1, boy // 40)
    noktalar = [(x, 0) for x in range(0, en, adim_x)] + [(x, boy - 1) for x in range(0, en, adim_x)]
    noktalar += [(0, y) for y in range(0, boy, adim_y)] + [(en - 1, y) for y in range(0, boy, adim_y)]
    renkler = [resim.getpixel(n) for n in noktalar]
    ort = tuple(sum(r[i] for r in renkler) // len(renkler) for i in range(3))
    yakin = sum(1 for r in renkler if max(abs(r[i] - ort[i]) for i in range(3)) < 28) / len(renkler)
    return ort, yakin


def _ana_parcalar(maske):
    """Maskede yalnızca büyük parçaları (ürünü) bırakır; yazı, logo, rozet gibi küçük parçaları atar."""
    kucuk = maske.copy()
    kucuk.thumbnail((220, 220), Image.NEAREST)
    kucuk = kucuk.point(lambda v: 255 if v > 127 else 0)
    en, boy = kucuk.size
    piksel = kucuk.load()
    etiket = 1
    for y in range(boy):
        for x in range(en):
            if piksel[x, y] == 255 and etiket < 250:
                ImageDraw.floodfill(kucuk, (x, y), etiket)
                etiket += 1
    hist = kucuk.histogram()
    alanlar = {i: hist[i] for i in range(1, etiket)}
    if not alanlar:
        return maske
    en_buyuk = max(alanlar.values())
    tut = {i for i, a in alanlar.items() if a >= 0.2 * en_buyuk}
    secili = kucuk.point(lambda v: 255 if v in tut else 0).filter(ImageFilter.MaxFilter(5))
    secili = secili.resize(maske.size, Image.NEAREST)
    return ImageChops.multiply(maske, secili)


def urunu_ayikla(resim):
    """Açık ve düz zeminli ürün fotoğrafında ürünü zeminden ayırır (RGBA). Uygun değilse None."""
    ort, yakin = _zemin(resim)
    if yakin < 0.85 or min(ort) < 195:
        return None
    kucuk = resim.copy()
    kucuk.thumbnail((480, 480))
    fark = ImageChops.difference(kucuk, Image.new("RGB", kucuk.size, ort)).convert("L")
    ikili = fark.point(lambda v: 255 if v > 22 else 0)
    en, boy = ikili.size
    tohumlar = ([(x, 0) for x in range(0, en, 5)] + [(x, boy - 1) for x in range(0, en, 5)]
                + [(0, y) for y in range(0, boy, 5)] + [(en - 1, y) for y in range(0, boy, 5)])
    for xy in tohumlar:
        if ikili.getpixel(xy) == 0:
            ImageDraw.floodfill(ikili, xy, 128)
    maske = _ana_parcalar(ikili.point(lambda v: 0 if v == 128 else 255))
    kutu = maske.getbbox()
    if not kutu:
        return None
    oran = (kutu[2] - kutu[0]) * (kutu[3] - kutu[1]) / (en * boy)
    if oran < 0.04 or oran > 0.97:
        return None
    maske = maske.filter(ImageFilter.MinFilter(3)).resize(resim.size, Image.BILINEAR)
    maske = maske.filter(ImageFilter.GaussianBlur(1.2))
    rgba = resim.convert("RGBA")
    rgba.putalpha(maske)
    return rgba.crop(maske.getbbox())


def _isik(en, boy):
    """Ürünün arkasındaki yumuşak ışık halkası."""
    katman = Image.new("L", (en, boy), 0)
    c = ImageDraw.Draw(katman)
    for i in range(12, 0, -1):
        r = int(min(en, boy) * 0.48 * i / 12)
        c.ellipse((en // 2 - int(r * 1.25), boy // 2 - r, en // 2 + int(r * 1.25), boy // 2 + r),
                  fill=int(70 * (1 - i / 13)))
    katman = katman.filter(ImageFilter.GaussianBlur(30))
    isik = Image.new("RGBA", (en, boy), (255, 236, 200, 0))
    isik.putalpha(katman)
    return isik


def _sigdir(resim, en, boy):
    """Resmi kırpmadan kutuya sığdırır; boşlukları resmin kenar rengiyle doldurur."""
    zemin = resim.getpixel((2, 2))
    tuval = Image.new("RGB", (en, boy), zemin)
    kopya = resim.copy()
    kopya.thumbnail((en, boy), Image.LANCZOS)
    if kopya.width < en * 0.6 and kopya.height < boy * 0.6:  # küçük resmi büyüt
        oran = min(en / kopya.width, boy / kopya.height) * 0.9
        kopya = resim.resize((int(resim.width * oran), int(resim.height * oran)), Image.LANCZOS)
    tuval.paste(kopya, ((en - kopya.width) // 2, (boy - kopya.height) // 2))
    return tuval


class Kurgu:
    def __init__(self, veri, resimler, no, kelimeler=(), sahne_baslari=()):
        self.veri = veri
        self.no = no
        self.kelimeler = list(kelimeler)
        self.sahne_baslari = list(sahne_baslari)
        secim = veri.get("urun_gorseli") or {}
        indeks = secim.get("goruntu", 1) - 1 if secim else 0
        indeks = indeks if 0 <= indeks < len(resimler) else 0
        with Image.open(resimler[indeks]) as ham:
            kaynak = ImageOps.exif_transpose(ham).convert("RGB")
        self.urun = urun_gorseli_kirp(kaynak, secim.get("kutu") if secim else None)
        pw, ph = PANEL[2] - PANEL[0], PANEL[3] - PANEL[1]
        self.panel_boyut = (pw, ph)
        self.kesik = urunu_ayikla(self.urun)
        if self.kesik is not None:
            # Zeminden ayrılmış ürün: koyu zeminde, gölgeli ve hafifçe süzülerek
            self.urun_alani = ph - 70  # alttaki ürün adı şeridinin üstü
            olcek = min(pw * 0.86 / self.kesik.width, self.urun_alani * 0.93 / self.kesik.height)
            boyut = (max(1, int(self.kesik.width * olcek * 1.08)), max(1, int(self.kesik.height * olcek * 1.08)))
            self.kesik = self.kesik.resize(boyut, Image.LANCZOS)
            if olcek > 1.3:
                self.kesik = self.kesik.filter(ImageFilter.UnsharpMask(radius=2, percent=70, threshold=2))
            alfa = self.kesik.getchannel("A")
            golge = Image.new("RGBA", self.kesik.size, (0, 0, 0, 0))
            golge.putalpha(alfa.point(lambda v: int(v * 0.45)).filter(ImageFilter.GaussianBlur(26)))
            self.golge = golge
            self.isik = _isik(pw, ph)
            ortalama = self.kesik.convert("RGB").resize((1, 1), Image.LANCZOS).getpixel((0, 0))
            arka = Image.new("RGB", (G, Y), ortalama)
        else:
            # Zemini dolu fotoğraf: paneli tamamen kaplar (beyaz boşluk yok), yavaş kadraj hareketi
            self.panel_kaynak = kapla(self.urun, int(pw * 1.25), int(ph * 1.25), (0.5, 0.45))
            arka = kapla(self.urun.resize((54, 96)), G, Y)
        arka = arka.filter(ImageFilter.GaussianBlur(60))
        self.arka = Image.blend(arka, Image.new("RGB", (G, Y), KOYU), 0.84)
        c = ImageDraw.Draw(self.arka)
        c.text((KENAR, 172), f"{A.KANAL_ADI}  ·  Yorum dosyası #{self.no}", font=F(34), fill=GRI)
        self.maske = yuvarlak_maske(pw, ph, 32)
        self.ad_seridi = self._ad_seridi(pw)
        self._etiketleri_ciz(self.arka)

    # --- ortak parçalar ------------------------------------------------------
    def _etiketleri_ciz(self, resim):
        v = self.veri
        parcalar = []
        if v.get("fiyat"):
            parcalar.append(str(v["fiyat"]))
        if v.get("puan"):
            parcalar.append(f"★ {v['puan']}")
        if v.get("toplam_yorum"):
            parcalar.append(f"{v['toplam_yorum']} değerlendirme")
        if not parcalar:
            return
        c = ImageDraw.Draw(resim)
        font = F(32)
        while parcalar:
            genislikler = [c.textlength(p, font=font) + 44 for p in parcalar]
            toplam = sum(genislikler) + 14 * (len(parcalar) - 1)
            if toplam <= G - 2 * KENAR + 40:
                break
            parcalar.pop()
        x = (G - toplam) / 2
        for metin, en in zip(parcalar, genislikler):
            c.rounded_rectangle((x, ETIKET_Y, x + en, ETIKET_Y + 52), 26, fill=(0, 0, 0))
            c.text((x + 22, ETIKET_Y + 8), metin, font=font, fill=SARI if metin.startswith("★") else BEYAZ)
            x += en + 14

    def _ad_seridi(self, en):
        serit = Image.new("RGBA", (en, 70), (0, 0, 0, 150))
        c = ImageDraw.Draw(serit)
        ad = self.veri["urun_adi"]
        font = F(40)
        while c.textlength(ad, font=font) > en - 60 and len(ad) > 10:
            ad = ad.rstrip("…")[:-1].rstrip() + "…"
        c.text(((en - c.textlength(ad, font=font)) / 2, 13), ad, font=font, fill=BEYAZ)
        return serit

    def _kadraj(self, t):
        sira = int(t // KARE_ARALIK)
        yerel = t - sira * KARE_ARALIK
        onceki, simdiki = KADRAJLAR[(sira - 1) % len(KADRAJLAR)], KADRAJLAR[sira % len(KADRAJLAR)]
        if sira > 0 and yerel < GECIS:
            o = yumusak(yerel / GECIS)
            z, cx, cy = (onceki[i] + (simdiki[i] - onceki[i]) * o for i in range(3))
        else:
            z, cx, cy = simdiki
        return z * (1 + 0.012 * yerel), cx, cy

    def _vurus(self, t):
        """Sahne geçişlerinde ürünün kısa bir 'zıplama' büyümesi."""
        for bas in self.sahne_baslari[1:]:
            if 0 <= t - bas < 0.35:
                return 1 + 0.05 * math.sin(math.pi * (t - bas) / 0.35)
        return 1.0

    def _panel(self, resim, t):
        pw, ph = self.panel_boyut
        if self.kesik is not None:
            resim.paste(self.isik, (PANEL[0], PANEL[1]), self.isik)
            z = (1 + 0.04 * min(1.0, t / 30)) * self._vurus(t)
            urun, golge = self.kesik, self.golge
            if abs(z - 1) > 0.003:
                boyut = (int(urun.width * z), int(urun.height * z))
                urun, golge = urun.resize(boyut, Image.BILINEAR), golge.resize(boyut, Image.BILINEAR)
            dy = int(9 * math.sin(2 * math.pi * t / 3.2))
            x = PANEL[0] + (pw - urun.width) // 2
            y = PANEL[1] + (self.urun_alani - urun.height) // 2 + dy
            resim.paste(golge, (x, y + 30 - dy), golge)
            resim.paste(urun, (x, y), urun)
            serit_y = PANEL[3] - self.ad_seridi.height
            resim.paste(self.ad_seridi, (PANEL[0], serit_y), self.ad_seridi)
            return
        kaynak = self.panel_kaynak
        z, cx, cy = self._kadraj(t)
        z *= self._vurus(t)
        ken, kboy = min(kaynak.width, kaynak.width / z), min(kaynak.height, kaynak.height / z)
        sol = min(max(0, cx * kaynak.width - ken / 2), kaynak.width - ken)
        ust = min(max(0, cy * kaynak.height - kboy / 2), kaynak.height - kboy)
        parca = kaynak.crop((int(sol), int(ust), int(sol + ken), int(ust + kboy))).resize((pw, ph), Image.BILINEAR)
        parca.paste(self.ad_seridi, (0, ph - self.ad_seridi.height), self.ad_seridi)
        resim.paste(parca, (PANEL[0], PANEL[1]), self.maske)

    def _kelime_zamani(self, sahne, aranan, yedek):
        """Sahne içinde 'aranan' metnin söylendiği anı (sahne başına göre) bulur."""
        if not aranan or not self.sahne_baslari:
            return yedek
        bas = self.sahne_baslari[sahne]
        son = self.sahne_baslari[sahne + 1] if sahne + 1 < len(self.sahne_baslari) else 1e9
        for kelime, z_bas, _ in self.kelimeler:
            if bas <= z_bas < son and aranan in kelime:
                return max(0.0, z_bas - bas)
        return yedek

    def _taban(self, t_genel):
        resim = self.arka.copy()
        self._panel(resim, t_genel)
        return resim

    @staticmethod
    def _kaydir(t):
        """Sahne başında bilgi alanının sağdan kayarak gelmesi için x kayması."""
        return int((1 - yumusak(t / 0.28)) * 140)

    # --- sahneler (t: sahne içi zaman, tg: videonun genel zamanı) -----------------
    def acilis(self, t, sure, tg):
        resim = self._taban(tg)
        c = ImageDraw.Draw(resim)
        metin = tr_buyuk(self.veri["ekran_acilis"])
        for boyut in (88, 78, 68, 60):
            yazi = sar(c, metin, F(boyut), G - 2 * KENAR)
            if len(yazi) <= 3:
                break
        yazi = yazi[:3]
        aralik = int(boyut * 1.16)
        kutu_boy = len(yazi) * aralik + 44
        olcek = 0.85 + 0.15 * yumusak(t / 0.25)
        y0 = ICERIK_Y + 20
        dx = int((1 - olcek) * 300)
        c.rounded_rectangle((KENAR - 30 + dx, y0, G - KENAR + 30 - dx, y0 + kutu_boy), 26, fill=(0, 0, 0))
        ortala(c, yazi, F(boyut), y0 + 22, SARI, aralik)
        return resim

    def baglam(self, t, sure, tg):
        resim = self._taban(tg)
        c = ImageDraw.Draw(resim)
        v = self.veri
        urun = v.get("urun_yorumu", v["okunan_yorum"])
        bloklar = [(str(v["okunan_yorum"]), "yorum okundu", BEYAZ), (str(urun), "ürünü anlatıyor", SARI)]
        en = (SAG - KENAR - 30) // 2
        dx = self._kaydir(t)
        for i, (sayi, etiket, renk) in enumerate(bloklar):
            gir = self._kelime_zamani(1, sayi, i * 0.9)
            ilerleme = yumusak((t - gir) / 0.3)
            if ilerleme <= 0:
                continue
            x = KENAR + i * (en + 30) + dx
            y = ICERIK_Y + 20 + int((1 - ilerleme) * 30)
            c.rounded_rectangle((x, y, x + en, y + 250), 28, fill=(30, 32, 38))
            font = F(int(118 + 30 * (1 - min(1.0, (t - gir) / 0.35))))
            genislik = c.textlength(sayi, font=font)
            c.text((x + (en - genislik) / 2, y + 30), sayi, font=font, fill=renk)
            genislik = c.textlength(etiket, font=F(38, False))
            c.text((x + (en - genislik) / 2, y + 180), etiket, font=F(38, False), fill=GRI)
        return resim

    def _cubuklar(self, t, tg, sahne, baslik, renk, ogeler):
        resim = self._taban(tg)
        c = ImageDraw.Draw(resim)
        dx = self._kaydir(t)
        c.text((KENAR + dx, ICERIK_Y), baslik, font=F(56), fill=renk)
        toplam = max(1, self.veri.get("urun_yorumu", self.veri["okunan_yorum"]))
        for i, oge in enumerate(ogeler):
            gir = self._kelime_zamani(sahne, str(oge["sayi"]), 0.2 + i * 1.6)
            ilerleme = yumusak((t - gir) / 0.6)
            y = ICERIK_Y + 90 + i * 150
            boyut = 48
            while boyut > 32 and c.textlength(oge["konu"], font=F(boyut)) > SAG - KENAR - 200:
                boyut -= 4
            konu = sar(c, oge["konu"], F(boyut), SAG - KENAR - 200)[:1]
            c.text((KENAR + dx, y + (48 - boyut) // 2), konu[0] if konu else "", font=F(boyut),
                   fill=BEYAZ if ilerleme > 0 else (120, 120, 120))
            etiket = f"{oge['sayi']} / {toplam}"
            if ilerleme > 0:
                font = F(int(48 + 14 * (1 - min(1, (t - gir) / 0.4))))
                en = c.textlength(etiket, font=font)
                c.text((SAG - en + dx, y - 4), etiket, font=font, fill=renk)
            cy = y + 66
            c.rounded_rectangle((KENAR + dx, cy, SAG + dx, cy + 34), 17, fill=(52, 54, 60))
            dolu = int((SAG - KENAR) * oge["sayi"] / toplam * ilerleme)
            if dolu > 34:
                c.rounded_rectangle((KENAR + dx, cy, KENAR + dolu + dx, cy + 34), 17, fill=renk)
        return resim

    def ovgu(self, t, sure, tg):
        return self._cubuklar(t, tg, 2, "EN ÇOK ÖVÜLEN", YESIL, self.veri["ovulenler"])

    def sikayet(self, t, sure, tg):
        return self._cubuklar(t, tg, 3, "EN ÇOK ŞİKÂYET EDİLEN", KIRMIZI, self.veri["sikayetler"])

    def hukum(self, t, sure, tg):
        resim = self._taban(tg)
        c = ImageDraw.Draw(resim)
        renk = HUKUM_RENK[self.veri["hukum"]]
        metin = self.veri["hukum"]
        font = F(118 if len(metin) <= 8 else 96)
        sol, ust, sag, alt = c.textbbox((0, 0), metin, font=font)
        en, boy = sag - sol + 100, alt - ust + 70
        damga = Image.new("RGBA", (en, boy), (0, 0, 0, 0))
        dc = ImageDraw.Draw(damga)
        dc.rounded_rectangle((6, 6, en - 6, boy - 6), 26, fill=(0, 0, 0, 150), outline=renk + (255,), width=12)
        dc.text((50 - sol, 35 - ust), metin, font=font, fill=renk + (255,))
        damga = damga.rotate(-6, expand=True, resample=Image.BICUBIC)
        olcek = 1.0 + 0.7 * (1 - yumusak(t / 0.3))
        damga = damga.resize((int(damga.width * olcek), int(damga.height * olcek)), Image.BICUBIC)
        if damga.width > G - 40:
            oran = (G - 40) / damga.width
            damga = damga.resize((int(damga.width * oran), int(damga.height * oran)), Image.BICUBIC)
        resim.paste(damga, ((G - damga.width) // 2, ICERIK_Y + 110 - damga.height // 2), damga)
        if self.veri.get("kime_uygun") and t > 0.35:
            satirlar = sar(c, self.veri["kime_uygun"], F(46, False), G - 2 * KENAR)[:2]
            ortala(c, satirlar, F(46, False), ICERIK_Y + 250, BEYAZ, 58)
        return resim

    def kapanis(self, t, sure, tg):
        resim = self._taban(tg)
        c = ImageDraw.Draw(resim)
        ortala(c, ["Sıradaki ürün ne olsun?"], F(70), ICERIK_Y + 20, BEYAZ, 84)
        if t > 0.25:
            ortala(c, ["Yorumlara yaz"], F(66), ICERIK_Y + 115, SARI, 80)
        alt = [f"Yorum dosyası #{self.no}"]
        if A.LINK_PROFILDE:
            alt.append("Link profilde · satış ortaklığı linki")
        ortala(c, alt, F(36, False), ICERIK_Y + 220, GRI, 48)
        return resim


def _zamanlar(segmentler, hiz):
    """Altyazı ekrandaki (rakamlı) metinle, zamanlama ise seslendirilen (okunuş) metinle yapılır."""
    konusma, kelime_haritasi, seg_bas = okunus.esle([m for _, m in segmentler])
    bas, bit = hiz["baslangic"], hiz["bitis"]
    n = len(bas)
    oran = n / max(1, len(konusma))

    def zaman(indeks, liste):
        return liste[max(0, min(n - 1, int(indeks * oran)))]

    sahne_baslangic = [zaman(k, bas) for k in seg_bas]
    toplam = bit[-1] + 0.6
    kelimeler = [(kelime, zaman(b, bas), zaman(max(b, e - 1), bit)) for kelime, b, e in kelime_haritasi]
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
    return sahne_baslangic, toplam, altyazi, kelimeler


def _altyazi_ciz(resim, metin):
    c = ImageDraw.Draw(resim)
    satirlar = sar(c, metin, F(70), 780)[:2]
    ortala(c, satirlar, F(70), 1290, BEYAZ, 84, kontur=7)


def videoyu_kurgula(veri, resimler, ses_yolu, hiz, no, cikti):
    segmentler = [(rol, veri["senaryo"][rol]) for rol in ROLLER]
    baslangiclar, toplam, altyazi, kelimeler = _zamanlar(segmentler, hiz)
    kurgu = Kurgu(veri, resimler, no, kelimeler, baslangiclar)
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
            kare = sahneler[sahne](t - baslangiclar[sahne], son - baslangiclar[sahne], t)
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
