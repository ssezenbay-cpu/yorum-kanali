"""Ekran görüntülerini Claude'a okutur; özet, sayılar ve senaryoyu JSON olarak alır."""
import base64
import io
import json
import re

import anthropic
from PIL import Image, ImageOps

import ayarlar as A
from veriler import GRUPLAR, fiyat_sayi

ROLLER = ["acilis", "baglam", "ovgu", "sikayet", "hukum", "kapanis"]
HUKUMLER = {"ALINIR", "ALINMAZ", "DİKKATLİ AL"}
YASAK_IFADELER = ["denedim", "kullandım", "test ettim", "aldım ve", "bende de"]


class AnalizHatasi(Exception):
    pass


SISTEM = """Sen "{kanal}" adlı Türkçe bir YouTube Shorts ve TikTok kanalının yorum analistisin.
Kullanıcı sana bir e-ticaret ürün sayfasının ve o ürünün alıcı yorumlarının ekran görüntülerini gönderir.
Görevin: yalnızca bu görüntülerde gerçekten gördüğün bilgiye dayanarak yorumları saymak, özetlemek ve 30 saniyelik bir video senaryosu yazmak.

Kesin kurallar:
1. Hiçbir bilgi uydurma. Fiyat, puan veya toplam yorum sayısı okunamıyorsa boş bırak ve "uyarilar" listesine yaz.
2. "okunan_yorum" = görüntülerde metnini gerçekten okuyabildiğin yorum sayısı. Sitenin kendi "Değerlendirme Özeti" gibi yapay zekâ özetleri, puan dağılımı grafikleri ve satıcı bilgileri yorum değildir: sayılmaz, övgü ya da şikâyet kaynağı olarak kullanılmaz.
3. Ürünü anlatmayan yorumlar sayılmaz: kargo hızı, paketleme, satıcının ilgisi, "güler yüzlü", "teşekkürler", "tavsiye ederim" gibi tek başına bilgi vermeyen yorumlar ne övgü ne şikâyettir. Ürünün kendisini ilgilendirenler sayılır: kırık, eksik ya da taklit gelmesi, beden/kalıp, malzeme, performans, dayanıklılık.
   "urun_yorumu" = okunan yorumlardan ürünün kendisi hakkında bilgi veren yorum sayısı. Övgü ve şikâyet sayıları yalnızca bunların içinden sayılır ve urun_yorumu'nu geçemez.
4. Senaryoda rakamlar örneklemden verilir: "ürünü anlatan 30 yorumun 12'si" gibi. Bağlam bölümünde kaç yorum okunduğunu ve kaçının ürünü anlattığını söyle (ör. "40 yorum okudum, 30'u ürünü anlatıyordu"). "Binlerce yorum", "herkes" gibi abartı yok.
5. Ürünü sen kullanmadın: "denedim", "kullandım", "test ettim" gibi ifadeler yasak. "Alıcılar", "yorumlara göre" de.
6. Yorum yazanların adlarını kullanma, cümlelerini birebir alıntılama; kendi cümlelerinle özetle.
7. Sağlık, tedavi veya güvenlik iddiası yapma.
8. Hüküm: şikâyetler ürünün temel işlevini bozuyorsa veya ürünü anlatan yorumların yarısına yakınındaysa "ALINMAZ"; övgüler açıkça baskınsa "ALINIR"; karışıksa "DİKKATLİ AL".
9. Senaryo konuşma dilinde, kısa cümlelerle, toplam 60-80 kelime. Açılış en fazla 8 kelime ve bir rakam ya da hüküm içerir.
10. Senaryonun bölümleri sırayla okunacak; her bölüm bir öncekinin devamı gibi akmalı.

Yalnızca geçerli bir JSON nesnesi döndür, başka hiçbir şey yazma.
Görüntülerde ürün sayfası ya da yorum yoksa yalnızca {"hata": "kısa açıklama"} döndür."""

