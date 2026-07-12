#!/usr/bin/env python3
"""Ambil data LINGKUNGAN sekitar kebun -> data/lingkungan.json.

Semua sumber GRATIS:
  1. Karhutla (titik api) - NASA FIRMS Area API (perlu FIRMS_MAP_KEY gratis).
     -> status peringatan + titik api TERDEKAT (jarak km + arah + wilayah).
  2. Kualitas udara - Open-Meteo Air Quality API (tanpa key).
  3. Banjir / tinggi air - Open-Meteo Flood API (debit sungai, tanpa key).
  4. Air pasang (pasang surut) - Open-Meteo Marine API (tanpa key) di titik
     pesisir TERDEKAT (kebun di darat, jadi pasang diambil dari laut terdekat:
     Selat Malaka di timur laut).

Titik acuan = koordinat kebun Harvin (Rawang Air Putih, Siak, Riau):
  farm_lat / farm_lon di config.json.

Hanya modul standar Python. Dijalankan oleh GitHub Actions.
"""
import csv
import io
import json
import math
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
OUT_PATH = os.path.join(ROOT, "data", "lingkungan.json")
CUACA_PATH = os.path.join(ROOT, "data", "cuaca.json")

# Titik laut kandidat di Selat Malaka (timur laut kebun) untuk data pasang surut.
# Kebun di darat -> Marine API tak punya data di titik kebun; pakai titik laut
# terdekat yang mengembalikan data. Diurut otomatis berdasar jarak dari kebun.
TIDE_CANDIDATES = [
    (1.30, 102.35, "Selat Malaka (dekat Sungai Apit)"),
    (1.50, 102.30, "Selat Malaka (lepas pantai Siak)"),
    (1.70, 102.50, "Selat Malaka"),
    (1.95, 102.30, "Selat Malaka (dekat Bengkalis)"),
    (2.20, 102.60, "Selat Malaka"),
]

COMPASS8 = ["utara", "timur laut", "timur", "tenggara",
            "selatan", "barat daya", "barat", "barat laut"]


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _get(url, headers=None, timeout=60, as_json=True):
    last = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(
                url, headers=headers or {"User-Agent": "kebun-lingkungan/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
            return json.loads(raw) if as_json else raw
        except Exception as e:
            last = e
            print("Percobaan " + str(attempt) + "/3 gagal:", e)
            if attempt < 3:
                time.sleep(4 * attempt)
    if last:
        print("Menyerah:", last)
    return None


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_compass(lat1, lon1, lat2, lon2, pts=COMPASS8):
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(math.radians(lat2))
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
         - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dl))
    brng = (math.degrees(math.atan2(y, x)) + 360) % 360
    idx = int((brng / (360 / len(pts))) + 0.5) % len(pts)
    return pts[idx]


def reverse_geocode(lat, lon):
    url = ("https://api.bigdatacloud.net/data/reverse-geocode-client?latitude="
           + str(lat) + "&longitude=" + str(lon) + "&localityLanguage=id")
    d = _get(url)
    if not isinstance(d, dict):
        return None
    parts = []
    for k in ("locality", "city", "principalSubdivision"):
        v = d.get(k)
        if v and v not in parts:
            parts.append(v)
    return ", ".join(parts) if parts else None


