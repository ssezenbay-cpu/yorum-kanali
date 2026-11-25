"""Ürün avı: Claude web'de araştırıp bu hafta videosu çekilecek ürün adaylarını puanlar."""
import html
import json
import logging
import re
import urllib.parse
from datetime import date

import anthropic

import ayarlar as A
from veriler import GRUP_ADLARI, dagilim, gecmis_metni, olcut_sec, grup_ozeti

log = logging.getLogger("urun_avi")

ISTEK = """Bugün {tarih}, Türkiye. "{kanal}" adlı yüzsüz bir TikTok / YouTube Shorts kanalı için bu hafta videosu çekilecek ürünleri araştır.

Kanalın formatı: bir ürünün Trendyol veya Hepsiburada'daki alıcı yorumlarını okuyup 30 saniyede "alınır mı" hükmü veriyor.
Gelir satış ortaklığı linklerinden geliyor. Elektronik dışı ürünlerde komisyon yüksek (Trendyol %15); elektronikte (telefon, bilgisayar, küçük ev aletleri: süpürge, airfryer, kahve makinesi dahil) %2 ama ürün pahalı olduğu için satış başına kazanç yine yüksek olabilir.

Web'de şunlara bak: Trendyol ve Hepsiburada'nın son satış ve kampanya açıklamaları, haber sitelerindeki "en çok satan / en çok aranan" haberleri, yaklaşan kampanyalar ve özel günler (yılbaşı, sevgililer günü, anneler günü, bayram, okul dönemi vb.), mevsim.

Aday kuralları:
- Ürün TİPİ öner (ör. "termos bardak", "robot süpürge"). Çok satan belli bir model biliniyorsa parantezde yaz.
- O ürün tipinde pazaryerinde yüzlerce yorumu olan modeller bulunmalı.
- Yorumların bölünmesi muhtemel olmalı: kalıp, dayanıklılık, ses, sızdırma, arıza gibi tartışılan bir konu olmalı.
- Hariç: takviye, ilaç, zayıflama, diş beyazlatma gibi sağlık iddiası gerektirenler; yaş sınırı veya güvenlik tartışması olan çocuk ürünleri; silah ve tehlikeli ürünler.
- Gruplar: "gunluk" = elektronik dışı ürünler; "ev_elektronigi" = 20.000 TL altı elektronik ve küçük ev aletleri; "pahali" = 20.000 TL üstü ürünler.
- Bu hafta tam olarak şu dağılımla 5 aday öner: {dagilim}.

{gecmis}

Puan kartı (her biri 1-5): talep (çok satan/aranan listelerde mi), yorum (yorum bolluğu), tartisma (yorumların bölünme ihtimali), zamanlama (mevsim, kampanya, özel gün uyumu), kazanc (fiyat x komisyon).
"neden" alanında yalnızca bulduğun kaynaklara dayan; tahminini kesin bilgi gibi yazma.
Arama yapamazsan ya da sonuç bulamazsan yine de genel bilginle doldur ve "donem" alanına "güncel veri bulunamadı" yaz; JSON'u her durumda döndür.

Araştırma bitince yalnızca şu JSON'u döndür, başka hiçbir şey yazma:
{{"donem": "bu haftanın öne çıkan bağlamı, en fazla 15 kelime",
 "adaylar": [{{"urun": "...", "grup": "gunluk|ev_elektronigi|pahali", "fiyat_bandi": "ör. 800-1.500 TL",
   "neden": "en fazla 20 kelime", "tartisma": "yorumlarda tartışılması muhtemel konu, en fazla 8 kelime",
   "puan": {{"talep": 0, "yorum": 0, "tartisma": 0, "zamanlama": 0, "kazanc": 0}},
   "arama": "pazaryerinde aranacak 1-4 kelime"}}],
 "kaynaklar": ["en önemli 3 kaynağın adresi"]}}"""


class AvHatasi(Exception):
    pass


def _json_bul(metin):
    eslesme = re.search(r"\{.*\}", metin or "", re.S)
    if not eslesme:
        return None
    try:
        return json.loads(eslesme.group(0))
    except json.JSONDecodeError:
        return None


def _tum_metin(icerik):
    return "".join(getattr(b, "text", "") for b in icerik if getattr(b, "type", "") == "text")


def _son_metin(icerik):
    """Son arama sonucundan sonraki metin bloklarını birleştirir (JSON orada olur)."""
    son_arac = max((i for i, b in enumerate(icerik) if getattr(b, "type", "") != "text"), default=-1)
    sonraki = "".join(getattr(b, "text", "") for b in icerik[son_arac + 1:] if getattr(b, "type", "") == "text")
    return sonraki if "{" in sonraki else _tum_metin(icerik)


DUZELT = ("Bulduklarına göre adayları şimdi yalnızca istenen JSON biçiminde ver. "
          "Yeni arama yapma, JSON dışında hiçbir şey yazma.")


