"""ElevenLabs ile senaryoyu senin ses klonunla seslendirir; altyazı için zaman bilgisini de alır."""
import base64
import subprocess

import requests

import ayarlar as A
from ayarlar import FFMPEG

URL = "https://api.elevenlabs.io/v1/text-to-speech/{ses}/with-timestamps"


class SesHatasi(Exception):
    pass


def _istek(metin, normalizasyon_kapali=True):
    govde = {
        "text": metin,
        "model_id": A.ELEVENLABS_MODEL,
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.85,
                           "style": 0.15, "use_speaker_boost": True},
    }
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
    yanit = _istek(metin)
    if yanit.status_code in (400, 422) and "normalization" in yanit.text:
        yanit = _istek(metin, normalizasyon_kapali=False)
    if yanit.status_code == 401:
        raise SesHatasi("ElevenLabs anahtarı geçersiz. Telegram'da /elevenlabs komutuyla yenisini gir.")
    if yanit.status_code != 200:
        raise SesHatasi(f"ElevenLabs hata verdi ({yanit.status_code}): {yanit.text[:300]}")
    veri = yanit.json()
    with open(hedef, "wb") as dosya:
        dosya.write(base64.b64decode(veri["audio_base64"]))
    hizalama = veri.get("alignment") or veri.get("normalized_alignment")
    if not hizalama:
        raise SesHatasi("ElevenLabs zaman bilgisini göndermedi.")
    return {
        "karakterler": hizalama["characters"],
        "baslangic": hizalama["character_start_times_seconds"],
        "bitis": hizalama["character_end_times_seconds"],
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
