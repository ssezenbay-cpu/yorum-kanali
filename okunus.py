"""Seslendirmeye gidecek metni Türkçe okunuşa çevirir; ekrandaki altyazı rakamlı kalır.

Örnekler: "1.839 TL" -> "bin sekiz yüz otuz dokuz lira", "4,6" -> "dört virgül altı",
"46'sı" -> "kırk altısı", "%15" -> "yüzde on beş", "QR" -> "kü ar", "#1" -> "bir",
"Stanley" -> "Stenli" (sözlükten; /okunus komutuyla Telegram'dan eklenebilir).
"""
import json
import os
import re

from ayarlar import CALISMA

SOZLUK_DOSYASI = CALISMA / "okunus.json"

# Bilinen marka ve kısaltmaların okunuşu (küçük harfle anahtar). Kullanıcı sözlüğü bunun üstüne yazar.
VARSAYILAN = {
    "stanley": "Stenli", "quencher": "Kuençır", "iphone": "Ayfon", "ipad": "Aypad", "apple": "Epıl",
    "airpods": "Eırpods", "xiaomi": "Şaomi", "philips": "Filips", "dyson": "Dayson", "dreame": "Drim",
    "roborock": "Roborok", "airfryer": "Erfrayır", "thermos": "Termos", "tefal": "Tefal",
    "tl": "lira", "₺": "lira", "qr": "kü ar", "usb": "yu es bi", "led": "led", "tv": "ti vi",
    "ml": "mililitre", "lt": "litre", "cm": "santim", "mm": "milimetre", "kg": "kilo", "gr": "gram",
    "mah": "miliamper saat", "gb": "gigabayt", "tb": "terabayt", "hz": "hertz", "w": "vat",
}
# Sayıdan hemen sonra gelince birim olarak okunanlar (tek başına "L" birim sayılmaz)
BIRIMLER = {"l": "litre", "lt": "litre", "g": "gram", "gr": "gram", "w": "vat", "v": "volt", "tl": "lira",
            "ml": "mililitre", "cm": "santim", "mm": "milimetre", "kg": "kilo", "mah": "miliamper saat",
            "gb": "gigabayt", "tb": "terabayt", "hz": "hertz", "m": "metre", "km": "kilometre"}

BIRLER = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
ONLAR = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]


def _uc_basamak(n):
    yuz, kalan = divmod(n, 100)
    on, bir = divmod(kalan, 10)
    parcalar = []
    if yuz:
        parcalar.append("yüz" if yuz == 1 else f"{BIRLER[yuz]} yüz")
    if on:
        parcalar.append(ONLAR[on])
    if bir:
        parcalar.append(BIRLER[bir])
    return " ".join(parcalar)


def sayi_oku(n):
    """Tam sayıyı Türkçe yazıya çevirir (0 - 999 milyar)."""
    n = int(n)
    if n == 0:
        return "sıfır"
    if n < 0:
        return "eksi " + sayi_oku(-n)
    parcalar = []
    for deger, ad in ((10 ** 9, "milyar"), (10 ** 6, "milyon"), (1000, "bin")):
        bolum, n = divmod(n, deger)
        if bolum:
            parcalar.append(ad if (bolum == 1 and ad == "bin") else f"{_uc_basamak(bolum)} {ad}")
    if n:
        parcalar.append(_uc_basamak(n))
    return " ".join(parcalar)


def _ondalik_oku(tam, kesir):
    bas = sayi_oku(tam)
    # Baştaki sıfırları tek tek oku: 0,05 -> sıfır virgül sıfır beş
    sifirlar = len(kesir) - len(kesir.lstrip("0"))
    kalan = kesir.lstrip("0")
    kesir_oku = " ".join(["sıfır"] * sifirlar + ([sayi_oku(int(kalan))] if kalan else []))
    return f"{bas} virgül {kesir_oku}"


SAYI = re.compile(r"^(?P<on>[%₺#]?)(?P<sayi>\d{1,3}(?:\.\d{3})+|\d+(?:[.,]\d+)?)(?P<ek>.*)$")


def _sayi_metni(sayi):
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", sayi):  # 1.839 / 12.999 -> binlik ayraç
        return sayi_oku(sayi.replace(".", ""))
    if "," in sayi or "." in sayi:  # 4,6 / 1.18 -> ondalık
        tam, kesir = re.split(r"[.,]", sayi, maxsplit=1)
        return _ondalik_oku(int(tam), kesir)
    return sayi_oku(int(sayi))


def sozluk():
    veri = dict(VARSAYILAN)
    try:
        veri.update({k.lower(): v for k, v in json.loads(SOZLUK_DOSYASI.read_text(encoding="utf-8")).items()})
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return veri