KULLANICI = """{n} ekran görüntüsü gönderiyorum. Bu video "Yorum dosyası #{no}" olacak.
Şu yapıda JSON döndür:
{{
  "urun_adi": "kısa ürün adı, en fazla 6 kelime",
  "kategori": "ürün tipi, 1-3 kelime (ör. termos, robot süpürge, kışlık bot)",
  "grup": "gunluk | ev_elektronigi | pahali  (pahali: 20.000 TL üstü; ev_elektronigi: daha ucuz elektronik ve küçük ev aletleri; gunluk: geri kalan her şey)",
  "fiyat": "ör. 1.299 TL ya da boş",
  "puan": "ör. 4,3 ya da boş",
  "toplam_yorum": "sayfada görünen toplam değerlendirme sayısı ya da boş",
  "okunan_yorum": 0,
  "urun_yorumu": 0,
  "satici": "görünüyorsa satıcı adı ve satıcı puanı, yoksa boş",
  "ovulenler": [{{"konu": "en fazla 4 kelime", "sayi": 0}}, {{"konu": "...", "sayi": 0}}],
  "sikayetler": [{{"konu": "en fazla 4 kelime", "sayi": 0}}, {{"konu": "...", "sayi": 0}}],
  "hukum": "ALINIR | ALINMAZ | DİKKATLİ AL",
  "kime_uygun": "en fazla 10 kelime: kime uygun ya da kime uygun değil",
  "ekran_acilis": "ilk karede büyük yazı, en fazla 6 kelime",
  "senaryo": {{
    "acilis": "...",
    "baglam": "fiyat, puan ve kaç yorum okunduğu",
    "ovgu": "en çok övülen iki şey, sayılarıyla",
    "sikayet": "en çok şikâyet edilen iki şey, sayılarıyla; 'ama asıl sorun' gibi merak cümlesiyle",
    "hukum": "hüküm ve kime uygun",
    "kapanis": "Link profilde. Yorum dosyası #{no}."
  }},
  "baslik": "en fazla 60 karakter, merak uyandıran",
  "aciklama": "2-3 cümle",
  "etiketler": ["5-8 etiket, # işareti olmadan"],
  "uyarilar": ["okunamayan veya belirsiz bilgiler"]
}}"""


def _resim_parcasi(yol):
    with Image.open(yol) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((1568, 1568))
        tampon = io.BytesIO()
        im.save(tampon, "JPEG", quality=85)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.b64encode(tampon.getvalue()).decode("ascii"),
        },
    }


def _json_cikar(metin):
    eslesme = re.search(r"\{.*\}", metin, re.S)
    if not eslesme:
        raise AnalizHatasi("Yapay zekâ geçerli bir yanıt vermedi. Tekrar dene.")
    try:
        return json.loads(eslesme.group(0))
    except json.JSONDecodeError as hata:
        raise AnalizHatasi(f"Yanıt okunamadı ({hata}). Tekrar dene.") from hata


