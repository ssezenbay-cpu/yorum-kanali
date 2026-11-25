"""Analiz, ses ve ekran görüntülerinden dikey (1080x1920) Shorts videosu kurgular."""
import colorsys
import math
import re
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from analiz import ROLLER
import ayarlar as A
import miksaj
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
YAZI_TIPLERI = {"kalin": "Montserrat-ExtraBold.ttf", "normal": "Montserrat-SemiBold.ttf",
                "siyah": "Montserrat-Black.ttf", "dar": "Anton-Regular.ttf"}
SEMBOLLER = set("★✓✗")  # Montserrat'ta olmayan işaretler yedek yazı tipiyle çizilir


def _font_yolu(tur):
    yol = A.KOK / "yazitipleri" / YAZI_TIPLERI[tur]
    return str(yol) if yol.exists() else font_bul(tur != "normal")


def F(boyut, kalin=True, tur=None):
    """Yazı tipi: kalin (ExtraBold), normal (SemiBold), siyah (Black), dar (Anton)."""
    tur = tur or ("kalin" if kalin else "normal")
    anahtar = (boyut, tur)
    if anahtar not in _fontlar:
        _fontlar[anahtar] = ImageFont.truetype(_font_yolu(tur), boyut)
    return _fontlar[anahtar]


def FS(boyut):
    return F(boyut, tur="siyah")


def FD(boyut):
    return F(boyut, tur="dar")


def _yedek(font):
    anahtar = ("yedek", font.size)
    if anahtar not in _fontlar:
        _fontlar[anahtar] = ImageFont.truetype(font_bul(True), font.size)
    return _fontlar[anahtar]


def olc(c, metin, font):
    return sum(c.textlength(ch, font=_yedek(font)) if ch in SEMBOLLER else 0 for ch in metin) + \
        c.textlength("".join(ch for ch in metin if ch not in SEMBOLLER), font=font)


def yaz(c, xy, metin, font, fill, **kw):
    """Metni yazar; ★ ✓ ✗ gibi işaretleri yedek yazı tipiyle çizer."""
    if not SEMBOLLER.intersection(metin):
        c.text(xy, metin, font=font, fill=fill, **kw)
        return
    x, y = xy
    parca = ""
    for ch in metin + "\0":
        if ch in SEMBOLLER or ch == "\0":
            if parca:
                c.text((x, y), parca, font=font, fill=fill, **kw)
                x += c.textlength(parca, font=font)
                parca = ""
            if ch != "\0":
                c.text((x, y + font.size * 0.05), ch, font=_yedek(font), fill=fill, **kw)
                x += c.textlength(ch, font=_yedek(font))
        else:
            parca += ch


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
BASLIK_Y = 104                          # kanal adı (seri başlığı)
ILERLEME_Y = 160                        # adım sırası: Dosya #N · Övgü · Şikâyet · Karar
PANEL = (60, 240, G - 60, 766)          # ürün paneli: sürekli görünür
SERIT = 60                              # ürün adı şeridinin yüksekliği
ETIKET_Y = 782                          # fiyat / puan etiketleri
ICERIK_Y, ICERIK_ALT = 856, 1326        # bilgi alanı
ALTYAZI_Y = 1352                        # kalın altyazı
DIPNOT_Y = 1540                         # veri kaynağı ve tarih
ADIMLAR = [(1, "Dosya"), (2, "Övgü"), (3, "Şikâyet"), (4, "Karar")]  # (sahne sırası, ad)
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
    return ImageChops.multiply(maske, secili), len(tut)


def urunu_ayikla(resim, tam_olmali=False):
    """Açık ve düz zeminli ürün fotoğrafında ürünü zeminden ayırır (RGBA). Uygun değilse None.
    tam_olmali: ürün fotoğrafın kenarlarına dayanıyorsa (yakın çekim, kesik ürün) kullanma."""
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
    maske, parca_sayisi = _ana_parcalar(ikili.point(lambda v: 0 if v == 128 else 255))
    if parca_sayisi > 6:  # birbirinden ayrı çok sayıda benzer parça: ürün değil, yazı (ör. yorum ekranı)
        return None
    kutu = maske.getbbox()
    if not kutu:
        return None
    oran = (kutu[2] - kutu[0]) * (kutu[3] - kutu[1]) / (en * boy)
    if oran < 0.04 or oran > 0.97:
        return None
    if tam_olmali:
        dayanan = sum((kutu[0] <= 2, kutu[1] <= 2, kutu[2] >= en - 2, kutu[3] >= boy - 2))
        if dayanan >= 1:
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


TEMALAR = {"lacivert": "Lacivert dosya", "canli": "Pembe-mor", "urun": "Ürünün rengine göre",
           "acik": "Açık stüdyo", "sari": "Sarı", "koyu": "Koyu (eski)"}


def tema_paleti(ad, ton=None):
    """Temanın renkleri. ton: ürünün renk tonu; canlı ve açık temada arka plan ürüne göre renklenir."""
    p = _tema_paleti(ad, ton)
    p.setdefault("baslik", p["vurgu"])
    p.setdefault("bolum_isigi", False)   # ürünün arkasındaki ışık bölüme göre renk değiştirsin mi
    p.setdefault("kenar_renkli", p["kart_kenar"] is None)  # kartların çerçevesi bölüm renginde
    return p


