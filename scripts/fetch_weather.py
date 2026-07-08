#!/usr/bin/env python3
"""Ambil data cuaca/hujan dari Open-Meteo (gratis, tanpa API key) untuk titik
koordinat kebun, lalu simpan ke data/cuaca.json. Dijalankan tiap hari oleh
GitHub Actions.

Sumber: Open-Meteo (timezone=auto -> memakai zona waktu lokal titik koordinat,
model best_match memilih model paling akurat: ECMWF/DWD/NOAA/JMA dll).

Peningkatan:
- Retry 3x kalau API sedang gangguan.
- Simpan riwayat maksimal 1 tahun (MAX_HISTORY_DAYS).
- Rincian HARI INI: kelembapan, tutupan awan, kondisi (cerah/berawan/hujan),
  angin + hembusan + arah, perkiraan JAM hujan + durasi, matahari terbit/terbenam,
  serta data per jam untuk grafik dashboard.

Hanya modul standar Python.
"""
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from analysis import compass, weather_desc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
DATA_PATH = os.path.join(ROOT, "data", "cuaca.json")
MAX_HISTORY_DAYS = 365  # simpan riwayat maksimal 1 tahun
API = "https://api.open-meteo.com/v1/forecast?"


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _get(url):
    last_err = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kebun-cuaca/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except Exception as e:
            last_err = e
            print("Percobaan " + str(attempt) + "/3 gagal:", e)
            if attempt < 3:
                time.sleep(5 * attempt)
    raise last_err


def fetch_daily(cfg):
    params = {
        "latitude": cfg["lat"],
        "longitude": cfg["lon"],
        "timezone": "auto",
        "past_days": cfg.get("past_days", 40),
        "forecast_days": cfg.get("forecast_days", 16),
        "daily": ",".join([
            "precipitation_sum",
            "precipitation_probability_max",
            "temperature_2m_max",
            "temperature_2m_min",
            "windspeed_10m_max",
            "weathercode",
            "precipitation_hours",
            "windgusts_10m_max",
            "winddirection_10m_dominant",
            "sunrise",
            "sunset",
        ]),
    }
    return _get(API + urllib.parse.urlencode(params))


def fetch_hourly(cfg):
    params = {
        "latitude": cfg["lat"],
        "longitude": cfg["lon"],
        "timezone": "auto",
        "past_days": 1,
        "forecast_days": 2,
        "hourly": ",".join([
            "precipitation",
            "precipitation_probability",
            "relativehumidity_2m",
            "cloudcover",
            "weathercode",
            "windspeed_10m",
            "winddirection_10m",
            "windgusts_10m",
        ]),
    }
    return _get(API + urllib.parse.urlencode(params))


def _mean(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v)) if v else None


def _hm(s):
    return s[11:16] if s and len(s) >= 16 else s


def build_today(today, hourly, daily_by_date):
    times = hourly.get("time", [])
    tstr = today.isoformat()
    idxs = [i for i, t in enumerate(times) if t[:10] == tstr]

    def col(name):
        arr = hourly.get(name, [])
        return [(arr[i] if i < len(arr) else None) for i in idxs]

    precip = col("precipitation")
    prob = col("precipitation_probability")
    rh = col("relativehumidity_2m")
    cloud = col("cloudcover")
    code_h = col("weathercode")
    hours = [int(times[i][11:13]) for i in idxs]

    windows = []
    run = None
    for j in range(len(precip)):
        p = precip[j]
        wet = p is not None and p >= 0.2
        if wet and run is None:
            run = j
        if (not wet) and run is not None:
            windows.append((hours[run], hours[j - 1]))
            run = None
    if run is not None:
        windows.append((hours[run], hours[len(precip) - 1]))

    def wlabel(a, b):
        return ("%02d:00" % a) + "\u2013" + ("%02d:00" % (b + 1))

    rain_windows = [wlabel(a, b) for (a, b) in windows]

    d = daily_by_date.get(tstr, {})
    code = d.get("weathercode")
    desc, emoji = weather_desc(code)

    hourly_out = []
    for k, i in enumerate(idxs):
        hourly_out.append({
            "t": times[i][11:16],
            "p": precip[k],
            "prob": prob[k],
            "rh": rh[k],
            "cloud": cloud[k],
            "code": code_h[k],
        })

    return {
        "date": tstr,
        "precip": d.get("precipitation_sum"),
        "prob": d.get("precipitation_probability_max"),
        "tmax": d.get("temperature_2m_max"),
        "tmin": d.get("temperature_2m_min"),
        "humidity": _mean(rh),
        "cloud": _mean(cloud),
        "code": code,
        "condition": desc,
        "emoji": emoji,
        "wind": d.get("windspeed_10m_max"),
        "gust": d.get("windgusts_10m_max"),
        "wind_dir": compass(d.get("winddirection_10m_dominant")),
        "wind_dir_deg": d.get("winddirection_10m_dominant"),
        "precip_hours": d.get("precipitation_hours"),
        "rain_windows": rain_windows,
        "sunrise": _hm(d.get("sunrise")),
        "sunset": _hm(d.get("sunset")),
        "hourly": hourly_out,
    }