def sozluge_ekle(kelime, okunus):
    try:
        veri = json.loads(SOZLUK_DOSYASI.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        veri = {}
    if okunus:
        veri[kelime.lower()] = okunus
    else:
        veri.pop(kelime.lower(), None)
    gecici = SOZLUK_DOSYASI.with_suffix(".tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(gecici, SOZLUK_DOSYASI)


def kullanici_sozlugu():
    try:
        return json.loads(SOZLUK_DOSYASI.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


NOKTALAMA = ".,!?;:…\"“”)("
INCE = set("eiöü")
YUVARLAK = set("ouöü")
UNLU = set("aeıioöuüAEIİOÖUÜ")


def ek_uyumla(kok, ek):
    """Yazıdaki eki, okunan köke göre ünlü uyumuna sokar: lira + lik -> lık, lira + ye -> ya."""
    son = next((h for h in reversed(kok.lower()) if h in UNLU), "e")
    sonuc = []
    for harf in ek:
        kucuk = harf.lower()
        if kucuk in "ea":
            yeni = "e" if son in INCE else "a"
        elif kucuk in "ıiuü":
            if son in INCE:
                yeni = "ü" if son in YUVARLAK else "i"
            else:
                yeni = "u" if son in YUVARLAK else "ı"
        else:
            sonuc.append(harf)
            continue
        sonuc.append(yeni)
        son = yeni
    return "".join(sonuc)


def kelime_oku(kelime, onceki_sayi=False, sozluk_=None):
    """Tek bir kelimeyi (boşluksuz parça) okunuşa çevirir. Noktalama korunur."""
    sozluk_ = sozluk() if sozluk_ is None else sozluk_
    bas = len(kelime) - len(kelime.lstrip(NOKTALAMA))
    on_nokta, govde = kelime[:bas], kelime[bas:]
    son = len(govde.rstrip(NOKTALAMA))
    govde, arka = govde[:son], govde[son:]
    if not govde:
        return kelime

    # Sayılar: %15, ₺1.299, #1, 46'sı, 1.839, 4,6, 1.18, 5-7, 500ml
    if re.fullmatch(r"\d[\d.,]*-\d[\d.,]*", govde):
        sol, sag = govde.split("-", 1)
        return on_nokta + kelime_oku(sol, sozluk_=sozluk_) + " ile " + kelime_oku(sag, sozluk_=sozluk_) + arka
    eslesme = SAYI.match(govde)
    if eslesme:
        onek, sayi, ek = eslesme.group("on"), eslesme.group("sayi"), eslesme.group("ek")
        okunan = _sayi_metni(sayi)
        if onek == "%":
            okunan = "yüzde " + okunan
        elif onek == "₺":
            okunan += " lira"
        ek_temiz = ek.lstrip("'’")
        birim, _, birim_eki = ek_temiz.partition("'")
        if birim.lower() in BIRIMLER:  # 500ml, 2L, 1.299TL'lik
            birim_okunus = BIRIMLER[birim.lower()]
            return on_nokta + okunan + " " + birim_okunus + ek_uyumla(birim_okunus, birim_eki) + arka
        return on_nokta + okunan + ek_temiz + arka  # 46'sı -> kırk altısı

    # Sözlük: marka ve kısaltmalar, ekleriyle (TL'lik -> liralık, Stanley'nin -> Stenlinin)
    if re.search(r"['’]", govde):
        kok, _, ek = re.split(r"(['’])", govde, maxsplit=1)
    else:
        kok, ek = govde, ""
    anahtar = kok.lower()
    if onceki_sayi and anahtar in BIRIMLER:
        return on_nokta + BIRIMLER[anahtar] + ek_uyumla(BIRIMLER[anahtar], ek) + arka
    if anahtar in sozluk_:
        return on_nokta + sozluk_[anahtar] + ek_uyumla(sozluk_[anahtar], ek) + arka
    return kelime


def esle(segment_metinleri):
    """Her segmentin okunuşunu ve kelime eşlemesini çıkarır.

    Dönüş: (konusma_metni, kelimeler, segment_baslangiclari)
      kelimeler: [(ekrandaki_kelime, konusmadaki_bas, konusmadaki_son)]
      segment_baslangiclari: her segmentin konuşma metnindeki başlangıç indeksi
    """
    sozluk_ = sozluk()
    parcalar, kelimeler, seg_bas = [], [], []
    konum = 0
    for metin in segment_metinleri:
        if parcalar:
            konum += 1  # segmentler arası boşluk
        seg_bas.append(konum)
        seg_parca = []
        onceki_sayi = False
        for kelime in metin.split():
            okunan = kelime_oku(kelime, onceki_sayi, sozluk_) or kelime
            if seg_parca:
                konum += 1
            kelimeler.append((kelime, konum, konum + len(okunan)))
            seg_parca.append(okunan)
            konum += len(okunan)
            onceki_sayi = bool(re.match(r"^[%₺#]?\d", kelime))
        parcalar.append(" ".join(seg_parca))
    return " ".join(parcalar), kelimeler, seg_bas


def konusma_metni(segment_metinleri):
    return esle(segment_metinleri)[0]