def _tema_paleti(ad, ton=None):
    if ad == "lacivert":
        return dict(
            ust=(17, 27, 50), alt=(7, 11, 22), hale=(60, 120, 255), hale_guc=0,
            desen="izgara", desen_renk=(120, 160, 255, 14),
            metin=(244, 246, 252), ikincil=(146, 158, 186), kart=(13, 22, 41), kart_kenar=None,
            iz=(34, 46, 72), cip=(22, 33, 58), cip_kenar=None, cip_metin=(235, 240, 250),
            yildiz=(255, 196, 40), vurgu=(64, 164, 255), yesil=(46, 204, 113), kirmizi=(255, 82, 82),
            dikkat=(255, 170, 30), damga_ic=(10, 14, 26, 210), golge=0.55, bolum_isigi=True)
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
    ust, alt = _canli_renkler(ton) if ad == "urun" else CANLI_GECISLER[0][1:]
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
    if not p["hale_guc"]:
        return zemin
    hale = Image.new("L", (G, Y), 0)
    c = ImageDraw.Draw(hale)
    cx, cy = (PANEL[0] + PANEL[2]) // 2, (PANEL[1] + PANEL[3]) // 2 - 20
    c.ellipse((cx - 430, cy - 360, cx + 430, cy + 360), fill=p["hale_guc"])
    hale = hale.filter(ImageFilter.GaussianBlur(120))
    zemin.paste(Image.new("RGB", (G, Y), p["hale"]), (0, 0), hale)
    return zemin


DESEN_ADIM = {"nokta": 46, "serit": 92, "izgara": 72}
DESEN_HIZ = 14  # piksel/saniye: zemin deseni yavaşça kayar
GOLGE_PAY = 50  # gölge bulanıklığı kenarda kesilmesin diye bırakılan pay