def main():
    cfg = load_config()
    offset = timezone(timedelta(hours=cfg.get("utc_offset_hours", 8)))
    today = datetime.now(offset).date()

    raw = fetch_daily(cfg)
    daily = raw.get("daily", {})
    dates = daily.get("time", [])

    def col(name):
        return daily.get(name, [None] * len(dates))

    precip = col("precipitation_sum")
    prob = col("precipitation_probability_max")
    tmax = col("temperature_2m_max")
    tmin = col("temperature_2m_min")
    wind = col("windspeed_10m_max")
    code = col("weathercode")
    phours = col("precipitation_hours")
    gust = col("windgusts_10m_max")
    wdir = col("winddirection_10m_dominant")
    sunrise = col("sunrise")
    sunset = col("sunset")

    daily_by_date = {}
    for i, dd in enumerate(dates):
        daily_by_date[dd] = {
            "precipitation_sum": round(precip[i], 1) if precip[i] is not None else None,
            "precipitation_probability_max": prob[i],
            "temperature_2m_max": tmax[i],
            "temperature_2m_min": tmin[i],
            "windspeed_10m_max": wind[i],
            "weathercode": code[i],
            "precipitation_hours": phours[i],
            "windgusts_10m_max": gust[i],
            "winddirection_10m_dominant": wdir[i],
            "sunrise": sunrise[i],
            "sunset": sunset[i],
        }

    existing = {}
    if os.path.exists(DATA_PATH):
        try:
            with open(DATA_PATH, encoding="utf-8") as f:
                for drow in json.load(f).get("days", []):
                    existing[drow["date"]] = drow
        except Exception:
            existing = {}

    for i, dcur in enumerate(dates):
        day = datetime.strptime(dcur, "%Y-%m-%d").date()
        kind = "actual" if day < today else "forecast"
        existing[dcur] = {
            "date": dcur,
            "precip": round(precip[i], 1) if precip[i] is not None else None,
            "prob": prob[i],
            "tmax": tmax[i],
            "tmin": tmin[i],
            "wind": wind[i],
            "code": code[i],
            "gust": gust[i],
            "wdir": wdir[i],
            "phours": phours[i],
            "kind": kind,
        }

    cutoff = (today - timedelta(days=MAX_HISTORY_DAYS)).isoformat()
    keys = [k for k in sorted(existing.keys()) if k >= cutoff]
    days = [existing[k] for k in keys]

    today_detail = None
    try:
        hourly = fetch_hourly(cfg)
        today_detail = build_today(today, hourly.get("hourly", {}), daily_by_date)
    except Exception as e:
        print("Rincian per jam gagal (dilewati):", e)

    out = {
        "updated_at": datetime.now(offset).isoformat(timespec="minutes"),
        "location": {"lat": cfg["lat"], "lon": cfg["lon"]},
        "farm_name": cfg.get("farm_name", "Kebun"),
        "today": today_detail,
        "days": days,
    }

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("OK: " + str(len(days)) + " hari tersimpan (hingga " + days[-1]["date"] + ").")


if __name__ == "__main__":
    main()