# ---------- 1) KARHUTLA (NASA FIRMS) ----------
def fetch_fire(cfg):
    lat = cfg["farm_lat"]
    lon = cfg["farm_lon"]
    warn_km = cfg.get("karhutla_warn_km", 50)
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key:
        return {"status": "tidak tersedia", "note": "FIRMS_MAP_KEY belum diatur",
                "warn_km": warn_km, "nearest": None, "count_within": 0}
    deg = cfg.get("karhutla_scan_deg", 2.5)
    days = cfg.get("fire_day_range", 2)
    box = "%.4f,%.4f,%.4f,%.4f" % (lon - deg, lat - deg, lon + deg, lat + deg)
    sources = cfg.get("firms_sources") or ["VIIRS_NOAA20_NRT", "VIIRS_SNPP_NRT"]
    rows = []
    for src in sources:
        url = ("https://firms.modaps.eosdis.nasa.gov/api/area/csv/" + key + "/"
               + src + "/" + box + "/" + str(days))
        txt = _get(url, as_json=False)
        if not txt or "," not in txt:
            continue
        try:
            for row in csv.DictReader(io.StringIO(txt)):
                rows.append(row)
        except Exception as e:
            print("FIRMS parse gagal:", e)
    pts = []
    for r in rows:
        try:
            la = float(r.get("latitude"))
            lo = float(r.get("longitude"))
        except Exception:
            continue
        pts.append((haversine_km(lat, lon, la, lo), la, lo, r))
    if not pts:
        return {"status": "aman", "warn_km": warn_km, "nearest": None,
                "count_within": 0, "scanned_days": days}
    pts.sort(key=lambda x: x[0])
    within = [p for p in pts if p[0] <= warn_km]
    km, la, lo, r = pts[0]
    acq_fmt = r.get("acq_date", "")  # tanggal saja, tanpa jam
    nearest = {
        "km": round(km, 1),
        "dir": bearing_compass(lat, lon, la, lo),
        "lat": round(la, 4), "lon": round(lo, 4),
        "place": reverse_geocode(la, lo),
        "acq": acq_fmt.strip(),
        "sat": r.get("satellite") or r.get("instrument"),
        "confidence": r.get("confidence"),
        "frp": r.get("frp"),
    }
    if km <= warn_km:
        status = "bahaya" if (km <= warn_km / 2 or len(within) >= 5) else "waspada"
    else:
        status = "aman"
    return {"status": status, "warn_km": warn_km, "nearest": nearest,
            "count_within": len(within), "scanned_days": days}


def fire_weather_risk(cfg):
    """Risiko cuaca kebakaran dari cuaca.json: hari kering beruntun + kelembapan."""
    try:
        with open(CUACA_PATH, encoding="utf-8") as f:
            c = json.load(f)
    except Exception:
        return None
    td = c.get("today") or {}
    hum = td.get("humidity")
    by = {d["date"]: d for d in c.get("days", [])}
    off = timezone(timedelta(hours=cfg.get("utc_offset_hours", 8)))
    today = datetime.now(off).date()
    dry = cfg.get("dry_threshold_mm", 2)
    streak = 0
    for i in range(0, 14):
        r = by.get((today + timedelta(days=i)).isoformat())
        if r and r.get("precip") is not None and r["precip"] < dry:
            streak += 1
        else:
            break
    level = "rendah"
    if streak >= 7 or (hum is not None and hum < 55):
        level = "tinggi"
    elif streak >= 3:
        level = "sedang"
    return {"level": level, "dry_streak": streak, "humidity": hum}


# ---------- 2) KUALITAS UDARA (Open-Meteo Air Quality) ----------
def aqi_category(aqi):
    if aqi is None:
        return ("tidak tersedia", "muted")
    if aqi <= 50:
        return ("Baik", "green")
    if aqi <= 100:
        return ("Sedang", "gold")
    if aqi <= 150:
        return ("Tidak sehat (kel. sensitif)", "orange")
    if aqi <= 200:
        return ("Tidak sehat", "red")
    if aqi <= 300:
        return ("Sangat tidak sehat", "red")
    return ("Berbahaya", "red")


def haze_category(aod):
    if aod is None:
        return ("tidak tersedia", "muted")
    if aod < 0.3:
        return ("cerah", "green")
    if aod < 0.6:
        return ("berkabut tipis", "gold")
    if aod < 1.0:
        return ("berasap/berkabut", "orange")
    return ("asap tebal", "red")


def uv_category(uv):
    if uv is None:
        return "tidak tersedia"
    if uv < 3:
        return "rendah"
    if uv < 6:
        return "sedang"
    if uv < 8:
        return "tinggi"
    if uv < 11:
        return "sangat tinggi"
    return "ekstrem"


