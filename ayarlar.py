"""Ortak ayarlar: .env dosyasını okur, klasörleri ve yazı tiplerini hazırlar."""
import os
from pathlib import Path

from dotenv import load_dotenv

KOK = Path(__file__).resolve().parent
ENV = KOK / ".env"
load_dotenv(ENV, encoding="utf-8")


def _al(ad, varsayilan=""):
    return (os.getenv(ad) or varsayilan).strip()


TELEGRAM_TOKEN = _al("TELEGRAM_TOKEN").strip("`\"' ")
TELEGRAM_PROXY = _al("TELEGRAM_PROXY")
IZINLI_KULLANICI_ID = _al("IZINLI_KULLANICI_ID")
ANTHROPIC_API_KEY = _al("ANTHROPIC_API_KEY")
CLAUDE_MODEL = _al("CLAUDE_MODEL", "claude-sonnet-5-5")
ELEVENLABS_API_KEY = _al("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = _al("ELEVENLABS_VOICE_ID")
ELEVENLABS_MODEL = _al("ELEVENLABS_MODEL", "eleven_multilingual_v2")
KANAL_ADI = _al("KANAL_ADI", "Yorumları Okudum")
GITHUB_DEPO = _al("GITHUB_DEPO", "ssezenbay-cpu/yorum-kanali")
LINK_PROFILDE = _al("LINK_PROFILDE")  # satış ortaklığı linki profile eklenince "1" yapılır (/link ac)
GITHUB_DAL = _al("GITHUB_DAL", "main")
VIDEO_TEMA = _al("VIDEO_TEMA", "canli")  # canli | acik | sari | koyu  (/tema)
SES_HIZI = _al("SES_HIZI", "1.1")        # seslendirme hızı (/hiz); 1.15 üstü sonradan hızlandırılır
MUZIK = _al("MUZIK", "1")                # gönderilen müzikler videoya eklensin mi (/muzik ac|kapat)
MUZIK_SES = _al("MUZIK_SES", "0.18")     # müziğin ses seviyesi (/muzik ses 0.18)
EFEKT = _al("EFEKT", "1")                # whoosh / pop / damga efektleri (/efekt ac|kapat)
FFMPEG = _al("FFMPEG_YOLU", "ffmpeg") or "ffmpeg"

CALISMA = KOK / "calisma"
GELEN = CALISMA / "gelen"
CIKTI = KOK / "videolar"
SAYAC = KOK / "dosya_no.txt"
for _klasor in (CALISMA, GELEN, CIKTI):
    _klasor.mkdir(parents=True, exist_ok=True)

_FONT_ADAYLARI = {
    True: [
        _al("FONT_KALIN"),
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ],
    False: [
        _al("FONT_NORMAL"),
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
    ],
}


def font_bul(kalin=True):
    for yol in _FONT_ADAYLARI[kalin]:
        if yol and Path(yol).exists():
            return yol
    raise FileNotFoundError(
        "Türkçe karakter destekli bir yazı tipi bulunamadı. "
        ".env dosyasına FONT_KALIN ve FONT_NORMAL yollarını yaz."
    )


def sonraki_no():
    try:
        return int(SAYAC.read_text(encoding="utf-8").strip()) + 1
    except (FileNotFoundError, ValueError):
        return 1


def no_kaydet(no):
    SAYAC.write_text(str(no), encoding="utf-8")


def kaydet(ad, deger):
    """Bir ayarı .env dosyasına yazar ve çalışan programda hemen geçerli kılar."""
    deger = str(deger).strip()
    satirlar = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    yeni = f"{ad}={deger}"
    for i, satir in enumerate(satirlar):
        if satir.split("=", 1)[0].strip() == ad:
            satirlar[i] = yeni
            break
    else:
        satirlar.append(yeni)
    gecici = KOK / ".env.tmp"
    gecici.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    try:
        os.chmod(gecici, 0o600)
    except OSError:
        pass
    os.replace(gecici, ENV)
    os.environ[ad] = deger
    globals()[ad] = deger


def maskele(deger):
    return f"…{deger[-4:]}" if deger else "yok"


def eksik_ayarlar():
    gerekli = {
        "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "ELEVENLABS_API_KEY": ELEVENLABS_API_KEY,
        "ELEVENLABS_VOICE_ID": ELEVENLABS_VOICE_ID,
    }
    return [ad for ad, deger in gerekli.items() if not deger]
