"""Logika analisis bersama (dipakai notify.py & make_chart.py)."""
from datetime import timedelta

HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN = [
    "", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
    "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
]


def fmt(dstr):
    from datetime import datetime
    d = datetime.strptime(dstr, "%Y-%m-%d").date()
    return f"{d.day:02d} {BULAN[d.month]} {d.year}"


def fmt_dow(d):
    return f"{HARI[d.weekday()]} {d.day:02d} {BULAN[d.month]}"


def compute_insights(days, cfg, today, soil=None):
    """Jendela pemupukan terbaik, neraca air 30 hari, radar hari kering."""
    heavy = cfg.get("heavy_rain_mm", 25)
    dry = cfg.get("dry_threshold_mm", 2)
    by = {d["date"]: d for d in days}

    def P(d):
        r = by.get(d.isoformat())
        return r["precip"] if r and r.get("precip") is not None else None

    # Simulasi lembap tanah maju hari-demi-hari (lembap terkini + hujan
    # prakiraan) supaya rekomendasi tak menyarankan hari yang tanahnya masih
    # tergenang. Hanya dipakai bila data lembap tanah tersedia.
    def soil_at(cd):
        w = float(soil)
        d = today
        while d < cd:
            pv2 = P(d)
            if pv2 is None or pv2 < dry:
                w -= 7.0
            else:
                w += min(pv2, 40.0) * 0.9
            w = max(5.0, min(95.0, w))
            d = d + timedelta(days=1)
        return w

    best = None
    for i in range(16):
        cd = today + timedelta(days=i)
        pv = P(cd)
        if pv is None:
            continue
        score = 100
        why = []
        if pv >= heavy:
            score -= 60; why.append("hujan lebat hari itu")
        elif pv > 10:
            score -= 18
        nxt = (P(cd + timedelta(days=1)) or 0) + (P(cd + timedelta(days=2)) or 0)
        if nxt > 40:
            score -= 40; why.append("hujan deras sesudahnya")
        elif nxt < 1:
            score -= 8; why.append("nyaris tanpa air pelarut")
        else:
            score += 6; why.append("tanpa hujan deras 2 hari sesudahnya")
        sw = None
        if soil is not None:
            sw = soil_at(cd)
            if 25 <= sw <= 45:
                score += 12; why.append("tanah ~" + str(round(sw)) + "% (pas)")
            elif sw > 45:
                score -= 50; why.append("tanah masih terlalu basah")
            elif sw < 15:
                score -= 12; why.append("tanah terlalu kering")
        else:
            prior = (P(cd - timedelta(days=1)) or 0) + (P(cd - timedelta(days=2)) or 0)
            if prior < 2:
                score -= 15; why.append("tanah cenderung kering")
            elif prior > 60:
                score -= 10; why.append("tanah sangat basah")
        score = min(100, score)
        if best is None or score > best["score"]:
            best = {"date": cd, "score": score, "why": why, "precip": pv, "soil_est": sw}

    actuals = [d for d in days if d.get("kind") == "actual"][-30:]
    rain_total = sum(d["precip"] for d in actuals if d.get("precip") is not None)
    et0_total = sum((d.get("et0") or 0) for d in actuals)
    wb = rain_total - et0_total

    best_run = None
    cur_start = None
    cur_len = 0
    for i in range(16):
        cd = today + timedelta(days=i)
        pv = P(cd)
        if pv is not None and pv < dry:
            if cur_len == 0:
                cur_start = cd
            cur_len += 1
            if best_run is None or cur_len > best_run["len"]:
                best_run = {"start": cur_start, "len": cur_len}
        else:
            cur_len = 0
            cur_start = None
    upcoming_dry = 0
    for i in range(16):
        pv = P(today + timedelta(days=i))
        if pv is not None and pv < dry:
            upcoming_dry += 1
        else:
            break

    soon = sum((P(today + timedelta(days=i)) or 0) for i in range(3))
    return {
        "best": best,
        "water_balance": wb,
        "rain_total": rain_total,
        "et0_total": et0_total,
        "dry_longest": best_run,
        "upcoming_dry": upcoming_dry,
        "soon3": soon,
    }