def fetch_air(cfg):
    url = ("https://air-quality-api.open-meteo.com/v1/air-quality?latitude="
           + str(cfg["farm_lat"]) + "&longitude=" + str(cfg["farm_lon"])
           + "&current=pm2_5,pm10,us_aqi,aerosol_optical_depth,dust,uv_index&timezone=auto")
    d = _get(url)
    if not isinstance(d, dict):
        return None
    cur = d.get("current", {})
    aqi = cur.get("us_aqi")
    cat, color = aqi_category(aqi)
    aod = cur.get("aerosol_optical_depth")
    dust = cur.get("dust")
    uv = cur.get("uv_index")
    hcat, hcolor = haze_category(aod)
    return {"us_aqi": aqi, "pm2_5": cur.get("pm2_5"), "pm10": cur.get("pm10"),
            "category": cat, "color": color,
            "aod": round(aod, 2) if aod is not None else None,
            "dust": round(dust) if dust is not None else None,
            "haze": hcat, "haze_color": hcolor,
            "uv": round(uv, 1) if uv is not None else None,
            "uv_cat": uv_category(uv)}


# ---------- 3) BANJIR / DEBIT SUNGAI (Open-Meteo Flood) ----------
def fetch_flood(cfg):
    url = ("https://flood-api.open-meteo.com/v1/flood?latitude="
           + str(cfg["farm_lat"]) + "&longitude=" + str(cfg["farm_lon"])
           + "&daily=river_discharge&past_days=7&forecast_days=3")
    d = _get(url)
    if not isinstance(d, dict):
        return None
    daily = d.get("daily", {})
    dates = daily.get("time", [])
    disch = daily.get("river_discharge", [])
    if not dates:
        return None
    off = timezone(timedelta(hours=cfg.get("utc_offset_hours", 8)))
    today = datetime.now(off).date().isoformat()
    idx = dates.index(today) if today in dates else len(dates) - 1
    val = disch[idx] if idx < len(disch) else None
    prev = [disch[i] for i in range(max(0, idx - 3), idx)
            if i < len(disch) and disch[i] is not None]
    trend = "stabil"
    if val is not None and prev:
        pm = sum(prev) / len(prev)
        if val > pm * 1.1:
            trend = "naik"
        elif val < pm * 0.9:
            trend = "turun"
    fut = [disch[i] for i in range(idx + 1, min(len(disch), idx + 4))
           if disch[i] is not None]
    prev7 = [disch[i] for i in range(max(0, idx - 7), idx)
             if i < len(disch) and disch[i] is not None]
    base = None
    if prev7:
        sp = sorted(prev7)
        base = sp[len(sp) // 2]  # median 7 hari
    ratio = (val / base) if (val is not None and base) else None
    if ratio is None:
        status = "tidak tersedia"
    elif ratio < 1.15:
        status = "Normal"
    elif ratio < 1.5:
        status = "Agak tinggi"
    elif ratio < 2.0:
        status = "Tinggi"
    else:
        status = "Sangat tinggi"
    return {"river_discharge": round(val, 1) if val is not None else None,
            "unit": "m3/s", "trend": trend,
            "peak_next3": round(max(fut), 1) if fut else None,
            "baseline": round(base, 1) if base is not None else None,
            "ratio_pct": round(ratio * 100) if ratio is not None else None,
            "status": status}


def tide_extremes(pairs):
    """Semua titik balik pasang/surut dari deret ketinggian per jam."""
    ext = []
    prev_sign = 0
    for i in range(1, len(pairs)):
        d = pairs[i][1] - pairs[i - 1][1]
        s = 1 if d > 0.005 else (-1 if d < -0.005 else 0)
        if s == 0:
            continue
        if prev_sign != 0 and s != prev_sign:
            typ = "pasang" if prev_sign > 0 else "surut"
            ext.append({"type": typ,
                        "h": round(pairs[i - 1][1], 2),
                        "time": pairs[i - 1][0][11:16]})
        prev_sign = s
    return ext


# ---------- 4) AIR PASANG (Open-Meteo Marine) ----------
# ---------- Prediksi pasang jangka panjang (analisis harmonik) ----------
# Pasang bersifat astronomis & periodik, jadi bisa diprediksi jauh ke depan
# dengan mencocokkan konstituen pasang utama (M2, S2, K1, O1, dll) ke data
# historis + prakiraan, lalu memproyeksikannya ke depan. Hanya komponen
# astronomis; efek cuaca/surge tak diprediksi di luar jangkauan model (~16 hr).
TIDE_CONSTITUENTS = [
    ("M2", 28.9841042), ("S2", 30.0), ("N2", 28.4397295), ("K2", 30.0821373),
    ("K1", 15.0410686), ("O1", 13.9430356), ("P1", 14.9589314), ("Q1", 13.3986609),
    ("Mf", 1.0980331), ("Mm", 0.5443747),
]


def _solve_linear(A, b):
    n = len(A)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            return None
        M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        for j in range(col, n + 1):
            M[col][j] /= pv
        for r in range(n):
            if r != col and M[r][col]:
                f = M[r][col]
                for j in range(col, n + 1):
                    M[r][j] -= f * M[col][j]
    return [M[i][n] for i in range(n)]


def _tide_design(t):
    row = [1.0]
    for (_, sp) in TIDE_CONSTITUENTS:
        ph = math.radians(sp * t)
        row.append(math.cos(ph))
        row.append(math.sin(ph))
    return row


def tide_harmonic_fit(times_h, heights):
    ncol = 1 + 2 * len(TIDE_CONSTITUENTS)
    ATA = [[0.0] * ncol for _ in range(ncol)]
    ATb = [0.0] * ncol
    for t, y in zip(times_h, heights):
        row = _tide_design(t)
        for i in range(ncol):
            ATb[i] += row[i] * y
            ri = row[i]
            for j in range(i, ncol):
                ATA[i][j] += ri * row[j]
    for i in range(ncol):
        for j in range(i):
            ATA[i][j] = ATA[j][i]
    return _solve_linear(ATA, ATb)


def tide_harmonic_value(coef, t):
    row = _tide_design(t)
    return sum(coef[i] * row[i] for i in range(len(coef)))


def fetch_tide(cfg):
    lat = cfg["farm_lat"]
    lon = cfg["farm_lon"]
    off = timezone(timedelta(hours=cfg.get("utc_offset_hours", 8)))
    today = datetime.now(off).date().isoformat()
    fdays = int(cfg.get("tide_forecast_days", 16) or 16)
    fdays = max(1, min(16, fdays))
    pdays = int(cfg.get("tide_past_days", 60) or 0)
    pdays = max(0, min(92, pdays))
    predict_days = int(cfg.get("tide_predict_days", 30) or 30)
    predict_days = max(fdays, min(60, predict_days))
    cands = []
    if cfg.get("tide_lat") is not None and cfg.get("tide_lon") is not None:
        cands.append((cfg["tide_lat"], cfg["tide_lon"],
                      cfg.get("tide_name") or "Pesisir terdekat"))
    cands += TIDE_CANDIDATES
    cands.sort(key=lambda c: haversine_km(lat, lon, c[0], c[1]))
    for (tlat, tlon, name) in cands:
        url = ("https://marine-api.open-meteo.com/v1/marine?latitude="
               + str(tlat) + "&longitude=" + str(tlon)
               + "&hourly=sea_level_height_msl&timezone=auto&forecast_days=" + str(fdays)
               + "&past_days=" + str(pdays))
        d = _get(url)
        if not isinstance(d, dict):
            continue
        h = d.get("hourly", {})
        times = h.get("time", [])
        lv = h.get("sea_level_height_msl", [])
        all_pairs = [(times[i], lv[i]) for i in range(min(len(times), len(lv)))
                     if lv[i] is not None]
        if not all_pairs:
            continue
        all_pairs.sort(key=lambda p: p[0])
        pairs = [p for p in all_pairs if p[0][:10] == today] or all_pairs
        hi = max(pairs, key=lambda p: p[1])
        lo = min(pairs, key=lambda p: p[1])
        t0 = datetime.strptime(all_pairs[0][0][:16], "%Y-%m-%dT%H:%M")

        def _th(ts):
            return (datetime.strptime(ts[:16], "%Y-%m-%dT%H:%M") - t0).total_seconds() / 3600.0

        by_day = {}
        for (tt, vv) in all_pairs:
            by_day.setdefault(tt[:10], []).append((tt, vv))
        daily = []
        for day in sorted(by_day.keys()):
            if day < today:
                continue
            dps = by_day[day]
            dh = max(dps, key=lambda p: p[1])
            dl = min(dps, key=lambda p: p[1])
            daily.append({"date": day,
                          "high": round(dh[1], 2), "high_time": dh[0][11:16],
                          "low": round(dl[1], 2), "low_time": dl[0][11:16]})
        # Perpanjang ke predict_days via prediksi harmonik (astronomis).
        have = set(x["date"] for x in daily)
        coef = None
        try:
            coef = tide_harmonic_fit([_th(p[0]) for p in all_pairs],
                                     [p[1] for p in all_pairs])
        except Exception as _e:
            coef = None
        if coef:
            base = datetime.strptime(today, "%Y-%m-%d")
            for k in range(predict_days):
                day = (base + timedelta(days=k)).strftime("%Y-%m-%d")
                if day in have:
                    continue
                best_h = best_t = low_h = low_t = None
                for m in range(48):
                    ts = day + "T%02d:%02d" % (m // 2, 30 * (m % 2))
                    val = tide_harmonic_value(coef, _th(ts))
                    if best_h is None or val > best_h:
                        best_h, best_t = val, ts[11:16]
                    if low_h is None or val < low_h:
                        low_h, low_t = val, ts[11:16]
                daily.append({"date": day,
                              "high": round(best_h, 2), "high_time": best_t,
                              "low": round(low_h, 2), "low_time": low_t,
                              "est": True})
            daily.sort(key=lambda x: x["date"])
        return {"point_name": name, "lat": tlat, "lon": tlon,
                "km": round(haversine_km(lat, lon, tlat, tlon)),
                "dir": bearing_compass(lat, lon, tlat, tlon),
                "high": {"h": round(hi[1], 2), "time": hi[0][11:16]},
                "low": {"h": round(lo[1], 2), "time": lo[0][11:16]},
                "extremes": tide_extremes(pairs),
                "daily": daily}
    return None


def main():
    cfg = load_config()
    off = timezone(timedelta(hours=cfg.get("utc_offset_hours", 8)))
    fire = fetch_fire(cfg)
    try:
        fire["weather_risk"] = fire_weather_risk(cfg)
    except Exception as e:
        print("Risiko cuaca kebakaran gagal:", e)
    out = {
        "updated_at": datetime.now(off).isoformat(timespec="minutes"),
        "farm": {"lat": cfg["farm_lat"], "lon": cfg["farm_lon"],
                 "name": cfg.get("farm_name", "Kebun")},
        "fire": fire,
        "air": fetch_air(cfg),
        "flood": fetch_flood(cfg),
        "tide": fetch_tide(cfg),
    }
    fl, fo = cfg["farm_lat"], cfg["farm_lon"]
    if out.get("fire"):
        out["fire"]["map"] = ("https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;@"
                              + "{:.3f},{:.3f},9z".format(fo, fl))
        _nr = out["fire"].get("nearest") or {}
        if _nr.get("lat") is not None:
            out["fire"]["map_google"] = "https://www.google.com/maps?q=" + str(_nr["lat"]) + "," + str(_nr["lon"])
    if out.get("flood"):
        out["flood"]["map"] = "https://sites.research.google/floods/l/" + format(fl, ".3f") + "/" + format(fo, ".3f") + "/9"
    if out.get("tide") and out["tide"].get("lat") is not None:
        out["tide"]["map"] = "https://www.google.com/maps?q=" + str(out["tide"]["lat"]) + "," + str(out["tide"]["lon"])
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("OK: data/lingkungan.json tersimpan.")
    print(json.dumps(out, ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
