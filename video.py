"""Analiz, ses ve ekran görüntülerinden dikey (1080x1920) Shorts videosu kurgular."""
import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

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
PANEL = (70, 240, G - 70, 820)          # ürün paneli: üstte, sürekli görünür
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
        self.panel_kaynak = _sigdir(self.urun, int(pw * 1.25), int(ph * 1.25))
        arka = kapla(self.urun.resize((54, 96)), G, Y).filter(ImageFilter.GaussianBlur(60))
        self.arka = Image.blend(arka, Image.new("RGB", (G, Y), KOYU), 0.84)
        c = ImageDraw.Draw(self.arka)
        c.text((KENAR, 175), f"{A.KANAL_ADI}  ·  Yorum dosyası #{self.no}", font=F(36), fill=GRI)
        self.maske = yuvarlak_maske(pw, ph, 32)
        self.ad_seridi = self._ad_seridi(pw)

    # --- ortak parçalar ------------------------------------------------------
    def _ad_seridi(self, en):
        serit = Image.new("RGBA", (en, 76), (0, 0, 0, 165))
        c = ImageDraw.Draw(serit)
        ad = self.veri["urun_adi"]
        font = F(44)
        while c.textlength(ad, font=font) > en - 60 and len(ad) > 10:
            ad = ad.rstrip("…")[:-1].rstrip() + "…"
        c.text(((en - c.textlength(ad, font=font)) / 2, 14), ad, font=font, fill=BEYAZ)
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

    def _panel(self, resim, t):
        pw, ph = self.panel_boyut
        kaynak = self.panel_kaynak
        z, cx, cy = self._kadraj(t)
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
        satirlar = []
        if v.get("fiyat"):
            satirlar.append(("Fiyat", v["fiyat"], str(v["fiyat"]).split()[0]))
        if v.get("puan"):
            satirlar.append(("Puan", f"{v['puan']} / 5", str(v["puan"])))
        if v.get("toplam_yorum"):
            satirlar.append(("Toplam değerlendirme", str(v["toplam_yorum"]), str(v["toplam_yorum"])))
        satirlar.append(("Ürünü anlatan yorum", f"{urun} / {v['okunan_yorum']}", str(v["okunan_yorum"])))
        dx = self._kaydir(t)
        for i, (etiket, deger, aranan) in enumerate(satirlar):
            gir = self._kelime_zamani(1, aranan, i * 0.7)
            ilerleme = yumusak((t - gir) / 0.3)
            if ilerleme <= 0:
                continue
            y = ICERIK_Y + i * 94
            vurgu = (t - gir) < 0.6
            c.rounded_rectangle((KENAR + dx, y, SAG + dx, y + 82), 20,
                                fill=(52, 56, 66) if vurgu else (30, 32, 38))
            c.text((KENAR + 34 + dx, y + 22), etiket, font=F(40, False), fill=GRI)
            font = F(int(50 + 8 * (1 - ilerleme)))
            en = c.textlength(deger, font=font)
            c.text((SAG - 34 - en + dx, y + 14), deger, font=font, fill=BEYAZ)
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
            konu = sar(c, oge["konu"], F(48), SAG - KENAR - 200)[:1]
            c.text((KENAR + dx, y), konu[0] if konu else "", font=F(48),
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
        ortala(c, ["Link profilde"], F(92), ICERIK_Y + 20, BEYAZ, 110)
        ortala(c, [f"Yorum dosyası #{self.no}"], F(60), ICERIK_Y + 150, SARI, 74)
        ortala(c, ["Profildeki link satış ortaklığı linkidir."], F(34, False), ICERIK_Y + 250, GRI, 44)
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