def _sor(istemci, istek, web=True):
    """Claude'a sorar, gerekirse bir kez JSON'u düzeltmesini ister; sözlük döndürür."""
    mesajlar = [{"role": "user", "content": istek}]
    ek = {"tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}]} if web else {}
    duzeltme_istendi = False
    durum = "?"
    for _ in range(8):
        yanit = istemci.messages.create(model=A.CLAUDE_MODEL, max_tokens=4000, messages=mesajlar, **ek)
        icerik = list(yanit.content)
        durum = yanit.stop_reason
        aramalar = sum(1 for b in icerik if getattr(b, "type", "") == "server_tool_use")
        log.info("Ürün avı yanıtı: durum=%s, arama=%d, blok=%d", durum, aramalar, len(icerik))
        mesajlar.append({"role": "assistant", "content": yanit.content})
        if durum == "pause_turn":
            continue
        veri = _json_bul(_son_metin(icerik))
        if veri and veri.get("adaylar"):
            return veri
        log.warning("Ürün avı JSON vermedi (durum=%s): %s", durum, _tum_metin(icerik)[-1500:])
        if duzeltme_istendi:
            break
        mesajlar.append({"role": "user", "content": DUZELT})
        duzeltme_istendi = True
    raise AvHatasi(f"Araştırma sonucu okunamadı (durum: {durum}). Ayrıntı için /kayit yaz.")


def arastir():
    """Adayları bulur; (veri, web_kullanildi_mi, dagilim, ogrenildi_mi) döndürür."""
    if not A.ANTHROPIC_API_KEY:
        raise AvHatasi("Anthropic anahtarı yok. /anthropic ANAHTAR ile gir.")
    dag, ogrenildi = dagilim()
    dag_metni = ", ".join(f"{s} {g}" for g, s in dag.items() if s)
    istek = ISTEK.format(tarih=date.today().strftime("%d.%m.%Y"), kanal=A.KANAL_ADI,
                         dagilim=dag_metni, gecmis=gecmis_metni())
    istemci = anthropic.Anthropic(api_key=A.ANTHROPIC_API_KEY)
    web = True
    try:
        veri = _sor(istemci, istek, web=True)
    except anthropic.BadRequestError as hata:
        if "web search" not in str(hata).lower() and "web_search" not in str(hata).lower():
            raise
        log.warning("Web araması kullanılamadı, aramasız devam: %s", hata)
        web = False
        veri = _sor(istemci, istek, web=False)
    return veri, web, dag, ogrenildi


def _linkler(arama):
    q = urllib.parse.quote(arama)
    return (f'<a href="https://www.trendyol.com/sr?q={q}">Trendyol</a> · '
            f'<a href="https://www.hepsiburada.com/ara?q={q}">Hepsiburada</a>')


def mesaj_metni(veri, web, dag, ogrenildi):
    e = html.escape
    satirlar = ["🛒 <b>Bu haftanın ürün adayları</b>"]
    if veri.get("donem"):
        satirlar.append(e(str(veri["donem"])))
    for i, aday in enumerate(veri["adaylar"][:6], 1):
        puan = aday.get("puan") or {}
        try:
            toplam = sum(int(v) for v in puan.values())
        except (TypeError, ValueError):
            toplam = 0
        grup = GRUP_ADLARI.get(aday.get("grup"), "")
        ust = " · ".join(x for x in (grup, str(aday.get("fiyat_bandi") or ""),
                                     f"puan {toplam}/25" if toplam else "") if x)
        satirlar.append(f"\n<b>{i}. {e(str(aday.get('urun', '?')))}</b>\n{e(ust)}")
        if aday.get("neden"):
            satirlar.append(f"Neden: {e(str(aday['neden']))}")
        if aday.get("tartisma"):
            satirlar.append(f"Yorumlarda: {e(str(aday['tartisma']))}")
        satirlar.append(_linkler(str(aday.get("arama") or aday.get("urun") or "")))
    _, olcut_adi = olcut_sec(grup_ozeti())
    satirlar.append(
        f"\nDağılım: {dag['gunluk']} günlük, {dag['ev_elektronigi']} ev elektroniği, {dag['pahali']} pahalı"
        + (f" ({olcut_adi} sonuçlarına göre)" if ogrenildi else " (test dönemi)"))
    if not web:
        satirlar.append("⚠️ Web araması kullanılamadı; liste güncel veriye dayanmıyor.")
    kaynaklar = [str(k) for k in (veri.get("kaynaklar") or []) if str(k).startswith("http")][:3]
    if kaynaklar:
        satirlar.append("Kaynaklar: " + " · ".join(
            f'<a href="{e(k, quote=True)}">{e(urllib.parse.urlparse(k).netloc)}</a>' for k in kaynaklar))
    satirlar.append("\nLinkte sıralamayı \"En çok değerlendirilen\" yap; 1-2 yıldızlı yorumlardan da görüntü al.")
    return "\n".join(satirlar)[:4000]


def haftalik_mesaj():
    return mesaj_metni(*arastir())