def _desen(tur, renk):
    adim = DESEN_ADIM[tur]
    en, boy = G + adim, Y + adim
    katman = Image.new("RGBA", (en, boy), (0, 0, 0, 0))
    c = ImageDraw.Draw(katman)
    if tur == "nokta":
        for y in range(0, boy, adim):
            for x in range(0, en, adim):
                c.ellipse((x + adim // 2 - 3, y + adim // 2 - 3, x + adim // 2 + 3, y + adim // 2 + 3), fill=renk)
    elif tur == "izgara":
        for x in range(0, en, adim):
            c.line((x, 0, x, boy), fill=renk, width=1)
        for y in range(0, boy, adim):
            c.line((0, y, en, y), fill=renk, width=1)
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


def _urun_adaylari(veri, resimler):
    """Ürün görseli adayları, öncelik sırasıyla: tam ürün fotoğrafları, ekran görüntüsünden kırpılan, ilk görüntü.
    Çok küçük kırpıntılar (bulanık çıkar) başka aday varsa elenir."""
    def ac(i):
        with Image.open(resimler[i]) as ham:
            return ImageOps.exif_transpose(ham).convert("RGB")

    adaylar, kullanilan = [], set()
    for no in veri.get("urun_fotograflari") or []:
        i = no - 1
        if 0 <= i < len(resimler) and i not in kullanilan:
            try:
                adaylar.append((ac(i), True))
                kullanilan.add(i)
            except OSError:
                pass
    secim = veri.get("urun_gorseli") or {}
    i = secim.get("goruntu", 1) - 1 if secim else 0
    if 0 <= i < len(resimler):
        try:
            tam = ac(i)
            kirpik = urun_gorseli_kirp(tam, secim.get("kutu") if secim else None)
            guvenilir = bool(secim)  # analiz ürün fotoğrafını bulduysa güvenilir; bulamadıysa yalnızca tahmin
            if min(kirpik.size) >= 220:
                adaylar.append((kirpik, guvenilir))
            elif not adaylar:  # kutu çok küçük: bulanık çıkmasın diye görüntünün tamamı
                adaylar.append((urun_gorseli_kirp(tam), guvenilir))
        except OSError:
            pass
    return adaylar


def _sigdir_panel(resim, en, boy):
    """Açık zeminli fotoğrafı kırpmadan panele sığdırır (ad şeridinin üstünde kalır), en fazla 2 kat büyütür."""
    zemin = _zemin(resim)[0]
    tuval = Image.new("RGB", (en, boy), zemin)
    alan_en, alan_boy = int(en * 0.9), int((boy - SERIT - 20) * 0.92)
    oran = min(alan_en / resim.width, alan_boy / resim.height, 2.0)
    kopya = resim.resize((max(1, int(resim.width * oran)), max(1, int(resim.height * oran))), Image.LANCZOS)
    tuval.paste(kopya, ((en - kopya.width) // 2, (boy - SERIT - 20 - kopya.height) // 2 + 10))
    return tuval


class Kurgu:
    def __init__(self, veri, resimler, no, kelimeler=(), sahne_baslari=(), tema=None):
        self.veri = veri
        self.no = no
        self.kelimeler = list(kelimeler)
        self.sahne_baslari = list(sahne_baslari)
        pw, ph = PANEL[2] - PANEL[0], PANEL[3] - PANEL[1]
        self.panel_boyut = (pw, ph)
        self.urun_alani = ph - SERIT - 10
        # Ürün görseli: önce kullanıcının gönderdiği tam ürün fotoğrafları, sonra ekran görüntüsünden kırpılan.
        adaylar = _urun_adaylari(veri, resimler)
        kesikler = []
        for aday, _ in adaylar:
            if len(kesikler) >= 4:
                break
            kesik = urunu_ayikla(aday, tam_olmali=bool(kesikler))
            if kesik is not None:
                kesikler.append(kesik)
        self.kesik = kesikler[0] if kesikler else None
        guvenilir = [a for a, g in adaylar if g]
        # Ürün fotoğrafı yoksa (yalnızca yorum ekranları gönderildiyse) ekran görüntüsü ürün sanılmasın: ad kartı
        self.ad_karti = self.kesik is None and not guvenilir
        if self.kesik is not None:
            self.urun = adaylar[0][0]
        elif guvenilir:
            self.urun = max(guvenilir, key=lambda a: min(a.size))
        else:
            self.urun = Image.new("RGB", (pw, ph), (20, 30, 54))
        tema = tema or A.VIDEO_TEMA or "lacivert"
        self.tema = tema if tema in TEMALAR else "lacivert"
        self.p = p = tema_paleti(self.tema, urun_tonu(self.kesik if self.kesik is not None else self.urun))
        self.arka = _arka_plan(p)
        self.desen, self.desen_adim = _desen(p["desen"], p["desen_renk"]) if p["desen"] else (None, 0)
        self.sigdir = False
        if self.kesik is not None:
            # Zeminden ayrılmış ürün: renkli zeminde, gölgeli ve hafifçe süzülerek.
            # Birden fazla temiz ürün fotoğrafı varsa her sahnede başka açı gösterilir.
            self.kesikler = [self._hazirla(kesik) for kesik in kesikler]
        elif self.ad_karti:
            self.sigdir = True
            self.panel_kaynak = self._ad_karti_ciz(pw, ph)
        else:
            ort, yakin = _zemin(self.urun)
            if yakin >= 0.6 and min(ort) >= 185:
                # Açık zeminli ama ayrılamayan fotoğraf: ürün kırpılmadan, tamamı görünecek şekilde sığdırılır
                self.sigdir = True
                self.panel_kaynak = _sigdir_panel(self.urun, pw, ph)
            else:
                # Zemini dolu fotoğraf: paneli tamamen kaplar, yavaş kadraj hareketi
                self.panel_kaynak = kapla(self.urun, int(pw * 1.25), int(ph * 1.25), (0.5, 0.45))
            golge = Image.new("L", (G, Y), 0)
            ImageDraw.Draw(golge).rounded_rectangle((PANEL[0], PANEL[1] + 18, PANEL[2], PANEL[3] + 18), 34,
                                                     fill=int(255 * p["golge"]))
            golge = golge.filter(ImageFilter.GaussianBlur(22))
            self.arka.paste(Image.new("RGB", (G, Y), (0, 0, 0)), (0, 0), golge)
        self.maske = yuvarlak_maske(pw, ph, 34)
        self.ad_seridi = self._ad_seridi(pw) if not self.ad_karti else Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        self._isik_hazirla()
        self._dipnot_ciz(self.arka)

    def _ad_karti_ciz(self, en, boy):
        """Ürün fotoğrafı yokken panel: ürünün adı büyük harflerle, kategori üstte."""
        p = self.p
        kart = Image.new("RGB", (en, boy), p["kart"])
        c = ImageDraw.Draw(kart)
        c.rounded_rectangle((3, 3, en - 4, boy - 4), 34, outline=p["iz"], width=3)
        ad = tr_buyuk(self.veri.get("urun_adi") or "")
        for boyut in (84, 72, 62, 54):
            satirlar = sar(c, ad, FD(boyut), en - 120)
            if len(satirlar) <= 3:
                break
        satirlar = satirlar[:3]
        aralik = int(boyut * 1.1)
        y = (boy - aralik * len(satirlar)) // 2 + 20
        kategori = tr_buyuk(self.veri.get("kategori") or "")
        if kategori:
            en_k = c.textlength(kategori, font=FS(30))
            c.text(((en - en_k) / 2, y - 60), kategori, font=FS(30), fill=p["vurgu"])
        ortala_ = [(s, c.textlength(s, font=FD(boyut))) for s in satirlar]
        for i, (s, en_s) in enumerate(ortala_):
            c.text(((en - en_s) / 2, y + i * aralik), s, font=FD(boyut), fill=p["metin"])
        return kart

    def _hazirla(self, kesik):
        """Kesilmiş ürünü panele göre ölçekler ve gölgesini (kenarlarda kesilmesin diye paylı) hazırlar."""
        pw, _ = self.panel_boyut
        olcek = min(pw * 0.80 / kesik.width, self.urun_alani * 0.94 / kesik.height)
        boyut = (max(1, int(kesik.width * olcek)), max(1, int(kesik.height * olcek)))
        kesik = kesik.resize(boyut, Image.LANCZOS)
        if olcek > 1.3:
            kesik = kesik.filter(ImageFilter.UnsharpMask(radius=2, percent=70, threshold=2))
        en, boy = kesik.size
        pay = GOLGE_PAY
        maske = Image.new("L", (en + 2 * pay, boy + 2 * pay), 0)
        guc = self.p["golge"]
        maske.paste(kesik.getchannel("A").point(lambda v: int(v * guc * 0.7)), (pay, pay))
        ImageDraw.Draw(maske).ellipse((pay + en * 0.06, pay + boy - 16, pay + en * 0.94, pay + boy + 20),
                                      fill=int(255 * guc))  # ürünün altındaki zemin gölgesi
        golge = Image.new("RGBA", maske.size, (0, 0, 0, 0))
        golge.putalpha(maske.filter(ImageFilter.GaussianBlur(20)))
        return kesik, golge

    # --- ortak parçalar ------------------------------------------------------
    def _bolum_rengi(self, sahne):
        p = self.p
        return {2: p["yesil"], 3: p["kirmizi"], 4: self._hukum_rengi()}.get(sahne, p["vurgu"])

    def _hukum_rengi(self):
        p = self.p
        return {"ALINIR": p["yesil"], "ALINMAZ": p["kirmizi"]}.get(self.veri["hukum"], p["dikkat"])

    def _isik_hazirla(self):
        """Bölüme göre renk değiştiren ürün ışığı (lacivert temada): övgüde yeşil, şikâyette kırmızı..."""
        self.isiklar = {}
        if not self.p.get("bolum_isigi"):
            return
        pw, ph = self.panel_boyut
        en, boy = pw + 160, ph + 120
        maske = Image.new("L", (en, boy), 0)
        ImageDraw.Draw(maske).ellipse((en * 0.22, boy * 0.14, en * 0.78, boy * 0.86), fill=150)
        maske = maske.filter(ImageFilter.GaussianBlur(70))
        for renk in {self._bolum_rengi(s) for s in range(6)}:
            isik = Image.new("RGBA", (en, boy), renk + (0,))
            isik.putalpha(maske)
            self.isiklar[renk] = isik

    def _dipnot_ciz(self, resim):
        """Altta her zaman: veri kaynağı, yorum sayısı ve tarih."""
        v, p = self.veri, self.p
        c = ImageDraw.Draw(resim)
        kaynak = v.get("kaynak_etiketi") or ", ".join(k.get("ad", "") for k in v.get("kaynaklar") or []) \
            or "ekran görüntüleri"
        tarih = v.get("tarih") or datetime.now().strftime("%d.%m.%Y")
        satir1 = f"Veri: {v['okunan_yorum']} yorum ({v.get('urun_yorumu', v['okunan_yorum'])} ürünle ilgili) · {tarih}"
        satir2 = f"Kaynak: {kaynak} · {v['urun_adi']}" + ("" if self.ad_karti else " · ürün görseli: satıcı sayfası")
        for i, (metin, boyut) in enumerate(((satir1, 31), (satir2, 26))):
            font = F(boyut, i == 0)
            while c.textlength(metin, font=font) > G - 2 * KENAR + 40 and len(metin) > 20:
                metin = metin[:-2].rstrip() + "…"
            c.text((KENAR - 30, DIPNOT_Y + i * 44), metin, font=font,
                   fill=p["metin"] if i == 0 else p["ikincil"])

    def _ust_bilgi(self, resim):
        """Seri başlığı (kanal adı) ve fiyat / puan / değerlendirme etiketleri."""
        p, v = self.p, self.veri
        c = ImageDraw.Draw(resim)
        c.text((KENAR - 30, BASLIK_Y), tr_buyuk(A.KANAL_ADI), font=FS(36), fill=p["baslik"])
        parcalar = []
        if v.get("fiyat"):
            parcalar.append(str(v["fiyat"]))
        if v.get("puan"):
            parcalar.append(f"★ {v['puan']}")
        if v.get("toplam_yorum"):
            toplam_ = str(v["toplam_yorum"]).strip()
            if toplam_.isdigit() and len(toplam_) > 3:
                toplam_ = f"{int(toplam_):,}".replace(",", ".")
            parcalar.append(f"{toplam_} değerlendirme")
        font = F(30)
        while parcalar:
            genislikler = [olc(c, m, font) + 40 for m in parcalar]
            toplam = sum(genislikler) + 12 * (len(parcalar) - 1)
            if toplam <= G - 2 * KENAR + 40:
                break
            parcalar.pop()
        if not parcalar:
            return
        x = (G - toplam) / 2
        for metin, en in zip(parcalar, genislikler):
            c.rounded_rectangle((x, ETIKET_Y, x + en, ETIKET_Y + 48), 24, fill=p["cip"],
                                outline=p["cip_kenar"], width=2 if p["cip_kenar"] else 0)
            yaz(c, (x + 20, ETIKET_Y + 7), metin, font, p["yildiz"] if metin.startswith("★") else p["cip_metin"])
            x += en + 12

    def _ad_seridi(self, en):
        ad = self.veri["urun_adi"]
        font = F(34)
        olcu = ImageDraw.Draw(Image.new("L", (1, 1)))
        while olcu.textlength(ad, font=font) > en - 100 and len(ad) > 10:
            ad = ad.rstrip("…")[:-1].rstrip() + "…"
        genislik = int(olcu.textlength(ad, font=font)) + 52
        serit = Image.new("RGBA", (genislik, SERIT), (0, 0, 0, 0))
        c = ImageDraw.Draw(serit)
        c.rounded_rectangle((0, 0, genislik - 1, SERIT - 1), SERIT // 2, fill=(10, 12, 18, 225))
        c.text((26, 10), ad, font=font, fill=(250, 250, 250))
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
        if self.isiklar:
            isik = self.isiklar[self._bolum_rengi(self._sahne_no(t))]
            resim.paste(isik, (PANEL[0] - 80, PANEL[1] - 60), isik)
        if self.kesik is not None:
            z = (1 + 0.04 * min(1.0, t / 30)) * self._vurus(t)
            urun, golge = self.kesikler[self._sahne_no(t) % len(self.kesikler)]
            if abs(z - 1) > 0.003:
                urun = urun.resize((int(urun.width * z), int(urun.height * z)), Image.BILINEAR)
                golge = golge.resize((int(golge.width * z), int(golge.height * z)), Image.BILINEAR)
            dy = int(9 * math.sin(2 * math.pi * t / 3.2))
            aci = 1.6 * math.sin(2 * math.pi * t / 4.4)  # hafif sallanma
            if abs(aci) > 0.05:
                genis = urun.rotate(aci, resample=Image.BICUBIC, expand=True)
                y_fark = (genis.height - urun.height) // 2
                urun = genis
            else:
                y_fark = 0
            x = PANEL[0] + (pw - urun.width) // 2
            y = PANEL[1] + (self.urun_alani - urun.height) // 2 + dy
            pay = (golge.width - urun.width) // 2
            resim.paste(golge, (x - pay, y - pay + 16 - dy + y_fark), golge)
            resim.paste(urun, (x, y), urun)
            resim.paste(self.ad_seridi, (serit_x, serit_y), self.ad_seridi)
            return
        kaynak = self.panel_kaynak
        if self.sigdir:
            z, cx, cy = 1 + 0.04 * min(1.0, t / 30), 0.5, 0.5
        else:
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
        desen = re.compile(rf"^\W*{re.escape(aranan)}(?!\d)")
        for kelime, z_bas, _ in self.kelimeler:
            if bas <= z_bas < son and desen.search(kelime):
                return max(0.0, z_bas - bas)
        return yedek

    def _baglam_anlari(self):
        v = self.veri
        okunan, urun = v["okunan_yorum"], v.get("urun_yorumu", v["okunan_yorum"])
        g1 = self._kelime_zamani(1, str(okunan), 0.1)
        g2 = self._kelime_zamani(1, str(urun), g1 + 1.0) if urun != okunan else None
        return g1, g2

    def efekt_anlari(self):
        """Ses efektleri: açılışta çarpma, geçişlerde whoosh, sayılarda pop, kararda damga."""
        b, v = self.sahne_baslari, self.veri
        anlar = [(0.08, "damga")]
        for i in range(1, len(b)):
            if i != 4:  # karar sahnesinde damga sesi var
                anlar.append((max(0.0, b[i] - 0.12), "whoosh"))
        if len(b) > 1:
            g1, g2 = self._baglam_anlari()
            anlar.append((b[1] + g1, "pop"))
            if g2 is not None:
                anlar.append((b[1] + g2, "pop"))
        for sahne, alan in ((2, "ovulenler"), (3, "sikayetler")):
            if sahne < len(b):
                for i, oge in enumerate(v[alan][:3]):
                    anlar.append((b[sahne] + self._kelime_zamani(sahne, str(oge["sayi"]), 0.2 + i * 1.4), "pop"))
        if len(b) > 4:
            anlar.append((b[4] + 0.2, "damga"))
        return anlar

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
        """Adım sırası: Dosya #N · Övgü · Şikâyet · Karar. Şimdiki adım dolu, bitenler koyu, gelecekler boş."""
        p = self.p
        c = ImageDraw.Draw(resim)
        simdi = self._sahne_no(tg)
        font = F(30)
        x = KENAR - 30
        for sira, (sahne, ad) in enumerate(ADIMLAR, 1):
            metin = f"Dosya #{self.no}" if sira == 1 else ad
            renk = self._bolum_rengi(sahne)
            kenar = None
            if sira == 1:
                dolgu, yazi = p["cip"], p["cip_metin"]
            elif simdi == sahne:
                dolgu = renk
                yazi = (20, 20, 20) if 0.299 * renk[0] + 0.587 * renk[1] + 0.114 * renk[2] > 165 else (255, 255, 255)
            elif simdi > sahne:
                dolgu = tuple(int(renk[i] * 0.45 + p["kart"][i] * 0.55) for i in range(3))
                yazi = p["metin"]
            else:
                dolgu, yazi = p["kart"], p["ikincil"]
                kenar = tuple(min(255, int(c_ * 1.6) + 10) for c_ in p["iz"])
            en = c.textlength(metin, font=font) + 36
            b = 0
            if simdi == sahne and sira > 1:
                bas = self.sahne_baslari[sahne] if sahne < len(self.sahne_baslari) else 0
                b = int(5 * math.sin(math.pi * min(1.0, max(0.0, (tg - bas) / 0.4))))
            c.rounded_rectangle((x - b, ILERLEME_Y - b, x + en + b, ILERLEME_Y + 50 + b), 25 + b, fill=dolgu,
                                outline=kenar, width=2 if kenar else 0)
            c.text((x + 18, ILERLEME_Y + 8), metin, font=font, fill=yazi)
            x += en + 12

    @staticmethod
    def _kaydir(t):
        """Sahne başında bilgi alanının sağdan kayarak gelmesi için x kayması."""
        return int((1 - yumusak(t / 0.28)) * 140)

    def _kart(self, c, dx, ust, alt, renk=None):
        """Bilgi kartı; koyu temalarda çerçevesi bölüm renginde."""
        p = self.p
        kenar = renk if (renk and p["kenar_renkli"]) else p["kart_kenar"]
        c.rounded_rectangle((KENAR - 40 + dx, ust, G - KENAR + 40 + dx, alt), 30, fill=p["kart"],
                            outline=kenar, width=3 if kenar else 0)

    def _hap(self, c, x, y, metin, renk, boyut=30):
        """Renkli zeminli küçük başlık."""
        font = FS(boyut)
        en = c.textlength(metin, font=font)
        c.rounded_rectangle((x, y, x + en + 36, y + boyut + 20), (boyut + 20) // 2, fill=renk)
        c.text((x + 18, y + 8), metin, font=font, fill=(255, 255, 255))
        return y + boyut + 20

    def _renkli_satir(self, c, x, y, kelimeler, font, kontur=0):
        """[(kelime, renk)] listesini tek satırda yazar."""
        for kelime, renk in kelimeler:
            c.text((x, y), kelime, font=font, fill=renk, stroke_width=kontur, stroke_fill=(8, 10, 16))
            x += c.textlength(kelime + " ", font=font)

    # --- sahneler (t: sahne içi zaman, tg: videonun genel zamanı) -----------------
    def _kanca_gorseli(self):
        """Açılış yazısı: büyük ve dar harfler; rakamlar mavi, tırnak içindeki kelime kırmızı."""
        if getattr(self, "_kanca", None) is not None:
            return self._kanca
        p = self.p
        metin = tr_buyuk(self.veri["ekran_acilis"]).replace("“", "'").replace("”", "'").replace('"', "'")
        oran = re.search(r"(\d+)\s*/\s*(\d+)", metin)
        if oran:  # "9/61 alıcı" ilk bakışta zor okunuyor: büyük yazıda "9 alıcı", oran küçük etikette
            metin = metin.replace(oran.group(0), oran.group(1), 1)
        sayi = oran.group(1) if oran else (re.search(r"\d+", metin).group(0) if re.search(r"\d+", metin) else None)
        payda = self.veri.get("urun_yorumu", self.veri["okunan_yorum"])
        self._kanca_oran = f"{sayi}/{payda} ürün yorumu" if sayi and int(sayi) <= payda else None
        olcu = ImageDraw.Draw(Image.new("L", (1, 1)))
        for boyut in (150, 132, 116, 100, 88):
            satirlar = sar(olcu, metin, FD(boyut), G - 2 * KENAR + 40)
            if len(satirlar) <= 3:
                break
        satirlar = satirlar[:3]
        aralik = int(boyut * 1.08)
        tuval = Image.new("RGBA", (G, aralik * len(satirlar) + 40), (0, 0, 0, 0))
        c = ImageDraw.Draw(tuval)
        tirnakta = False
        for i, satir in enumerate(satirlar):
            parcalar = []
            for kelime in satir.split():
                if kelime.startswith("'"):
                    tirnakta = True
                renk = p["kirmizi"] if tirnakta else (p["vurgu"] if re.search(r"\d", kelime) else (255, 255, 255))
                if kelime.endswith("'") or kelime.endswith("'."):
                    tirnakta = False
                parcalar.append((kelime, renk))
            en = c.textlength(satir, font=FD(boyut))
            self._renkli_satir(c, (G - en) / 2, 10 + i * aralik, parcalar, FD(boyut), kontur=6)
        self._kanca = tuval
        return tuval

    def acilis(self, t, sure, tg):
        resim = self._taban(tg)
        kanca = self._kanca_gorseli()
        olcek = 1.0 + 0.45 * (1 - yumusak(t / 0.18))  # ekrana 'çarparak' gelir
        if abs(olcek - 1) > 0.01:
            kanca = kanca.resize((int(kanca.width * olcek), int(kanca.height * olcek)), Image.BILINEAR)
        y = ICERIK_Y + 40 + (self._kanca.height - kanca.height) // 2
        resim.paste(kanca, ((G - kanca.width) // 2, y), kanca)
        if self._kanca_oran and t > 0.35:
            c = ImageDraw.Draw(resim)
            font = F(32)
            en = c.textlength(self._kanca_oran, font=font) + 40
            x, yy = (G - en) / 2, ICERIK_Y + 40 + self._kanca.height + 6
            c.rounded_rectangle((x, yy, x + en, yy + 50), 25, fill=self.p["cip"])
            c.text((x + 20, yy + 8), self._kanca_oran, font=font, fill=self.p["vurgu"])
        return resim

    def baglam(self, t, sure, tg):
        """Sayaç: önce okunan yoruma kadar sayar, sonra ürünle ilgisiz yorumlar düşülür (200 → 192)."""
        resim = self._taban(tg)
        c = ImageDraw.Draw(resim)
        p, v = self.p, self.veri
        okunan, urun = v["okunan_yorum"], v.get("urun_yorumu", v["okunan_yorum"])
        g1, g2 = self._baglam_anlari()
        dx = self._kaydir(t)
        ust = ICERIK_Y + 10
        alt = ust + (300 if g2 is not None else 220)
        self._kart(c, dx, ust, alt, p["vurgu"])
        if g2 is None or t < g2:  # sahne başından sayar, sayı söylendiği anda hedefe varır
            sayi = int(round(okunan * yumusak(t / max(0.6, g1 + 0.25))))
        else:
            sayi = int(round(okunan - (okunan - urun) * yumusak((t - g2) / 0.6)))
        sol = KENAR - 10 + dx
        c.text((sol, ust + 22), str(sayi), font=FD(150), fill=p["metin"])
        x = sol + max(c.textlength(str(okunan), font=FD(150)), 150) + 34
        etiket = "ürün yorumu kaldı" if (g2 is not None and t >= g2 + 0.6) else "yorum okudum"
        c.text((x, ust + 50), etiket, font=FS(44), fill=p["metin"])
        kaynak = v.get("kaynak_etiketi") or ", ".join(k.get("ad", "") for k in v.get("kaynaklar") or []) \
            or "ekran görüntüleri"
        c.text((x, ust + 112), kaynak, font=F(32, False), fill=p["ikincil"])
        if g2 is not None and t >= g2:
            cikan = okunan - urun
            o = yumusak((t - g2) / 0.3)
            c.text((sol + int((1 - o) * 40), ust + 220), f"– {cikan} kargo, iade, satıcı yorumu",
                   font=F(36), fill=p["kirmizi"])
        return resim

    def _alinti_ciz(self, c, ust, renk, metin, dx):
        """Gerçek bir alıcıdan kısa, isimsiz alıntı."""
        p = self.p
        satirlar = sar(c, f"“{metin}”", F(36, False), G - 2 * KENAR - 20)[:2]
        yukseklik = len(satirlar) * 46 + 44
        if ust + yukseklik > ICERIK_ALT:
            return
        c.rectangle((KENAR - 30 + dx, ust + 4, KENAR - 24 + dx, ust + yukseklik - 10), fill=renk)
        for i, s in enumerate(satirlar):
            c.text((KENAR + dx, ust + i * 46), s, font=F(36, False), fill=p["metin"])
        imza = "— bir alıcı"
        c.text((G - KENAR - c.textlength(imza, font=F(26, False)) + dx, ust + len(satirlar) * 46 + 4), imza,
               font=F(26, False), fill=p["ikincil"])

    def _cubuklar(self, t, tg, sahne, baslik, renk, ogeler, alinti):
        resim = self._taban(tg)
        c = ImageDraw.Draw(resim)
        p = self.p
        dx = self._kaydir(t)
        ogeler = ogeler[:3]
        aralik = 92
        ust = ICERIK_Y
        alt = ust + 80 + len(ogeler) * aralik + 6
        self._kart(c, dx, ust, alt, renk)
        self._hap(c, KENAR - 14 + dx, ust - 22, baslik, renk)
        toplam = max(1, self.veri.get("urun_yorumu", self.veri["okunan_yorum"]))
        sag = G - KENAR + 12
        ilk_gir = None
        for i, oge in enumerate(ogeler):
            gir = self._kelime_zamani(sahne, str(oge["sayi"]), 0.2 + i * 1.4)
            ilk_gir = gir if ilk_gir is None else ilk_gir
            ilerleme = yumusak((t - gir) / 0.6)
            y = ust + 52 + i * aralik
            boyut = 40
            while boyut > 28 and c.textlength(oge["konu"], font=F(boyut)) > sag - KENAR - 170:
                boyut -= 4
            konu = sar(c, oge["konu"], F(boyut), sag - KENAR - 170)[:1]
            c.text((KENAR - 12 + dx, y + (40 - boyut) // 2), konu[0] if konu else "", font=F(boyut),
                   fill=p["metin"] if ilerleme > 0 else p["ikincil"])
            etiket = f"{oge['sayi']}/{toplam}"
            if ilerleme > 0:
                font = FS(int(40 + 12 * (1 - min(1, (t - gir) / 0.4))))
                en = c.textlength(etiket, font=font)
                c.text((sag - en + dx, y - 2), etiket, font=font, fill=renk)
            cy = y + 54
            c.rounded_rectangle((KENAR - 12 + dx, cy, sag + dx, cy + 14), 7, fill=p["iz"])
            dolu = int((sag - KENAR + 12) * oge["sayi"] / toplam * ilerleme)
            if dolu > 14:
                c.rounded_rectangle((KENAR - 12 + dx, cy, KENAR - 12 + dolu + dx, cy + 14), 7, fill=renk)
        if alinti and ilk_gir is not None and t > ilk_gir + 0.6:
            self._alinti_ciz(c, alt + 30, renk, alinti, dx)
        return resim

    def ovgu(self, t, sure, tg):
        return self._cubuklar(t, tg, 2, "EN ÇOK ÖVÜLEN", self.p["yesil"], self.veri["ovulenler"],
                              (self.veri.get("alintilar") or {}).get("ovgu"))

    def sikayet(self, t, sure, tg):
        return self._cubuklar(t, tg, 3, "EN ÇOK ŞİKÂYET", self.p["kirmizi"], self.veri["sikayetler"],
                              (self.veri.get("alintilar") or {}).get("sikayet"))

    def hukum(self, t, sure, tg):
        """Karar damgası ürünün üstüne basılır; altta 'Uygun / Değil' kartı."""
        resim = self._taban(tg)
        c = ImageDraw.Draw(resim)
        p, v = self.p, self.veri
        renk = self._hukum_rengi()
        if t > 0.3:
            satirlar = []
            if v.get("uygun"):
                satirlar += [("✓ ", p["yesil"], "Uygun: " + v["uygun"])]
            if v.get("uygun_degil"):
                satirlar += [("✗ ", p["kirmizi"], "Değil: " + v["uygun_degil"])]
            if not satirlar and v.get("kime_uygun"):
                satirlar = [("", p["metin"], v["kime_uygun"])]
            dizilmis = [(isaret, irenk, sar(c, metin, F(38), G - 2 * KENAR - 50)[:2])
                        for isaret, irenk, metin in satirlar]
            yukseklik = sum(len(s) * 50 + 18 for _, _, s in dizilmis) + 44
            ust = ICERIK_Y + 30
            self._kart(c, 0, ust, ust + yukseklik, renk)
            y = ust + 26
            for isaret, irenk, parcalar in dizilmis:
                if isaret:
                    yaz(c, (KENAR - 10, y), isaret.strip(), F(38), irenk)
                for s in parcalar:
                    c.text((KENAR + 34, y), s, font=F(38), fill=p["metin"])
                    y += 50
                y += 18
        metin = v["hukum"]
        font = FD(150 if len(metin) <= 8 else 128)
        sol, ust_, sag, alt = c.textbbox((0, 0), metin, font=font)
        en, boy = sag - sol + 110, alt - ust_ + 80
        damga = Image.new("RGBA", (en, boy), (0, 0, 0, 0))
        dc = ImageDraw.Draw(damga)
        dc.rounded_rectangle((7, 7, en - 7, boy - 7), 22, fill=p["damga_ic"], outline=renk + (255,), width=14)
        dc.text((55 - sol, 40 - ust_), metin, font=font, fill=renk + (255,))
        damga = damga.rotate(-6, expand=True, resample=Image.BICUBIC)
        olcek = 1.0 + 0.8 * (1 - yumusak(t / 0.25))
        damga = damga.resize((int(damga.width * olcek), int(damga.height * olcek)), Image.BICUBIC)
        if damga.width > G - 40:
            oran = (G - 40) / damga.width
            damga = damga.resize((int(damga.width * oran), int(damga.height * oran)), Image.BICUBIC)
        orta_y = (PANEL[1] + PANEL[3]) // 2 + 40
        resim.paste(damga, ((G - damga.width) // 2, orta_y - damga.height // 2), damga)
        return resim

    def kapanis(self, t, sure, tg):
        resim = self._taban(tg)
        c = ImageDraw.Draw(resim)
        p = self.p
        dx = self._kaydir(t)
        alt = [f"{A.KANAL_ADI} · Yorum dosyası #{self.no}"]
        if A.LINK_PROFILDE:
            alt.append("Link profilde · satış ortaklığı linki")
        ust = ICERIK_Y + 20
        self._kart(c, dx, ust, ust + 210 + 44 * len(alt), p["vurgu"])
        for i, (metin, renk) in enumerate((("Sıradaki dosyayı sen seç", p["metin"]),
                                          ("Yorumlara yaz ↓", p["vurgu"]))):
            if i == 1 and t < 0.25:
                continue
            en = c.textlength(metin, font=FS(54))
            c.text(((G - en) / 2 + dx, ust + 30 + i * 76), metin, font=FS(54), fill=renk)
        for i, s in enumerate(alt):
            en = c.textlength(s, font=F(30, False))
            c.text(((G - en) / 2 + dx, ust + 192 + i * 44), s, font=F(30, False), fill=p["ikincil"])
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


_altyazi_onbellek = {}


def _altyazi_gorseli(metin, p):
    """Kalın, büyük harfli altyazı: rakamlar (yoksa son kelime) vurgu renginde."""
    anahtar = (metin, p["vurgu"])
    if anahtar in _altyazi_onbellek:
        return _altyazi_onbellek[anahtar]
    kelimeler = tr_buyuk(metin).split()
    rakamli = [i for i, k in enumerate(kelimeler) if re.search(r"\d", k)]
    vurgulu = set(rakamli) if rakamli else ({len(kelimeler) - 1} if len(kelimeler) > 1 else set())
    olcu = ImageDraw.Draw(Image.new("L", (1, 1)))
    for boyut in (78, 70, 62):
        satirlar = sar(olcu, " ".join(kelimeler), FS(boyut), G - 2 * KENAR)
        if len(satirlar) <= 2:
            break
    satirlar = satirlar[:2]
    aralik = int(boyut * 1.18)
    tuval = Image.new("RGBA", (G, aralik * len(satirlar) + 30), (0, 0, 0, 0))
    c = ImageDraw.Draw(tuval)
    sira = 0
    for i, satir in enumerate(satirlar):
        parcalar = []
        for kelime in satir.split():
            parcalar.append((kelime, p["vurgu"] if sira in vurgulu else (255, 255, 255)))
            sira += 1
        en = c.textlength(satir, font=FS(boyut))
        x = (G - en) / 2
        for kelime, renk in parcalar:
            c.text((x, 8 + i * aralik), kelime, font=FS(boyut), fill=renk, stroke_width=7, stroke_fill=(8, 10, 16))
            x += c.textlength(kelime + " ", font=FS(boyut))
    if len(_altyazi_onbellek) > 200:
        _altyazi_onbellek.clear()
    _altyazi_onbellek[anahtar] = tuval
    return tuval


def _altyazi_ciz(resim, metin, p=None, gecen=1.0):
    """Altyazıyı çizer; her yeni parça kısa bir 'pop' ile gelir."""
    p = p or {"vurgu": SARI}
    gorsel = _altyazi_gorseli(metin, p)
    olcek = 0.86 + 0.14 * yumusak(gecen / 0.12)
    if olcek < 0.995:
        gorsel = gorsel.resize((int(gorsel.width * olcek), int(gorsel.height * olcek)), Image.BILINEAR)
    resim.paste(gorsel, ((G - gorsel.width) // 2, ALTYAZI_Y + (gorsel.height < 120) * 10), gorsel)


def videoyu_kurgula(veri, resimler, ses_yolu, hiz, no, cikti, tema=None):
    segmentler = [(rol, veri["senaryo"][rol]) for rol in ROLLER]
    baslangiclar, toplam, altyazi, kelimeler = _zamanlar(segmentler, hiz)
    # bölümler arasına kısa nefes payı: yapay zekâ sesi düz okumasın
    ses_yolu, hiz = miksaj.bosluk_ekle(ses_yolu, hiz, baslangiclar)
    baslangiclar, toplam, altyazi, kelimeler = _zamanlar(segmentler, hiz)
    kurgu = Kurgu(veri, resimler, no, kelimeler, baslangiclar, tema)
    sahneler = [getattr(kurgu, rol) for rol, _ in segmentler]
    efekt_yolu = None
    if miksaj.efektler_acik():
        efekt_yolu = miksaj.efekt_izi(kurgu.efekt_anlari(), toplam, Path(ses_yolu).with_name("efekt.wav"))
    girdiler, filtre = miksaj.ses_girdileri(ses_yolu, efekt_yolu, miksaj.muzik_sec(no), toplam)

    komut = ([FFMPEG, "-y", "-loglevel", "error",
              "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{G}x{Y}", "-r", str(FPS), "-i", "-"]
             + girdiler
             + ["-filter_complex", filtre, "-map", "0:v", "-map", "[a]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", "-t", f"{toplam:.2f}", "-movflags", "+faststart", str(cikti)])
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
                _altyazi_ciz(kare, altyazi[ay][2], kurgu.p, t - altyazi[ay][0])
            islem.stdin.write(kare.tobytes())
    finally:
        islem.stdin.close()
        islem.wait()
    if islem.returncode != 0:
        raise RuntimeError("ffmpeg videoyu oluşturamadı. ffmpeg kurulu mu?")
    for gecici in (ses_yolu, efekt_yolu):
        if gecici:
            Path(gecici).unlink(missing_ok=True)
    return cikti
