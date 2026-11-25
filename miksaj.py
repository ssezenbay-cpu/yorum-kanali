"""Videonun sesi: bölüm aralarına kısa boşluk, ses efektleri (whoosh, pop, damga) ve alçak sesli müzik.

Efekt sesleri burada matematiksel olarak üretilir (dışarıdan dosya yok, telif sorunu yok).
Müzik, kullanıcının Telegram'dan gönderdiği parçalardır (calisma/muzik); konuşma sırasında kendiliğinden kısılır.
"""
import array
import math
import random
import subprocess
import wave
from pathlib import Path

import ayarlar as A
from ayarlar import CALISMA, FFMPEG

ORNEK = 44100
BOLUM_ARASI = 0.3            # saniye: bölümler arasına eklenen sessizlik
MUZIK_KLASORU = CALISMA / "muzik"
MUZIK_UZANTILARI = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac")


# --- bölüm arası boşluk ---------------------------------------------------------
def _wav_oku(yol):
    gecici = Path(yol).with_name(Path(yol).stem + "_tek.wav")
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(yol), "-ac", "1", "-ar", str(ORNEK),
                    "-sample_fmt", "s16", str(gecici)], check=True)
    with wave.open(str(gecici), "rb") as w:
        veri = w.readframes(w.getnframes())
    gecici.unlink(missing_ok=True)
    return veri