def dogrula(veri, no):
    if "hata" in veri:
        raise AnalizHatasi(veri["hata"])
    eksik = [a for a in ("urun_adi", "okunan_yorum", "ovulenler", "sikayetler",
                         "hukum", "senaryo", "baslik") if a not in veri]
    if eksik:
        raise AnalizHatasi("Yanıtta eksik alanlar var: " + ", ".join(eksik))

    uyarilar = list(veri.get("uyarilar") or [])
    try:
        okunan = int(veri["okunan_yorum"])
    except (TypeError, ValueError):
        raise AnalizHatasi("Okunan yorum sayısı anlaşılamadı.")
    if okunan < 5:
        raise AnalizHatasi(f"Yalnızca {okunan} yorum okunabildi. Daha fazla yorum ekran görüntüsü gönder.")
    veri["okunan_yorum"] = okunan
    try:
        urun_yorumu = int(veri.get("urun_yorumu", okunan))
    except (TypeError, ValueError):
        urun_yorumu = okunan
    urun_yorumu = max(0, min(urun_yorumu, okunan))
    if urun_yorumu < 8:
        raise AnalizHatasi(
            f"{okunan} yorum okundu ama yalnızca {urun_yorumu} tanesi ürünü anlatıyor (gerisi kargo, teşekkür vb.). "
            "1-3 yıldız ve fotoğraflı yorumlardan daha fazla görüntü gönderip tekrar /hazirla yaz.")
    veri["urun_yorumu"] = urun_yorumu
    veri["satici"] = str(veri.get("satici") or "").strip()

    for alan in ("ovulenler", "sikayetler"):
        temiz = []
        for oge in (veri.get(alan) or [])[:2]:
            sayi = max(0, min(int(oge.get("sayi", 0) or 0), urun_yorumu))
            temiz.append({"konu": str(oge.get("konu", "")).strip(), "sayi": sayi})
        if not temiz:
            raise AnalizHatasi(f"'{alan}' listesi boş geldi.")
        veri[alan] = temiz

    hukum = str(veri["hukum"]).strip().upper().replace("DIKKATLI", "DİKKATLİ")
    if hukum not in HUKUMLER:
        hukum = "DİKKATLİ AL"
        uyarilar.append("Hüküm anlaşılamadı, 'DİKKATLİ AL' kullanıldı.")
    veri["hukum"] = hukum

    senaryo = veri["senaryo"]
    for rol in ROLLER:
        if not str(senaryo.get(rol, "")).strip():
            raise AnalizHatasi(f"Senaryonun '{rol}' bölümü boş geldi.")
        senaryo[rol] = " ".join(str(senaryo[rol]).split())
    if f"#{no}" not in senaryo["kapanis"]:
        senaryo["kapanis"] = senaryo["kapanis"].rstrip(".") + f". Yorum dosyası #{no}."

    tam_metin = " ".join(senaryo[r] for r in ROLLER)
    kelime = len(tam_metin.split())
    if kelime > 95:
        uyarilar.append(f"Senaryo uzun ({kelime} kelime); video 35 saniyeyi geçebilir.")
    kucuk = tam_metin.lower()
    for ifade in YASAK_IFADELER:
        if ifade in kucuk:
            uyarilar.append(f"Senaryoda '{ifade}' ifadesi var; yayından önce kontrol et.")

    veri["kategori"] = str(veri.get("kategori") or "").strip()
    grup = str(veri.get("grup") or "").strip().lower()
    fiyat = fiyat_sayi(veri.get("fiyat"))
    if fiyat and fiyat >= 20000:
        grup = "pahali"
    if grup not in GRUPLAR:
        grup = "gunluk"
    veri["grup"] = grup

    veri["ekran_acilis"] = str(veri.get("ekran_acilis") or senaryo["acilis"]).strip()
    veri["kime_uygun"] = str(veri.get("kime_uygun") or "").strip()
    veri["etiketler"] = [str(e).lstrip("#").replace(" ", "") for e in (veri.get("etiketler") or [])][:8]
    veri["uyarilar"] = uyarilar
    return veri


def analiz_et(resimler, no):
    istemci = anthropic.Anthropic(api_key=A.ANTHROPIC_API_KEY)
    icerik = [_resim_parcasi(r) for r in list(resimler)[:20]]
    icerik.append({"type": "text", "text": KULLANICI.format(n=len(icerik), no=no)})
    yanit = istemci.messages.create(
        model=A.CLAUDE_MODEL,
        max_tokens=2500,
        system=SISTEM.replace("{kanal}", A.KANAL_ADI),
        messages=[{"role": "user", "content": icerik}],
    )
    metin = "".join(getattr(b, "text", "") for b in yanit.content)
    return dogrula(_json_cikar(metin), no)


def anthropic_dogrula(anahtar):
    """Anahtar geçerliyse True döner (ücretsiz bir istekle)."""
    try:
        anthropic.Anthropic(api_key=anahtar).models.list(limit=1)
        return True
    except anthropic.AuthenticationError:
        return False
