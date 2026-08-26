#!/usr/bin/env python3
"""Susun ringkasan harian kebun: cetak ke log + kirim via Telegram (opsional).

Kanal WhatsApp/CallMeBot SUDAH DIHAPUS — dashboard GitHub Pages adalah
sumber utama. Tanpa secret Telegram, skrip hanya MENCETAK pesan ke log
Actions (mode pratinjau) dan tidak mengirim apa pun.

Telegram (opsional) — GRATIS, foto asli: TG_TOKEN, TG_CHAT_ID

Citra terbaru diambil otomatis dari repo Harvin (folder citra/<tanggal>).
Hanya modul standar Python.
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from analysis import (
    BULAN, HARI, compute_insights, fmt, fmt_dow, headline, water_verdict,
    weather_desc,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "data", "last_sent.json")
JENIS = {"pupuk": "🌱 Pupuk", "pruning": "✂️ Pruning", "tebas": "🌾 Tebas"}


def today_summary_lines(td):
    """Ringkasan cuaca hari ini untuk pesan (kondisi, suhu, angin, jam hujan)."""
    if not td:
        return []
    out = []
    cond = td.get("condition")
    emoji = td.get("emoji") or "🌥️"
    cloud = td.get("cloud")
    hum = td.get("humidity")
    if cond:
        extra = []
        if cloud is not None:
            extra.append("awan " + str(cloud) + "%")
        if hum is not None:
            extra.append("lembap " + str(hum) + "%")
        tail = (" · " + " · ".join(extra)) if extra else ""
        out.append(emoji + " " + cond + tail)
    bits = []
    tmin = td.get("tmin")
    tmax = td.get("tmax")
    if tmin is not None and tmax is not None:
        bits.append("🌡️ " + str(round(tmin)) + "–" + str(round(tmax)) + "°C")
    w = td.get("wind")
    wd = td.get("wind_dir")
    if w is not None:
        wtxt = "💨 " + str(round(w)) + " km/j"
        if wd:
            wtxt += " dari " + wd
        _g = td.get("gust")
        if _g is not None:
            wtxt += " (maks: " + str(round(_g)) + " km/j)"
        bits.append(wtxt)
    if bits:
        out.append(" · ".join(bits))
    rw = td.get("rain_windows") or []
    ph = td.get("precip_hours")
    if rw:
        cap = (" (±" + str(int(round(ph))) + " jam)") if ph is not None else ""
        out.append("⏱️ Jam hujan: " + ", ".join(rw) + " WIB" + cap)
    elif ph is not None and ph < 1:
        out.append("⏱️ Cenderung tanpa hujan berarti hari ini")
    return out


def today_detail_lines(td):
    """Baris tambahan (matahari, hembusan angin) untuk pesan detail."""
    if not td:
        return []
    out = []
    sr = td.get("sunrise")
    ss = td.get("sunset")
    if sr and ss:
        out.append("🌅 Matahari: terbit " + sr + ", terbenam " + ss + " WIB")
    return out


def load_json(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return json.load(f)


def http_json(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": "kebun-cuaca/1.0",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def chart_url(cfg):
    base = (cfg.get("dashboard_url") or "").strip().rstrip("/")
    return base + "/chart.png" if base else ""


# ---------- Ambil citra terbaru dari repo Harvin ----------
def harvin_latest(cfg):
    owner = (cfg.get("harvin_owner") or "").strip()
    repo = (cfg.get("harvin_repo") or "").strip()
    branch = (cfg.get("harvin_branch") or "main").strip()
    if not (owner and repo):
        return None
    api = "https://api.github.com/repos/" + owner + "/" + repo + "/contents/citra?ref=" + branch
    try:
        items = http_json(api)
    except Exception as e:
        print("Harvin: gagal daftar citra:", e)
        return None
    dates = sorted([it["name"] for it in items if it.get("type") == "dir"])
    if not dates:
        return None
    d = dates[-1]
    raw = "https://raw.githubusercontent.com/" + owner + "/" + repo + "/" + branch + "/citra/" + d
    # Pratinjau thumbnail WhatsApp lebih andal dari GitHub Pages daripada raw.
    pages = (cfg.get("harvin_pages_url") or "").strip().rstrip("/")
    base = (pages + "/citra/" + d) if pages else raw
    tc = (cfg.get("truecolor_name") or "1_warna_asli_terbaru.png").strip()
    nd = (cfg.get("ndvi_name") or "2_ndvi_terbaru.png").strip()
    meta = {}
    try:
        meta = http_json(raw + "/meta.json")
    except Exception:
        pass
    sat = cloud = None
    imgs = meta.get("images", {}) if isinstance(meta, dict) else {}
    info = imgs.get(tc) or (next(iter(imgs.values())) if imgs else {})
    if isinstance(info, dict):
        sat = info.get("sat")
        cloud = info.get("cloud")
    return {
        "date": d,
        "truecolor": base + "/" + tc,
        "ndvi": base + "/" + nd,
        "sat": sat, "cloud": cloud,
    }


def sat_label(harv):
    return str(harv.get("sat") or harv["date"])


def next_event(jadwal, jenis, today):
    cand = [
        e for e in jadwal.get("events", [])
        if e.get("type") == jenis
        and datetime.strptime(e["date"], "%Y-%m-%d").date() >= today
    ]
    cand.sort(key=lambda e: e["date"])
    return cand[0] if cand else None


def soon_events(jadwal, today, within=7):
    """Semua kegiatan dalam 0..within hari, urut terdekat."""
    out = []
    for e in jadwal.get("events", []):
        ed = datetime.strptime(e["date"], "%Y-%m-%d").date()
        dd = (ed - today).days
        if 0 <= dd <= within:
            out.append((dd, e))
    out.sort(key=lambda x: x[0])
    return out


def when_label(dd):
    return "hari ini" if dd == 0 else ("besok" if dd == 1 else str(dd) + " hari lagi")


# ---------- Blok LINGKUNGAN (karhutla / udara / pasang / banjir) ----------
def soil_label(pct):
    if pct is None:
        return "tidak tersedia"
    if pct < 15:
        return "kering"
    if pct < 30:
        return "agak kering"
    if pct < 40:
        return "lembap"
    return "basah"


FLOOD_NOTE = {
    "Normal": "Aman — aliran sungai normal, tak ada tanda banjir.",
    "Agak tinggi": "Pantau saja — sedikit di atas biasa, belum berbahaya.",
    "Tinggi": "Waspada — aliran cukup tinggi; cek parit & bagian rendah kebun.",
    "Sangat tinggi": "Siaga — aliran jauh di atas normal; risiko genangan/banjir.",
}


def neraca_sinergi(env, ins, sm=None):
    """Klausa singkat: kaitkan banjir/pasang dengan neraca air. Ditaruh TEPAT di
    bawah baris "Neraca air 30 hari" sehingga tidak mengulang angka/vonisnya."""
    if not env or not ins:
        return []
    wb = ins.get("water_balance")
    if wb is None:
        return []
    verd = water_verdict(wb)
    flood = env.get("flood") or {}
    trend = flood.get("trend")
    disch = flood.get("river_discharge")
    tide = env.get("tide") or {}
    high = (tide.get("high") or {}).get("h")
    ctx = []
    if disch is not None:
        ctx.append("sungai " + (str(trend) if trend else "stabil"))
    if high is not None:
        ctx.append("pasang " + str(high) + " m")
    ctxtxt = (" (" + ", ".join(ctx) + ")") if ctx else ""
    if verd == "berlebih":
        act = "air menumpuk" + ctxtxt + " → utamakan drainase, tunda pemupukan (hara tercuci), waspada genangan."
    elif verd == "kurang":
        act = "cadangan air menipis" + ctxtxt + " → tahan buka parit, tunda pemupukan sampai tanah lembap."
    else:
        act = "banjir & pasang belum mengancam" + ctxtxt + "."
    tag = ""
    if sm is not None:
        if verd == "kurang":
            ok = sm < 25
        elif verd == "berlebih":
            ok = sm >= 40
        else:
            ok = 25 <= sm < 45
        tag = " [tanah sepakat ✓]" if ok else " [cek: tanah beda arah ⚠]"
    return ["↳ " + act[0].upper() + act[1:] + tag]


def fire_confidence(fire, air, wr=None):
    """Gabungkan titik api (FIRMS) + kabut/asap (AOD) jadi satu penilaian keyakinan."""
    fire = fire or {}
    air = air or {}
    aod = air.get("aod")
    hot = (fire.get("count_within") or 0) > 0 or bool(fire.get("nearest"))
    smoky = aod is not None and aod >= 0.6
    hazy = aod is not None and 0.3 <= aod < 0.6
    if hot and smoky:
        msg = "🎯 Keyakinan tinggi: ada titik api + udara berasap → asap kemungkinan nyata."
    elif hot and hazy:
        msg = "🎯 Titik api + udara agak berkabut → pantau, asap mulai terasa."
    elif hot and aod is not None:
        msg = "🎯 Titik api terdeteksi, tapi udara masih bersih → asap belum sampai sini."
    elif hot:
        msg = "🎯 Titik api terdeteksi; data udara belum tersedia."
    elif smoky:
        msg = "🎯 Tak ada titik api dekat, tapi udara berasap → mungkin asap kiriman dari jauh."
    else:
        msg = ""
    if msg and wr:
        msg += " · risiko cuaca: " + str(wr)
    return msg


def env_lines(env, ins=None):
    """Ringkasan lingkungan (dikelompokkan per topik) untuk pesan terpisah."""
    if not env:
        return []
    L = ["🌏 *LINGKUNGAN SEKITAR*", ""]
    fire = env.get("fire") or {}
    st = fire.get("status")
    near = fire.get("nearest")
    wr = (fire.get("weather_risk") or {}).get("level")
    if st == "tidak tersedia":
        L.append("🔥 *Karhutla: data belum aktif*")
        L.append(" - Atur FIRMS_MAP_KEY untuk mengaktifkan")
    elif near:
        icon = "🚨" if st == "bahaya" else ("⚠️" if st == "waspada" else "🔥")
        loc = (", " + near["place"]) if near.get("place") else ""
        L.append(icon + " *Karhutla: " + str(st).upper() + "*")
        _src = ((" (" + str(near["src"]) + ")")
                if near.get("src") in ("SIPONGI", "BMKG") else "")
        L.append(" - Titik api terdekat " + str(near["km"]) + " km (" + str(near["dir"]) + loc + ")" + _src)
        tail = str(fire.get("count_within", 0)) + " titik ≤" + str(fire.get("warn_km", 50)) + " km"
        if near.get("acq"):
            tail += " · deteksi " + str(near["acq"])
        L.append(" - " + tail)
    else:
        L.append("🔥 *Karhutla: AMAN*")
        L.append(" - Tak ada titik api terdeteksi di sekitar")
    _fc = fire_confidence(fire, env.get("air"), wr)
    if _fc:
        _fc2 = _fc[2:] if _fc.startswith("🎯 ") else _fc
        if " · risiko cuaca: " in _fc2:
            _main, _risk = _fc2.split(" · risiko cuaca: ", 1)
            L.append(" - " + _main.strip())
            L.append(" - Risiko cuaca: " + _risk.strip())
        else:
            L.append(" - " + _fc2.strip())
    sp = fire.get("sipongi") or {}
    # Label sumber sekunder mengikuti sumber NYATA yang berhasil dibaca
    # (SIPONGI kalau SiPongi+ terbaca, BMKG kalau pakai sumber pengganti).
    _slabel = str(sp.get("source_label") or "SIPONGI").split(" ")[0].upper()
    if sp.get("status") and sp.get("status") != "tidak tersedia" \
            and fire.get("primary_src") not in ("SIPONGI", "BMKG"):
        if sp.get("count_within"):
            _sn = sp.get("nearest") or {}
            _sp = " - Cek silang " + _slabel + ": " + str(sp["count_within"]) + " titik ≤" + str(sp.get("warn_km", 50)) + " km"
            if _sn.get("km") is not None:
                _sp += " · terdekat " + str(_sn["km"]) + " km (" + str(_sn.get("dir", "")) + ")"
            L.append(_sp)
        else:
            L.append(" - Cek silang " + _slabel + ": nihil di sekitar kebun")
    elif sp.get("status") == "tidak tersedia":
        # Sumber ke-2/ke-3 tak terbaca: tetap tampilkan barisnya dengan tanda
        # hubung, biar kelihatan lapisannya ada tapi datanya belum masuk.
        L.append(" - Cek silang: —")
    if fire.get("crosscheck"):
        L.append(" - ⚠️ " + str(fire["crosscheck"]))
    if near and fire.get("map"):
        L.append(" - 🔎 peta hotspot " + fire["map"])
    air = env.get("air") or {}
    if air.get("us_aqi") is not None:
        L.append("")
        L.append("😷 *Udara: " + str(air.get("category")) + " (AQI " + str(air["us_aqi"]) + ")*")
        if air.get("pm2_5") is not None:
            L.append(" - PM2.5 " + str(round(air["pm2_5"])) + " µg/m³")
        if air.get("uv") is not None:
            _uv = "UV skrg " + str(air["uv"])
            if air.get("uv_max") is not None:
                _win = ""
                if air.get("uv_peak_from") and air.get("uv_peak_to"):
                    _win = ", " + str(air["uv_peak_from"]) + "–" + str(air["uv_peak_to"])
                _uv += " (maks " + ("%g" % air["uv_max"]) + _win + ")"
            else:
                _uv += " (" + str(air.get("uv_cat")) + ")"
            L.append(" - " + _uv)
        if air.get("haze") and air.get("haze") != "tidak tersedia":
            _hz = "Kabut: " + str(air["haze"])
            if air.get("aod") is not None:
                _hz += " (AOD " + str(air["aod"]) + ")"
            L.append(" - " + _hz)
    tide = env.get("tide")
    if tide:
        L.append("")
        L.append("🌊 *Air pasang* (" + str(tide["point_name"]) + " ~" + str(tide["km"]) + " km " + str(tide["dir"]) + ")")
        _ext = tide.get("extremes") or []
        if _ext:
            for _e in _ext:
                _ar = "↑ pasang" if _e["type"] == "pasang" else "↓ surut"
                L.append(" - " + _ar + " " + str(_e["time"]) + " (" + str(_e["h"]) + " m)")
        else:
            L.append(" - ↑ pasang tertinggi " + str(tide["high"]["h"]) + " m pukul " + str(tide["high"]["time"]))
            L.append(" - ↓ surut terendah " + str(tide["low"]["h"]) + " m pukul " + str(tide["low"]["time"]))
    flood = env.get("flood")
    if flood and flood.get("river_discharge") is not None:
        _st = flood.get("status") or "-"
        L.append("")
        L.append("🏞️ *Debit sungai: " + str(flood["river_discharge"]) + " m³/s — " + _st + "*")
        if flood.get("baseline") is not None:
            L.append(" - Biasanya ~" + str(flood["baseline"]) + " m³/s")
        _note = FLOOD_NOTE.get(_st)
        if _note:
            L.append(" - " + _note)
    L.append("")
    return L


# ---------- PESAN 1: HEADLINE ----------
def build_headline(cfg, jadwal, cuaca, today, harv):
    """Ringkasan singkat (1-2 kalimat) + pengingat mendesak. Detail ada di pesan bawah."""
    days = cuaca.get("days", [])
    by = {d["date"]: d for d in days}
    ins = compute_insights(days, cfg, today)
    L = []
    L.append("🌴 *" + cfg.get("farm_name", "Kebun") + "* — "
             + HARI[today.weekday()] + ", " + f"{today.day:02d} {BULAN[today.month]} {today.year}")
    L.append("")

    # Kalimat inti: vonis cuaca + kondisi hari ini (ringkas, tanpa daftar).
    lead = headline(ins, cfg)
    t = by.get(today.isoformat())
    td = cuaca.get("today") or {}
    cond = (td.get("condition") or "").strip().lower()
    clause = ""
    if cond:
        clause = " Hari ini " + cond
        precip = t.get("precip") if t else None
        if precip is not None:
            clause += " (" + str(precip) + " mm)"
        clause += "."
    L.append(lead + clause)
    L.append("")

    # PENGINGAT H-7: hanya kegiatan mendesak (0-7 hari) — nilai tinggi, tampil sekali di sini.
    soon = soon_events(jadwal, today, 7)
    if soon:
        L.append("⏰ *PENGINGAT 7 HARI:*")
        for dd, e in soon:
            L.append("   " + JENIS.get(e["type"], "•") + " " + e["label"] + " — *" + when_label(dd) + "* (" + fmt(e["date"]) + ")")
        L.append("")

    L.append("📩 Rincian cuaca, lingkungan & jadwal di bawah ⬇️")
    return "\n".join(L)


# ---------- PESAN 2: DETAIL (dipecah 2 bagian agar tidak terpotong) ----------
def build_detail(cfg, jadwal, cuaca, today, harv, env=None):
    days = cuaca.get("days", [])
    by = {d["date"]: d for d in days}
    heavy = cfg.get("heavy_rain_mm", 25)
    dry = cfg.get("dry_threshold_mm", 2)
    ins = compute_insights(days, cfg, today, (cuaca.get("today") or {}).get("soil_moist"))
    td = cuaca.get("today") or {}
    t = by.get(today.isoformat())
    _sm = td.get("soil_moist")

    # ===== Bagian A1: cuaca hari ini + neraca air =====
    A1 = []
    A1.append("*Status " + cfg.get("farm_name", "Kebun") + "*")
    A1.append(HARI[today.weekday()] + ", " + f"{today.day:02d} {BULAN[today.month]} {today.year}")
    A1.append("")
    cond = td.get("condition")
    emoji = td.get("emoji") or "🌥️"
    A1.append("☁�� *Cuaca hari ini*")
    if cond:
        A1.append(emoji + " " + cond)
    if t and t.get("precip") is not None:
        prob = (" (kemungkinan " + str(t["prob"]) + "%)") if t.get("prob") is not None else ""
        A1.append(" - Hujan " + str(t["precip"]) + " mm" + prob)
    _ch = []
    if td.get("cloud") is not None:
        _ch.append("awan " + str(td["cloud"]) + "%")
    if td.get("humidity") is not None:
        _ch.append("lembap " + str(td["humidity"]) + "%")
    if _ch:
        _chs = " · ".join(_ch)
        A1.append(" - " + _chs[0].upper() + _chs[1:])
    if td.get("tmin") is not None and td.get("tmax") is not None:
        A1.append(" - Suhu " + str(round(td["tmin"])) + "–" + str(round(td["tmax"])) + "°C")
    if td.get("wind") is not None:
        _wt = " - Angin " + str(round(td["wind"])) + " km/j"
        if td.get("wind_dir"):
            _wt += " dari " + td["wind_dir"]
        if td.get("gust") is not None:
            _wt += " (maks " + str(round(td["gust"])) + ")"
        A1.append(_wt)
    _rw = td.get("rain_windows") or []
    _ph = td.get("precip_hours")
    if _rw:
        _cap = (" (±" + str(int(round(_ph))) + " jam)") if _ph is not None else ""
        A1.append(" - Jam hujan " + ", ".join(_rw) + " WIB" + _cap)
    elif _ph is not None and _ph < 1:
        A1.append(" - Cenderung tanpa hujan berarti hari ini")
    if td.get("sunrise") and td.get("sunset"):
        A1.append(" - Matahari " + td["sunrise"] + " – " + td["sunset"] + " WIB")
    A1.append("")
    A1.append("💧 *Neraca air 30 hari: " + str(round(ins["water_balance"])) + " mm (" + water_verdict(ins["water_balance"]) + ")*")
    if ins.get("rain_total") is not None and ins.get("et0_total") is not None:
        A1.append(" - Hujan " + str(round(ins["rain_total"])) + " mm · Penguapan ET₀ " + str(round(ins["et0_total"])) + " mm")
    if _sm is not None:
        A1.append(" - Lembap tanah (~10–27 cm): " + str(_sm) + "% (" + soil_label(_sm) + ")")
    for _n in neraca_sinergi(env, ins, _sm):
        _nn = _n[2:] if _n.startswith("↳ ") else _n
        A1.append(" - " + _nn.strip())

    # ===== Bagian A2: prakiraan + rekomendasi kerja =====
    A2 = []
    A2.append("📅 *Prakiraan 3 hari*")
    for i in range(1, 4):
        d = today + timedelta(days=i)
        row = by.get(d.isoformat())
        if not row:
            continue
        p = row.get("precip")
        p = (str(p) + " mm") if p is not None else "-"
        emo = weather_desc(row.get("code"))[1] if row.get("code") is not None else ""
        A2.append(" - " + HARI[d.weekday()] + f" {d.day:02d} {BULAN[d.month]}: " + p + ((" " + emo) if emo else ""))
    if ins["best"]:
        b = ins["best"]
        verdict = "ideal" if b["score"] >= 70 else ("cukup baik" if b["score"] >= 55 else "kurang ideal")
        A2.append("")
        A2.append("🎯 *Hari terbaik memupuk (16 hr): " + fmt_dow(b["date"]) + " — " + verdict + "*")
        why = b["why"][:2]
        _wy = ", ".join(why) if why else "kondisi seimbang untuk memupuk"
        A2.append(" - " + _wy[0].upper() + _wy[1:])
        if _sm is not None:
            _is_today = (b["date"] == today)
            if _sm >= 45:
                if _is_today:
                    A2.append(" - Tanah kini " + str(_sm) + "% (basah) → hara mudah tercuci; tunggu agak kering")
                else:
                    A2.append(" - Tanah kini " + str(_sm) + "% (basah), terlalu becek hari ini → tunggu " + fmt_dow(b["date"]) + " saat tanah lebih kering")
            elif _sm < 20:
                if _is_today:
                    A2.append(" - Tanah kini " + str(_sm) + "% (kering) → butiran sukar larut; tunggu ada lembap")
                else:
                    A2.append(" - Tanah kini " + str(_sm) + "% (kering) → " + fmt_dow(b["date"]) + " (setelah ada hujan ringan) lebih pas")
            else:
                A2.append(" - Tanah kini " + str(_sm) + "% (lembap) → kelembapan pas untuk memupuk")
    if ins["dry_longest"]:
        sdry = ins["dry_longest"]
        A2.append("")
        A2.append("☀️ *Rentang kering terpanjang: " + str(sdry["len"]) + " hari mulai " + fmt_dow(sdry["start"]) + "*")
        A2.append(" - Cocok untuk tebas & semprot — herbisida tak terbilas hujan")

    # ===== Bagian B: jadwal kegiatan =====
    def rain_advice(dstr):
        row = by.get(dstr)
        if not row or row.get("precip") is None:
            return "🕒 Prakiraan belum tersedia — cek mendekati tanggal"
        p = row["precip"]
        if p >= heavy:
            return "⚠️ Hujan lebat (" + str(p) + " mm) — risiko hara tercuci"
        if p < dry:
            return "☀️ Cenderung kering (" + str(p) + " mm) — hara lambat larut"
        return "✅ Kondisi baik (" + str(p) + " mm)"

    B = []
    B.append("🗓️ *Jadwal kegiatan — " + cfg.get("farm_name", "Kebun") + "*")
    pupuk_next = next_event(jadwal, "pupuk", today)
    if pupuk_next:
        _pdate = pupuk_next["date"]
        _same = [e for e in jadwal.get("events", []) if e.get("type") == "pupuk" and e["date"] == _pdate]
        d = datetime.strptime(_pdate, "%Y-%m-%d").date()
        B.append("")
        B.append("🌱 *Pupuk terjadwal — " + fmt(_pdate) + " (" + str((d - today).days) + " hari lagi)*")
        for _e in _same:
            B.append(" - " + _e["label"])
        B.append(" - " + rain_advice(_pdate))
    for jenis in ("pruning", "tebas"):
        e = next_event(jadwal, jenis, today)
        if e:
            d = datetime.strptime(e["date"], "%Y-%m-%d").date()
            _emoji, _word = JENIS[jenis].split(" ", 1)
            B.append("")
            B.append(_emoji + " *" + _word + "*")
            B.append(" - " + e["label"] + " — " + fmt(e["date"]) + " (" + str((d - today).days) + " hari lagi)")
    if harv and harv.get("cloud") is not None:
        B.append("")
        B.append("🛰️ Citra satelit " + sat_label(harv) + " · awan " + str(harv["cloud"]) + "% (foto menyusul)")
    B.append("")
    wurl = (cfg.get("dashboard_url") or "").strip()
    curl = (cfg.get("citra_dashboard_url") or "").strip()
    if wurl:
        B.append("📊 Dashboard cuaca: " + wurl)
    if curl:
        B.append("🛰️ Dashboard citra: " + curl)

    parts = []
    a1 = chr(10).join(A1).strip()
    if a1:
        parts.append(a1)
    a2 = chr(10).join(A2).strip()
    if a2:
        parts.append(a2)
    env_msg = chr(10).join(env_lines(env, ins)).strip()
    if env_msg:
        parts.append(env_msg)
    parts.append(chr(10).join(B).strip())
    return parts


# ---------- Telegram (opsional: teks + foto asli) ----------
def tg_env():
    return (os.environ.get("TG_TOKEN", "").strip(),
            os.environ.get("TG_CHAT_ID", "").strip())


def tg_send_text(text):
    token, chat = tg_env()
    if not (token and chat):
        return False
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "Markdown"}).encode()
    try:
        with urllib.request.urlopen(url, data=body, timeout=45) as r:
            print("TG text:", r.status)
        return True
    except Exception as e:
        print("TG text gagal:", e)
        return False


def tg_send_photo(link, caption):
    token, chat = tg_env()
    if not (token and chat and link):
        return False
    url = "https://api.telegram.org/bot" + token + "/sendPhoto"
    body = urllib.parse.urlencode({"chat_id": chat, "photo": link, "caption": caption}).encode()
    try:
        with urllib.request.urlopen(url, data=body, timeout=45) as r:
            print("TG photo:", r.status)
        return True
    except Exception as e:
        print("TG photo gagal:", e)
        return False


# Jeda minimum antar-kirim (jam): cegah dobel bila run terpicu berdekatan,
# tapi tetap izinkan 3x kirim/hari karena jadwalnya berjauhan.
MIN_GAP_HOURS = 4


def recently_sent(now):
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False
    ts = data.get("ts")
    if not ts:
        return False
    try:
        last = datetime.fromisoformat(ts)
    except Exception:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=now.tzinfo)
    return (now - last) < timedelta(hours=MIN_GAP_HOURS)


def mark_sent(now):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"date": now.date().isoformat(), "ts": now.isoformat()}, f)
        print("Status kirim disimpan:", now.isoformat())
    except Exception as e:
        print("Gagal simpan status:", e)


def main():
    cfg = load_json("config.json")
    jadwal = load_json("jadwal.json")
    cuaca = load_json(os.path.join("data", "cuaca.json"))
    offset = timezone(timedelta(hours=cfg.get("utc_offset_hours", 8)))
    now = datetime.now(offset)
    today = now.date()

    force = os.environ.get("FORCE_SEND", "").strip().lower() == "true"
    if recently_sent(now) and not force:
        print("Baru saja kirim (< " + str(MIN_GAP_HOURS) + " jam lalu) - lewati.")
        return

    harv = harvin_latest(cfg)
    try:
        env = load_json(os.path.join("data", "lingkungan.json"))
    except Exception:
        env = None
    msg1 = build_headline(cfg, jadwal, cuaca, today, harv)
    parts = build_detail(cfg, jadwal, cuaca, today, harv, env)
    cu = chart_url(cfg)

    print("===== PESAN 1 (HEADLINE) =====\n" + msg1)
    for i, p in enumerate(parts, 1):
        print("\n===== DETAIL " + str(i) + " =====\n" + p)
    if harv:
        print("\nCitra terbaru:", harv["date"], "|", harv["truecolor"], "|", harv["ndvi"])
    print("=" * 30)

    tg_configured = bool(os.environ.get("TG_TOKEN", "").strip() and os.environ.get("TG_CHAT_ID", "").strip())

    # ---- Telegram (opsional): foto asli ----
    tg_ok = False
    if tg_configured and tg_send_text(msg1):
        tg_ok = True
        if cu:
            tg_send_photo(cu, "Curah hujan & jadwal")
        if harv:
            tg_send_photo(harv["truecolor"], "Warna asli - " + sat_label(harv))
            tg_send_photo(harv["ndvi"], "NDVI - " + sat_label(harv))
        for p2 in parts:
            tg_send_text(p2)

    # Tandai terkirim hanya bila Telegram benar-benar berhasil, supaya run
    # berikutnya mencoba lagi bila gagal. Tanpa secret TG: murni pratinjau
    # log (dashboard GitHub Pages adalah kanal utama).
    if tg_ok:
        mark_sent(now)
    else:
        print("(Tidak ada secret Telegram - mode pratinjau; pesan hanya dicetak di log.)")


if __name__ == "__main__":
    main()