def water_verdict(wb):
    if wb < 0:
        return "kurang"
    if wb > 150:
        return "berlebih"
    return "cukup"


def headline(ins, cfg):
    heavy = cfg.get("heavy_rain_mm", 25)
    if ins["soon3"] >= heavy * 1.5:
        return "⛈️ Hujan deras 3 hari ke depan — tunda pemupukan, akses panen bisa becek."
    if ins["upcoming_dry"] >= 3:
        return f"☀️ {ins['upcoming_dry']} hari kering berturut-turut — bagus untuk tebas, semprot, & panen."
    if ins["best"] and ins["best"]["score"] >= 70:
        return f"🌱 Jendela bagus untuk memupuk: {fmt_dow(ins['best']['date'])}."
    return "🌤️ Cuaca campur — lihat detail untuk atur pekerjaan kebun."


# ===== Tambahan: kode cuaca WMO & arah angin =====
WMO = {
    0: ("Cerah", "\u2600\ufe0f"),
    1: ("Cerah berawan", "\U0001F324\ufe0f"),
    2: ("Berawan sebagian", "\u26c5"),
    3: ("Mendung", "\u2601\ufe0f"),
    45: ("Berkabut", "\U0001F32B\ufe0f"),
    48: ("Kabut beku", "\U0001F32B\ufe0f"),
    51: ("Gerimis ringan", "\U0001F326\ufe0f"),
    53: ("Gerimis", "\U0001F326\ufe0f"),
    55: ("Gerimis lebat", "\U0001F327\ufe0f"),
    56: ("Gerimis beku", "\U0001F327\ufe0f"),
    57: ("Gerimis beku lebat", "\U0001F327\ufe0f"),
    61: ("Hujan ringan", "\U0001F326\ufe0f"),
    63: ("Hujan sedang", "\U0001F327\ufe0f"),
    65: ("Hujan lebat", "\u26c8\ufe0f"),
    66: ("Hujan beku", "\U0001F327\ufe0f"),
    67: ("Hujan beku lebat", "\U0001F327\ufe0f"),
    71: ("Salju ringan", "\U0001F328\ufe0f"),
    73: ("Salju", "\U0001F328\ufe0f"),
    75: ("Salju lebat", "\u2744\ufe0f"),
    77: ("Butiran salju", "\U0001F328\ufe0f"),
    80: ("Hujan lokal ringan", "\U0001F326\ufe0f"),
    81: ("Hujan lokal sedang", "\U0001F327\ufe0f"),
    82: ("Hujan lokal lebat", "\u26c8\ufe0f"),
    85: ("Hujan salju ringan", "\U0001F328\ufe0f"),
    86: ("Hujan salju lebat", "\u2744\ufe0f"),
    95: ("Badai petir", "\u26c8\ufe0f"),
    96: ("Badai petir + es", "\u26c8\ufe0f"),
    99: ("Badai petir + es lebat", "\u26c8\ufe0f"),
}


def weather_desc(code):
    """Kode WMO -> (keterangan, emoji)."""
    if code is None:
        return ("Tidak diketahui", "\U0001F324\ufe0f")
    try:
        return WMO.get(int(code), ("Tidak diketahui", "\U0001F324\ufe0f"))
    except (TypeError, ValueError):
        return ("Tidak diketahui", "\U0001F324\ufe0f")


DIRS = ["Utara", "Timur Laut", "Timur", "Tenggara",
        "Selatan", "Barat Daya", "Barat", "Barat Laut"]


def compass(deg):
    """Derajat arah angin (asal) -> nama mata angin Indonesia."""
    if deg is None:
        return ""
    try:
        idx = int((float(deg) % 360) / 45 + 0.5) % 8
        return DIRS[idx]
    except (TypeError, ValueError):
        return ""
