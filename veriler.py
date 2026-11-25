"""Üretilen videoları ve yayın sonuçlarını (izlenme, tıklama, kazanç) saklar ve özetler."""
import json
import os
from datetime import date

from ayarlar import CALISMA

DOSYA = CALISMA / "videolar.json"
GRUPLAR = ["gunluk", "ev_elektronigi", "pahali"]
GRUP_ADLARI = {"gunluk": "Günlük ürün", "ev_elektronigi": "Ev elektroniği",
               "pahali": "Pahalı ürün", "bilinmiyor": "Grubu bilinmeyen"}


def sayi_bicim(n):
    return f"{int(round(n)):,}".replace(",", ".")


def fiyat_sayi(metin):
    """'12.999,90 TL' -> 12999.9 ; okunamazsa None."""
    temiz = "".join(ch for ch in str(metin or "") if ch.isdigit() or ch in ".,")
    if not temiz:
        return None
    if "," in temiz:
        temiz = temiz.replace(".", "").replace(",", ".")
    elif temiz.count(".") >= 1 and len(temiz.rsplit(".", 1)[-1]) == 3:
        temiz = temiz.replace(".", "")
    try:
        return float(temiz)
    except ValueError:
        return None


def _oku():
    try:
        return json.loads(DOSYA.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _yaz(veri):
    gecici = DOSYA.with_suffix(".tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(gecici, DOSYA)


def video_kaydet(no, analiz):
    veri = _oku()
    kayit = veri.get(str(no), {})
    kayit.update({
        "tarih": date.today().isoformat(),
        "urun": analiz.get("urun_adi", ""),
        "kategori": analiz.get("kategori", ""),
        "grup": analiz.get("grup", "gunluk"),
        "fiyat": analiz.get("fiyat", ""),
        "baslik": analiz.get("baslik", ""),
    })
    veri[str(no)] = kayit
    _yaz(veri)


def sonuc_kaydet(no, izlenme, tiklama, kazanc=None):
    veri = _oku()
    kayit = veri.setdefault(str(no), {"urun": "", "grup": "bilinmiyor"})
    kayit["izlenme"] = int(izlenme)
    kayit["tiklama"] = int(tiklama)
    if kazanc is not None:
        kayit["kazanc"] = float(kazanc)
    kayit["sonuc_tarihi"] = date.today().isoformat()
    _yaz(veri)
    return kayit


def _sonuclu():
    return {no: k for no, k in _oku().items() if "izlenme" in k}


def grup_ozeti():
    """Grup başına: n, ort. izlenme, ort. tıklama, kazanç girilen video sayısı ve ort. kazanç."""
    ozet = {}
    for kayit in _sonuclu().values():
        g = kayit.get("grup") or "bilinmiyor"
        o = ozet.setdefault(g, {"n": 0, "izlenme": 0, "tiklama": 0, "kn": 0, "kazanc": 0.0})
        o["n"] += 1
        o["izlenme"] += kayit["izlenme"]
        o["tiklama"] += kayit["tiklama"]
        if "kazanc" in kayit:
            o["kn"] += 1
            o["kazanc"] += kayit["kazanc"]
    for o in ozet.values():
        o["ort_izlenme"] = o["izlenme"] / o["n"]
        o["ort_tiklama"] = o["tiklama"] / o["n"]
        o["ort_kazanc"] = o["kazanc"] / o["kn"] if o["kn"] else None
    return ozet


def olcut_sec(ozet):
    """Gruplar arası karşılaştırmada kullanılacak ölçüt: kazanç > tıklama > izlenme."""
    gruplar = [o for g, o in ozet.items() if g in GRUPLAR and o["n"] >= 3]
    if gruplar and all(o["kn"] >= 2 for o in gruplar):
        return "ort_kazanc", "video başına kazanç"
    if gruplar and any(o["tiklama"] for o in gruplar):
        return "ort_tiklama", "video başına tıklama"
    return "ort_izlenme", "video başına izlenme"


def dagilim(ozet=None):
    """5 adayın gruplara dağılımı. Yeterli sonuç yoksa 2/2/1; varsa iyi gideni büyütür."""
    ozet = grup_ozeti() if ozet is None else ozet
    varsayilan = {"gunluk": 2, "ev_elektronigi": 2, "pahali": 1}
    alan, _ = olcut_sec(ozet)
    olculen = {g: (ozet[g].get(alan) or 0) for g in GRUPLAR if g in ozet and ozet[g]["n"] >= 3}
    if len(olculen) < 2 or not any(olculen.values()):
        return varsayilan, False
    slot = {g: 1 for g in GRUPLAR if g not in olculen}  # henüz denenmeyene bir hak
    kalan = 5 - sum(slot.values())
    toplam = sum(olculen.values())
    paylar = {g: kalan * v / toplam for g, v in olculen.items()}
    for g, p in paylar.items():
        slot[g] = int(p)
    for g in sorted(paylar, key=lambda g: paylar[g] - int(paylar[g]), reverse=True):
        if sum(slot.values()) >= 5:
            break
        slot[g] += 1
    return {g: slot.get(g, 0) for g in GRUPLAR}, True


def _satir(o, ad):
    parcalar = [f"{o['n']} video", f"ort. {sayi_bicim(o['ort_izlenme'])} izlenme",
                f"{sayi_bicim(o['ort_tiklama'])} tıklama"]
    if o["ort_kazanc"] is not None:
        parcalar.append(f"{sayi_bicim(o['ort_kazanc'])} TL")
    return f"{ad}: " + " · ".join(parcalar)


def rapor_metni():
    tumu = _oku()
    sonuclu = _sonuclu()
    if not sonuclu:
        return ("Henüz sonuç girilmedi.\n\nVideo yayınlandıktan 3-7 gün sonra şunu yaz:\n"
                "/sonuc DOSYA_NO İZLENME TIKLAMA [KAZANÇ]\nÖrnek: /sonuc 3 12000 40 350")
    ozet = grup_ozeti()
    satirlar = [f"📊 Sonuçlar ({len(sonuclu)} video)"]
    for g in GRUPLAR + ["bilinmiyor"]:
        if g in ozet:
            satirlar.append(_satir(ozet[g], GRUP_ADLARI[g]))
    _, olcut_adi = olcut_sec(ozet)

    def skor(item):
        k = item[1]
        return (k.get("kazanc", 0), k["tiklama"], k["izlenme"])

    en_iyi = sorted(sonuclu.items(), key=skor, reverse=True)[:3]
    satirlar.append("\nEn iyi 3:")
    for no, k in en_iyi:
        ek = f", {sayi_bicim(k['kazanc'])} TL" if "kazanc" in k else ""
        satirlar.append(f"#{no} {k.get('urun') or '?'}: {sayi_bicim(k['izlenme'])} izlenme, "
                        f"{sayi_bicim(k['tiklama'])} tıklama{ek}")
    bekleyen = [f"#{no}" for no, k in sorted(tumu.items(), key=lambda x: int(x[0]))
                if "izlenme" not in k]
    if bekleyen:
        satirlar.append("\nSonucu girilmemiş: " + ", ".join(bekleyen[-15:]))
    dag, ogrenildi = dagilim(ozet)
    satirlar.append(
        f"\nHaftalık liste dağılımı: {dag['gunluk']} günlük, {dag['ev_elektronigi']} ev elektroniği, "
        f"{dag['pahali']} pahalı" + (f" ({olcut_adi} ölçülerek)" if ogrenildi else " (varsayılan)"))
    return "\n".join(satirlar)


def gecmis_metni():
    """Ürün araştırmasına verilecek kısa geçmiş özeti."""
    sonuclu = _sonuclu()
    yapilanlar = sorted({k.get("urun") for k in _oku().values() if k.get("urun")})
    yapilan_satiri = ("Videosu çekilmiş ürünler (tekrar önerme): " + ", ".join(yapilanlar[-30:])
                      if yapilanlar else "")
    if not sonuclu:
        return "\n".join(x for x in ("Geçmiş sonuç yok; ilk haftalar test dönemi.", yapilan_satiri) if x)
    ozet = grup_ozeti()
    satirlar = ["Kanalın şimdiye kadarki sonuçları:"]
    for g in GRUPLAR:
        if g in ozet:
            satirlar.append("- " + _satir(ozet[g], GRUP_ADLARI[g]))
    for no, k in sorted(sonuclu.items(), key=lambda x: x[1]["izlenme"], reverse=True)[:5]:
        satirlar.append(f"- #{no} {k.get('urun')}: {k['izlenme']} izlenme, {k['tiklama']} tıklama")
    satirlar.append("İyi giden ürün tiplerine benzer ama aynısı olmayan adaylar öner.")
    if yapilan_satiri:
        satirlar.append(yapilan_satiri)
    return "\n".join(satirlar)
