"""ElevenLabs ile senaryoyu senin ses klonunla seslendirir; altyazı için zaman bilgisini de alır."""
import base64
import logging
import subprocess
from pathlib import Path

import requests

import ayarlar as A
from ayarlar import FFMPEG

URL = "https://api.elevenlabs.io/v1/text-to-speech/{ses}/with-timestamps"
EL_UST_HIZ = 1.15  # ElevenLabs'in kendi hız ayarını bunun üstüne çıkarmıyoruz; kalanını ffmpeg ile hızlandırıyoruz
log = logging.getLogger("ses")


class SesHatasi(Exception):
    pass


def hiz_carpani():
    """/hiz ile ayarlanan konuşma hızı (1.0 = sesin kendi hızı)."""
    try:
        hiz = float(str(A.SES_HIZI).replace(",", "."))
    except ValueError:
        hiz = 1.25
    return max(0.8, min(1.6, hiz))


def _istek(metin, normalizasyon_kapali=True, hiz=1.0):
    govde = {
        "text": metin,
        "model_id": A.ELEVENLABS_MODEL,
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.85,
                           "style": 0.15, "use_speaker_boost": True},
    }
    if abs(hiz - 1) > 0.001:
        govde["voice_settings"]["speed"] = round(hiz, 2)
    if normalizasyon_kapali:
        # Sayıları biz Türkçe yazıya çeviriyoruz; ElevenLabs'in kendi (İngilizce) çevirisi karışmasın
        govde["apply_text_normalization"] = "off"
    return requests.post(
        URL.format(ses=A.ELEVENLABS_VOICE_ID),
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": A.ELEVENLABS_API_KEY, "Content-Type": "application/json"},
        json=govde,
        timeout=180,
    )


def seslendir(metin, hedef):
    hedef = Path(hedef)
    istenen = hiz_carpani()
    el_hiz = min(EL_UST_HIZ, istenen) if istenen >= 1 else max(0.7, istenen)
    yanit = _istek(metin, hiz=el_hiz)
    if yanit.status_code in (400, 422) and "speed" in yanit.text.lower():
        log.warning("ElevenLabs hız ayarını kabul etmedi; hızlandırma ffmpeg ile yapılacak")
        el_hiz = 1.0
        yanit = _istek(metin, hiz=el_hiz)
    if yanit.status_code in (400, 422) and "normalization" in yanit.text:
        yanit = _istek(metin, normalizasyon_kapali=False, hiz=el_hiz)
    if yanit.status_code == 401:
        raise SesHatasi("ElevenLabs anahtarı geçersiz. Telegram'da /elevenlabs komutuyla yenisini gir.")
    if yanit.status_code != 200:
        raise SesHatasi(f"ElevenLabs hata verdi ({yanit.status_code}): {yanit.text[:300]}")
    veri = yanit.json()
    hizalama = veri.get("alignment") or veri.get("normalized_alignment")
    if not hizalama:
        raise SesHatasi("ElevenLabs zaman bilgisini göndermedi.")
    ses = base64.b64decode(veri["audio_base64"])
    kalan = istenen / el_hiz
    if abs(kalan - 1) > 0.01:
        # Kalan hızlandırma: ffmpeg atempo sesin tonunu değiştirmeden hızlandırır; zamanlar da aynı oranda kısalır
        ham = hedef.with_name(hedef.stem + "_ham.mp3")
        ham.write_bytes(ses)
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(ham), "-filter:a", f"atempo={kalan:.4f}",
                        "-c:a", "libmp3lame", "-b:a", "160k", str(hedef)], check=True)
        ham.unlink(missing_ok=True)
    else:
        kalan = 1.0
        hedef.write_bytes(ses)
    return {
        "karakterler": hizalama["characters"],
        "baslangic": [z / kalan for z in hizalama["character_start_times_seconds"]],
        "bitis": [z / kalan for z in hizalama["character_end_times_seconds"]],
    }


def sahte_seslendir(metin, hedef):
    """Demo için: sessiz ses dosyası ve tahmini zamanlama üretir (API gerekmez)."""
    karakterler, baslangic, bitis = [], [], []
    t = 0.0
    for k in metin:
        sure = 0.058
        if k in ".!?":
            sure = 0.32
        elif k in ",;:":
            sure = 0.16
        karakterler.append(k)
        baslangic.append(round(t, 3))
        t += sure
        bitis.append(round(t, 3))
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "anullsrc=r=44100:cl=mono", "-t", f"{t + 0.5:.2f}", "-q:a", "9", str(hedef)],
        check=True,
    )
    return {"karakterler": karakterler, "baslangic": baslangic, "bitis": bitis}


def sesleri_listele(anahtar):
    """Hesaptaki klon sesleri döndürür: [(ad, voice_id)]. Anahtar geçersizse SesHatasi."""
    yanit = requests.get("https://api.elevenlabs.io/v1/voices",
                         headers={"xi-api-key": anahtar}, timeout=30)
    if yanit.status_code == 401:
        if "invalid_api_key" in yanit.text or "Invalid API key" in yanit.text:
            raise SesHatasi("Bu ElevenLabs anahtarı geçersiz.")
        raise SesHatasi("Anahtar geçerli ama sesleri okuma izni yok. ElevenLabs'te anahtarı "
                        "oluştururken 'Voices' iznini aç ya da /ses SES_ID ile elle gir.")
    if yanit.status_code != 200:
        raise SesHatasi(f"ElevenLabs hata verdi ({yanit.status_code}): {yanit.text[:200]}")
    sesler = yanit.json().get("voices") or []
    return [(v.get("name") or "isimsiz", v["voice_id"]) for v in sesler
            if v.get("category") in ("cloned", "professional") and v.get("voice_id")]