def _wav_yaz(yol, veri):
    with wave.open(str(yol), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(ORNEK)
        w.writeframes(veri)


def bosluk_ekle(ses_yolu, hiz, sahne_baslari, sure=BOLUM_ARASI):
    """Her bölümün başına 'sure' kadar sessizlik ekler; yeni ses dosyasını ve kaydırılmış zamanları döndürür."""
    bas, bit = hiz["baslangic"], hiz["bitis"]
    kesimler = []
    for b in sahne_baslari[1:]:
        onceki = [e for e in bit if e <= b + 1e-6]
        son = max(onceki) if onceki else b
        kesimler.append((son + b) / 2 if son < b else b)
    ham = _wav_oku(ses_yolu)
    parcalar, onceki_bayt = [], 0
    bosluk = b"\x00\x00" * int(sure * ORNEK)
    for kesim in sorted(kesimler):
        bayt = min(len(ham), int(kesim * ORNEK) * 2)
        parcalar += [ham[onceki_bayt:bayt], bosluk]
        onceki_bayt = bayt
    parcalar.append(ham[onceki_bayt:])
    yeni = Path(ses_yolu).with_name(Path(ses_yolu).stem + "_bosluklu.wav")
    _wav_yaz(yeni, b"".join(parcalar))

    def kaydir(t):
        return t + sure * sum(1 for k in kesimler if k <= t)

    return yeni, {"karakterler": hiz["karakterler"], "baslangic": [kaydir(t) for t in bas],
                  "bitis": [kaydir(t) for t in bit]}


# --- efekt sesleri --------------------------------------------------------------
def _whoosh(rs):
    n = int(0.42 * ORNEK)
    cikti, alcak, cok_alcak = [], 0.0, 0.0
    for i in range(n):
        o = i / n
        a = 0.02 + 0.30 * math.sin(math.pi * o) ** 2       # filtre açılıp kapanır: "fşşş" süpürmesi
        alcak += a * (rs.uniform(-1, 1) - alcak)
        cok_alcak += 0.01 * (alcak - cok_alcak)
        cikti.append((alcak - cok_alcak) * math.sin(math.pi * o) ** 1.5 * 0.9)
    return cikti


def _pop(rs):
    n = int(0.11 * ORNEK)
    cikti, faz = [], 0.0
    for i in range(n):
        t = i / ORNEK
        frekans = 520 + 900 * math.exp(-t * 60)
        faz += 2 * math.pi * frekans / ORNEK
        cikti.append(math.sin(faz) * math.exp(-t * 38) * 0.55)
    return cikti


def _damga(rs):
    n = int(0.45 * ORNEK)
    cikti, faz, alcak = [], 0.0, 0.0
    for i in range(n):
        t = i / ORNEK
        frekans = 52 + 70 * math.exp(-t * 25)
        faz += 2 * math.pi * frekans / ORNEK
        govde = math.sin(faz) * math.exp(-t * 11)
        alcak += 0.18 * (rs.uniform(-1, 1) - alcak)
        tok = alcak * math.exp(-t * 45) * 1.6
        cikti.append(max(-1.0, min(1.0, (govde + tok) * 0.85)))
    return cikti


EFEKTLER = {"whoosh": (_whoosh, 0.30), "pop": (_pop, 0.42), "damga": (_damga, 0.62)}


def efekt_izi(anlar, toplam, hedef):
    """[(saniye, efekt_adı)] listesinden videonun boyunda bir efekt izi (wav) üretir."""
    rs = random.Random(7)
    hazir = {ad: [v * guc for v in uret(rs)] for ad, (uret, guc) in EFEKTLER.items()}
    iz = [0.0] * (int(toplam * ORNEK) + 1)
    for t, ad in anlar:
        ses = hazir.get(ad)
        if not ses:
            continue
        bas = max(0, int(t * ORNEK))
        for i, v in enumerate(ses[: max(0, len(iz) - bas)]):
            iz[bas + i] += v
    ornekler = array.array("h", (int(max(-1.0, min(1.0, v)) * 32000) for v in iz))
    _wav_yaz(hedef, ornekler.tobytes())
    return hedef


# --- müzik ----------------------------------------------------------------------
def muzik_listesi():
    if not MUZIK_KLASORU.exists():
        return []
    return sorted(p for p in MUZIK_KLASORU.iterdir() if p.suffix.lower() in MUZIK_UZANTILARI)


def muzik_sec(no):
    if str(A.MUZIK).strip() in ("0", "kapali", "kapalı"):
        return None
    liste = muzik_listesi()
    return liste[no % len(liste)] if liste else None


def muzik_sesi():
    try:
        return max(0.02, min(0.5, float(str(A.MUZIK_SES).replace(",", "."))))
    except ValueError:
        return 0.18


def efektler_acik():
    return str(A.EFEKT).strip() not in ("0", "kapali", "kapalı")


def ses_girdileri(ses_yolu, efekt_yolu, muzik_yolu, toplam):
    """ffmpeg'e eklenecek ses girdileri ve karıştırma filtresi. Video girdisi 0 numaradır."""
    girdiler = ["-i", str(ses_yolu)]
    adlar = ["[ses]"]
    # konuşma her videoda aynı yükseklikte olsun (-16 LUFS)
    filtre = [f"[1:a]aformat=sample_rates={ORNEK}:channel_layouts=mono,loudnorm=I=-16:TP=-2:LRA=11,"
              f"aresample={ORNEK},apad=whole_dur={toplam:.2f}"
              + (",asplit=2[ses][yan]" if muzik_yolu else "[ses]")]
    sira = 2
    if efekt_yolu:
        girdiler += ["-i", str(efekt_yolu)]
        filtre.append(f"[{sira}:a]aformat=sample_rates={ORNEK}:channel_layouts=mono[efekt]")
        adlar.append("[efekt]")
        sira += 1
    if muzik_yolu:
        girdiler += ["-stream_loop", "-1", "-i", str(muzik_yolu)]
        filtre.append(
            f"[{sira}:a]aformat=sample_rates={ORNEK}:channel_layouts=mono,atrim=0:{toplam:.2f},"
            f"loudnorm=I=-16:TP=-2:LRA=11,aresample={ORNEK},volume={muzik_sesi():.3f},afade=t=in:d=0.5,afade=t=out:st={max(0.0, toplam - 1.2):.2f}:d=1.2[m0]")
        # konuşma varken müzik kendiliğinden kısılır
        filtre.append("[m0][yan]sidechaincompress=threshold=0.02:ratio=5:attack=20:release=300[muzik]")
        adlar.append("[muzik]")
    filtre.append("".join(adlar) + f"amix=inputs={len(adlar)}:normalize=0:duration=first,"
                  "alimiter=limit=0.95,aformat=channel_layouts=stereo[a]")
    return girdiler, ";".join(filtre)
