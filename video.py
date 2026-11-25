"""Analiz, ses ve ekran görüntülerinden dikey (1080x1920) Shorts videosu kurgular."""
import colorsys
import math
import subprocess

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
ILERLEME_Y = 182                        # üstteki adım sırası: Okunan · Övülen · Şikâyet · Hüküm
PANEL = (60, 262, G - 60, 872)          # ürün paneli: sürekli görünür
SERIT = 64                              # ürün adı şeridinin yüksekliği
ETIKET_Y = 890                          # fiyat / puan etiketleri
ICERIK_Y, ICERIK_ALT = 972, 1316        # bilgi alanı
ALTYAZI_Y = 1342                        # altyazı; altındaki alan TikTok/Shorts yazılarına kalır
ADIMLAR = [(1, "Okunan"), (2, "Övülen"), (3, "Şikâyet"), (4, "Hüküm")]  # (sahne sırası, ad)
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


def _hsv(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return (int(r * 255), int(g * 255), int(b * 255))


def urun_tonu(resim):
    """Ürünün baskın renk tonu (0-1). Ürün beyaz/gri/siyahsa None."""
    kucuk = resim.convert("RGBA")
    kucuk.thumbnail((90, 90))
    x = y = 0.0
    renkli = toplam = 0
    for r, g, b, a in kucuk.getdata():
        if a < 128:
            continue
        toplam += 1
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s < 0.07 or v < 0.2:
            continue
        renkli += 1
        x += s * math.cos(2 * math.pi * h)
        y += s * math.sin(2 * math.pi * h)
    if not toplam or renkli / toplam < 0.15:
        return None
    return (math.atan2(y, x) / (2 * math.pi)) % 1.0


TEMALAR = {"canli": "Canlı renk", "acik": "Açık stüdyo", "sari": "Sarı", "koyu": "Koyu (eski)"}


def tema_paleti(ad, ton=None):
    """Temanın renkleri. ton: ürünün renk tonu; canlı ve açık temada arka plan ürüne göre renklenir."""
    if ad == "acik":
        h = ton if ton is not None else 0.08
        return dict(
            ust=(252, 250, 246), alt=(233, 230, 223), hale=_hsv(h, 0.32, 1.0), hale_guc=210,
            desen="nokta", desen_renk=(0, 0, 0, 20),
            metin=(22, 22, 26), ikincil=(100, 100, 108), kart=(255, 255, 255), kart_kenar=(220, 216, 208),
            iz=(232, 229, 222), cip=(255, 255, 255), cip_kenar=(214, 210, 202), cip_metin=(22, 22, 26),
            yildiz=(215, 135, 0), vurgu=(234, 88, 12), yesil=(22, 163, 74), kirmizi=(220, 38, 38),
            dikkat=(226, 112, 0), damga_ic=(255, 255, 255, 240), golge=0.30)
    if ad == "sari":
        return dict(
            ust=(255, 212, 0), alt=(255, 182, 0), hale=(255, 255, 255), hale_guc=170,
            desen="nokta", desen_renk=(0, 0, 0, 24),
            metin=(18, 18, 18), ikincil=(80, 60, 0), kart=(255, 255, 255), kart_kenar=None,
            iz=(240, 234, 214), cip=(18, 18, 18), cip_kenar=None, cip_metin=(255, 255, 255),
            yildiz=(255, 210, 0), vurgu=(20, 90, 210), yesil=(16, 140, 64), kirmizi=(210, 32, 32),
            dikkat=(226, 100, 0), damga_ic=(255, 255, 255, 245), golge=0.36)
    if ad == "koyu":
        return dict(
            ust=(32, 33, 38), alt=(14, 15, 18), hale=(255, 236, 200), hale_guc=80,
            desen=None, desen_renk=None,
            metin=BEYAZ, ikincil=GRI, kart=(30, 32, 38), kart_kenar=None,
            iz=(52, 54, 60), cip=(0, 0, 0), cip_kenar=None, cip_metin=BEYAZ,
            yildiz=SARI, vurgu=SARI, yesil=YESIL, kirmizi=KIRMIZI,
            dikkat=SARI, damga_ic=(0, 0, 0, 150), golge=0.45)
    ust, alt = _canli_renkler(ton)
    koyu = tuple(int(v * 0.55) for v in alt)
    return dict(
        ust=ust, alt=alt, hale=(255, 255, 255), hale_guc=150,
        desen="serit", desen_renk=(255, 255, 255, 18),
        metin=(255, 255, 255), ikincil=(255, 238, 245), kart=koyu, kart_kenar=None,
        iz=tuple(int(v * 0.85) for v in alt), cip=koyu, cip_kenar=None, cip_metin=(255, 255, 255),
        yildiz=(255, 210, 40), vurgu=(255, 214, 10), yesil=(70, 225, 135), kirmizi=(255, 98, 86),
        dikkat=(255, 200, 40), damga_ic=(0, 0, 0, 150), golge=0.45)


# Canlı tema renk geçişleri: ürünün tonuna en yakın olan seçilir (çamur/kahve tonlarına düşmesin diye elle seçildi)
CANLI_GECISLER = [
    (0.00, (255, 92, 122), (112, 28, 112)),   # kırmızı / pembe
    (0.08, (255, 142, 56), (196, 40, 92)),    # turuncu
    (0.15, (255, 196, 36), (222, 78, 40)),    # sarı
    (0.36, (36, 204, 140), (18, 82, 128)),    # yeşil
    (0.55, (40, 170, 255), (62, 40, 172)),    # mavi
    (0.74, (168, 92, 255), (58, 28, 142)),    # mor (renksiz ürünlerde de bu)
    (0.88, (255, 82, 192), (98, 28, 150)),    # magenta
]


def _canli_renkler(ton):
    if ton is None:
        ton = 0.74
    secim = min(CANLI_GECISLER, key=lambda g: min(abs(g[0] - ton), 1 - abs(g[0] - ton)))
    return secim[1], secim[2]


def _arka_plan(p):
    """Temanın sabit zemini: dikey renk geçişi ve ürünün arkasındaki renkli hale."""
    zemin = Image.new("RGB", (1, 256))
    for i in range(256):
        o = (i / 255) ** 1.3
        zemin.putpixel((0, i), tuple(int(p["ust"][k] + (p["alt"][k] - p["ust"][k]) * o) for k in range(3)))
    zemin = zemin.resize((G, Y), Image.BILINEAR)
    hale = Image.new("L", (G, Y), 0)
    c = ImageDraw.Draw(hale)
    cx, cy = (PANEL[0] + PANEL[2]) // 2, (PANEL[1] + PANEL[3]) // 2 - 20
    c.ellipse((cx - 430, cy - 360, cx + 430, cy + 360), fill=p["hale_guc"])
    hale = hale.filter(ImageFilter.GaussianBlur(120))
    zemin.paste(Image.new("RGB", (G, Y), p["hale"]), (0, 0), hale)
    return zemin


DESEN_ADIM = {"nokta": 46, "serit": 92}
DESEN_HIZ = 14  # piksel/saniye: zemin deseni yavaşça kayar


def _desen(tur, renk):
    adim = DESEN_ADIM[tur]
    en, boy = G + adim, Y + adim
    katman = Image.new("RGBA", (en, boy), (0, 0, 0, 0))
    c = ImageDraw.Draw(katman)
    if tur == "nokta":
        for y in range(0, boy, adim):
            for x in range(0, en, adim):
                c.ellipse((x + adim // 2 - 3, y + adim // 2 - 3, x + adim // 2 + 3, y + adim // 2 + 3), fill=renk)
    else:
        kalinlik = 30
        for k in range(-boy, en + adim, adim):
            c.polygon([(k, 0), (k + kalinlik, 0), (k + kalinlik + boy, boy), (k + boy, boy)], fill=renk)
    return katman, adim


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
    def __init__(self, veri, resimler, no, kelimeler=(), sahne_baslari=(), tema=None):
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
        tema = tema or A.VIDEO_TEMA or "canli"
        self.tema = tema if tema in TEMALAR else "canli"
        self.p = p = tema_paleti(self.tema, urun_tonu(self.kesik if self.kesik is not None else self.urun))
        self.arka = _arka_plan(p)
        self.desen, self.desen_adim = _desen(p["desen"], p["desen_renk"]) if p["desen"] else (None, 0)
        if self.kesik is not None:
            # Zeminden ayrılmış ürün: renkli zeminde, gölgeli ve hafifçe süzülerek
            self.urun_alani = ph - SERIT - 10
            olcek = min(pw * 0.80 / self.kesik.width, self.urun_alani * 0.94 / self.kesik.height)
            boyut = (max(1, int(self.kesik.width * olcek)), max(1, int(self.kesik.height * olcek)))
            self.kesik = self.kesik.resize(boyut, Image.LANCZOS)
            if olcek > 1.3:
                self.kesik = self.kesik.filter(ImageFilter.UnsharpMask(radius=2, percent=70, threshold=2))
            alfa = self.kesik.getchannel("A")
            golge = Image.new("RGBA", self.kesik.size, (0, 0, 0, 0))
            golge.putalpha(alfa.point(lambda v: int(v * p["golge"])).filter(ImageFilter.GaussianBlur(24)))
            self.golge = golge
        else:
            # Zemini dolu fotoğraf: paneli tamamen kaplar (beyaz boşluk yok), yavaş kadraj hareketi
            self.panel_kaynak = kapla(self.urun, int(pw * 1.25), int(ph * 1.25), (0.5, 0.45))
            golge = Image.new("L", (G, Y), 0)
            ImageDraw.Draw(golge).rounded_rectangle((PANEL[0], PANEL[1] + 18, PANEL[2], PANEL[3] + 18), 34,
                                                     fill=int(255 * p["golge"]))
            golge = golge.filter(ImageFilter.GaussianBlur(22))
            self.arka.paste(Image.new("RGB", (G, Y), (0, 0, 0)), (0, 0), golge)
        self.maske = yuvarlak_maske(pw, ph, 34)
        self.ad_seridi = self._ad_seridi(pw)

    # --- ortak parçalar ------------------------------------------------------
    def _ust_bilgi(self, resim):
        """Kanal adı ve fiyat / puan / değerlendirme etiketleri."""
        p, v = self.p, self.veri
        c = ImageDraw.Draw(resim)
        c.text((KENAR, 118), f"{A.KANAL_ADI}  ·  Yorum dosyası #{self.no}", font=F(34), fill=p["ikincil"])
        parcalar = []
        if v.get("fiyat"):
            parcalar.append(str(v["fiyat"]))
        if v.get("puan"):
            parcalar.append(f"★ {v['puan']}")
        if v.get("toplam_yorum"):
            parcalar.append(f"{v['toplam_yorum']} değerlendirme")
        font = F(32)
        while parcalar:
            genislikler = [c.textlength(m, font=font) + 44 for m in parcalar]
            toplam = sum(genislikler) + 14 * (len(parcalar) - 1)
            if toplam <= G - 2 * KENAR + 40:
                break
            parcalar.pop()
        if not parcalar:
            return
        x = (G - toplam) / 2
        for metin, en in zip(parcalar, genislikler):
            c.rounded_rectangle((x, ETIKET_Y, x + en, ETIKET_Y + 52), 26, fill=p["cip"],
                                outline=p["cip_kenar"], width=2 if p["cip_kenar"] else 0)
            c.text((x + 22, ETIKET_Y + 8), metin, font=font,
                   fill=p["yildiz"] if metin.startswith("★") else p["cip_metin"])
            x += en + 14

    def _ad_seridi(self, en):
        ad = self.veri["urun_adi"]
        font = F(38)
        olcu = ImageDraw.Draw(Image.new("L", (1, 1)))
        while olcu.textlength(ad, font=font) > en - 100 and len(ad) > 10:
            ad = ad.rstrip("…")[:-1].rstrip() + "…"
        genislik = int(olcu.textlength(ad, font=font)) + 56
        serit = Image.new("RGBA", (genislik, SERIT), (0, 0, 0, 0))
        c = ImageDraw.Draw(serit)
        c.rounded_rectangle((0, 0, genislik - 1, SERIT - 1), SERIT // 2, fill=(14, 14, 16, 225))
        c.text((28, 11), ad, font=font, fill=(250, 250, 250))
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
        serit_x = PANEL[0] + (pw - self.ad_seridi.width) // 2
        serit_y = PANEL[3] - SERIT
        if self.kesik is not None:
            z = (1 + 0.04 * min(1.0, t / 30)) * self._vurus(t)
            urun, golge = self.kesik, self.golge
            if abs(z - 1) > 0.003:
                boyut = (int(urun.width * z), int(urun.height * z))
                urun, golge = urun.resize(boyut, Image.BILINEAR), golge.resize(boyut, Image.BILINEAR)
            dy = int(9 * math.sin(2 * math.pi * t / 3.2))
            x = PANEL[0] + (pw - urun.width) // 2
            y = PANEL[1] + (self.urun_alani - urun.height) // 2 + dy
            resim.paste(golge, (x + 6, y + 28 - dy), golge)
            resim.paste(urun, (x, y), urun)
            resim.paste(self.ad_seridi, (serit_x, serit_y), self.ad_seridi)
            return
        kaynak = self.panel_kaynak
        z, cx, cy = self._kadraj(t)
        z *= self._vurus(t)
        ken, kboy = min(kaynak.width, kaynak.width / z), min(kaynak.height, kaynak.height / z)
        sol = min(max(0, cx * kaynak.width - ken / 2), kaynak.width - ken)
        ust = min(max(0, cy * kaynak.height - kboy / 2), kaynak.height - kboy)
        parca = kaynak.crop((int(sol), int(ust), int(sol + ken), int(ust + kboy))).resize((pw, ph), Image.BILINEAR)
        resim.paste(parca, (PANEL[0], PANEL[1]), self.maske)
        resim.paste(self.ad_seridi, (serit_x, serit_y - 14), self.ad_seridi)

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
        if self.desen is not None:
            o = int(t_genel * DESEN_HIZ) % self.desen_adim
            parca = self.desen.crop((o, o, o + G, o + Y))
            resim.paste(parca, (0, 0), parca)
        self._panel(resim, t_genel)
        self._ust_bilgi(resim)
        self._ilerleme(resim, t_genel)
        return resim

    def _sahne_no(self, tg):
        no = 0
        for i, bas in enumerate(self.sahne_baslari):
            if tg >= bas:
                no = i
        return no

    def _ilerleme(self, resim, tg):
        """Üstteki adım sırası: biten adım tik alır, hüküm sona kadar gizli kalır (izleyici sonunu bekler)."""
        p = self.p
        c = ImageDraw.Draw(resim)
        simdi = self._sahne_no(tg)
        font = F(34)
        hukum_renk = {"ALINIR": p["yesil"], "ALINMAZ": p["kirmizi"]}.get(self.veri["hukum"], p["dikkat"])
        x = KENAR - 30
        for sira, (sahne, ad) in enumerate(ADIMLAR, 1):
            son = sira == len(ADIMLAR)
            kenar = None
            if simdi > sahne:
                metin = f"★ {self.veri['hukum']}" if son else f"✓ {ad}"
                dolgu = hukum_renk if son else p["yesil"]
            elif simdi == sahne:
                metin = f"★ {ad}" if son else f"{sira} {ad}"
                dolgu = hukum_renk if son else p["vurgu"]
            else:
                metin = f"★ {ad}?" if son else f"{sira} {ad}"
                dolgu, kenar = p["kart"], p["kart_kenar"]
            if dolgu == p["kart"]:
                yazi = p["ikincil"]
            else:
                yazi = (20, 20, 20) if 0.299 * dolgu[0] + 0.587 * dolgu[1] + 0.114 * dolgu[2] > 165 else (255, 255, 255)
            en = c.textlength(metin, font=font) + 36
            if simdi == sahne:  # şimdiki adım kısa bir 'nabız' ile büyür
                bas = self.sahne_baslari[sahne] if sahne < len(self.sahne_baslari) else 0
                b = int(6 * math.sin(math.pi * min(1.0, (tg - bas) / 0.4)))
            else:
                b = 0
            c.rounded_rectangle((x - b, ILERLEME_Y - b, x + en + b, ILERLEME_Y + 58 + b), 29 + b, fill=dolgu,
                                outline=kenar, width=2 if kenar else 0)
            c.text((x + 18, ILERLEME_Y + 9), metin, font=font, fill=yazi)
            x += en + 12

    @staticmethod
    def _kaydir(t):
        """Sahne başında bilgi alanının sağdan kayarak gelmesi için x kayması."""
        return int((1 - yumusak(t / 0.28)) * 140)

    def _kart(self, c, dx, ust, alt):
        """Bilgi alanının zemini: temaya göre beyaz ya da koyu, yuvarlak köşeli kart."""
        p = self.p
        c.rounded_rectangle((KENAR - 40 + dx, ust, G - KENAR + 40 + dx, alt), 34, fill=p["kart"],
                            outline=p["kart_kenar"], width=3 if p["kart_kenar"] else 0)

    def _hap(self, c, x, y, metin, renk, boyut=40):
        """Renkli zeminli küçük başlık."""
        font = F(boyut)
        en = c.textlength(metin, font=font)
        c.rounded_rectangle((x, y, x + en + 40, y + boyut + 24), (boyut + 24) // 2, fill=renk)
        c.text((x + 20, y + 10), metin, font=font, fill=(255, 255, 255))
        return y + boyut + 24

    # --- sahneler (t: sahne içi zaman, tg: videonun genel zamanı) -----------------
    def acilis(self, t, sure, tg):
        resim = self._taban(tg)
        c = ImageDraw.Draw(resim)
        metin = tr_buyuk(self.veri["ekran_acilis"])
        for boyut in (84, 76, 68, 60):
            yazi = sar(c, metin, F(boyut), G - 2 * KENAR)
            if len(yazi) <= 3:
                break
        yazi = yazi[:3]
        aralik = int(boyut * 1.16)
        kutu_boy = len(yazi) * aralik + 44
        olcek = 0.85 + 0.15 * yumusak(t / 0.25)
        y0 = ICERIK_Y + 10
        dx = int((1 - olcek) * 300)
        c.rounded_rectangle((KENAR - 40 + dx, y0, G - KENAR + 40 - dx, y0 + kutu_boy), 30, fill=(12, 12, 14))
        ortala(c, yazi, F(boyut), y0 + 22, SARI, aralik)
        return resim

    def baglam(self, t, sure, tg):
        resim = self._taban(tg)
        c = ImageDraw.Draw(resim)
        p, v = self.p, self.veri
        urun = v.get("urun_yorumu", v["okunan_yorum"])
        dx = self._kaydir(t)
        ust = ICERIK_Y + 10
        self._kart(c, dx, ust, ust + 270)
        orta = G // 2 + dx
        c.line((orta, ust + 40, orta, ust + 230), fill=p["iz"], width=4)
        bloklar = [(str(v["okunan_yorum"]), "yorum okundu", p["metin"]), (str(urun), "ürünü anlatıyor", p["vurgu"])]
        yarim = (G - 2 * KENAR + 80) // 2
        for i, (sayi, etiket, renk) in enumerate(bloklar):
            gir = self._kelime_zamani(1, sayi, i * 0.9)
            ilerleme = yumusak((t - gir) / 0.3)
            if ilerleme <= 0:
                continue
            x = KENAR - 40 + i * yarim + dx
            y = ust + 30 + int((1 - ilerleme) * 30)
            font = F(int(124 + 30 * (1 - min(1.0, (t - gir) / 0.35))))
            genislik = c.textlength(sayi, font=font)
            c.text((x + (yarim - genislik) / 2, y), sayi, font=font, fill=renk)
            genislik = c.textlength(etiket, font=F(38, False))
            c.text((x + (yarim - genislik) / 2, y + 160), etiket, font=F(38, False), fill=p["ikincil"])
        return resim

    def _cubuklar(self, t, tg, sahne, baslik, renk, ogeler):
        resim = self._taban(tg)
        c = ImageDraw.Draw(resim)
        p = self.p
        dx = self._kaydir(t)
        ogeler = ogeler[:3]
        aralik = 122 if len(ogeler) <= 2 else 100
        ust = ICERIK_Y
        self._kart(c, dx, ust, ust + 96 + len(ogeler) * aralik + 4)
        self._hap(c, KENAR - 10 + dx, ust + 22, baslik, renk, 36)
        toplam = max(1, self.veri.get("urun_yorumu", self.veri["okunan_yorum"]))
        sag = G - KENAR + 10
        for i, oge in enumerate(ogeler):
            gir = self._kelime_zamani(sahne, str(oge["sayi"]), 0.2 + i * 1.6)
            ilerleme = yumusak((t - gir) / 0.6)
            y = ust + 112 + i * aralik
            boyut = 46
            while boyut > 30 and c.textlength(oge["konu"], font=F(boyut)) > sag - KENAR - 190:
                boyut -= 4
            konu = sar(c, oge["konu"], F(boyut), sag - KENAR - 190)[:1]
            c.text((KENAR - 10 + dx, y + (46 - boyut) // 2), konu[0] if konu else "", font=F(boyut),
                   fill=p["metin"] if ilerleme > 0 else p["ikincil"])
            etiket = f"{oge['sayi']} / {toplam}"
            if ilerleme > 0:
                font = F(int(46 + 14 * (1 - min(1, (t - gir) / 0.4))))
                en = c.textlength(etiket, font=font)
                c.text((sag - en + dx, y - 4), etiket, font=font, fill=renk)
            cy = y + 60
            c.rounded_rectangle((KENAR - 10 + dx, cy, sag + dx, cy + 30), 15, fill=p["iz"])
            dolu = int((sag - KENAR + 10) * oge["sayi"] / toplam * ilerleme)
            if dolu > 30:
                c.rounded_rectangle((KENAR - 10 + dx, cy, KENAR - 10 + dolu + dx, cy + 30), 15, fill=renk)
        return resim

    def ovgu(self, t, sure, tg):
        return self._cubuklar(t, tg, 2, "EN ÇOK ÖVÜLEN", self.p["yesil"], self.veri["ovulenler"])

    def sikayet(self, t, sure, tg):
        return self._cubuklar(t, tg, 3, "EN ÇOK ŞİKÂYET EDİLEN", self.p["kirmizi"], self.veri["sikayetler"])

    def hukum(self, t, sure, tg):
        resim = self._taban(tg)
        c = ImageDraw.Draw(resim)
        p = self.p
        renk = {"ALINIR": p["yesil"], "ALINMAZ": p["kirmizi"]}.get(self.veri["hukum"], p["dikkat"])
        if self.veri.get("kime_uygun") and t > 0.35:
            satirlar = sar(c, self.veri["kime_uygun"], F(44), G - 2 * KENAR)[:2]
            ust = ICERIK_Y + 190
            self._kart(c, 0, ust, ust + 40 + len(satirlar) * 56)
            ortala(c, satirlar, F(44), ust + 22, p["metin"], 56)
        metin = self.veri["hukum"]
        font = F(118 if len(metin) <= 8 else 98)
        sol, ust_, sag, alt = c.textbbox((0, 0), metin, font=font)
        en, boy = sag - sol + 100, alt - ust_ + 70
        damga = Image.new("RGBA", (en, boy), (0, 0, 0, 0))
        dc = ImageDraw.Draw(damga)
        dc.rounded_rectangle((6, 6, en - 6, boy - 6), 26, fill=p["damga_ic"], outline=renk + (255,), width=12)
        dc.text((50 - sol, 35 - ust_), metin, font=font, fill=renk + (255,))
        damga = damga.rotate(-6, expand=True, resample=Image.BICUBIC)
        olcek = 1.0 + 0.7 * (1 - yumusak(t / 0.3))
        damga = damga.resize((int(damga.width * olcek), int(damga.height * olcek)), Image.BICUBIC)
        if damga.width > G - 40:
            oran = (G - 40) / damga.width
            damga = damga.resize((int(damga.width * oran), int(damga.height * oran)), Image.BICUBIC)
        resim.paste(damga, ((G - damga.width) // 2, ICERIK_Y + 90 - damga.height // 2), damga)
        return resim

    def kapanis(self, t, sure, tg):
        resim = self._taban(tg)
        c = ImageDraw.Draw(resim)
        p = self.p
        dx = self._kaydir(t)
        alt = [f"Yorum dosyası #{self.no}"]
        if A.LINK_PROFILDE:
            alt.append("Link profilde · satış ortaklığı linki")
        ust = ICERIK_Y + 10
        self._kart(c, dx, ust, ust + 230 + 46 * len(alt))
        satir = ["Sıradaki ürün ne olsun?"]
        en = c.textlength(satir[0], font=F(66))
        c.text(((G - en) / 2 + dx, ust + 30), satir[0], font=F(66), fill=p["metin"])
        if t > 0.25:
            en = c.textlength("Yorumlara yaz", font=F(66))
            c.text(((G - en) / 2 + dx, ust + 118), "Yorumlara yaz", font=F(66), fill=p["vurgu"])
        for i, s in enumerate(alt):
            en = c.textlength(s, font=F(34, False))
            c.text(((G - en) / 2 + dx, ust + 214 + i * 46), s, font=F(34, False), fill=p["ikincil"])
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
    ortala(c, satirlar, F(70), ALTYAZI_Y, BEYAZ, 84, kontur=7)


def videoyu_kurgula(veri, resimler, ses_yolu, hiz, no, cikti, tema=None):
    segmentler = [(rol, veri["senaryo"][rol]) for rol in ROLLER]
    baslangiclar, toplam, altyazi, kelimeler = _zamanlar(segmentler, hiz)
    kurgu = Kurgu(veri, resimler, no, kelimeler, baslangiclar, tema)
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
