#!/usr/bin/env python3
"""Buat chart.png (curah hujan harian + jadwal + hari pupuk terbaik).
Dipakai untuk dikirim sebagai foto (Telegram) & pratinjau tautan (WhatsApp).
Butuh matplotlib (di-install oleh workflow).
"""
import json
import os
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from analysis import compute_insights

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVCOLOR = {"pupuk": "#46A171", "pruning": "#7A5AD9", "tebas": "#D5803B"}


def load(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as f:
        return json.load(f)


def main():
    cfg = load("config.json")
    jadwal = load("jadwal.json")
    cuaca = load(os.path.join("data", "cuaca.json"))
    days = cuaca.get("days", [])
    if not days:
        print("Tidak ada data, chart dilewati.")
        return

    offset = timezone(timedelta(hours=cfg.get("utc_offset_hours", 8)))
    today = datetime.now(offset).date()
    ins = compute_insights(days, cfg, today)

    dates = [datetime.strptime(d["date"], "%Y-%m-%d").date() for d in days]
    precip = [d.get("precip") or 0 for d in days]
    colors = ["#2783DE" if d.get("kind") == "actual" else "#AFD3F2" for d in days]
    idx = {d: i for i, d in enumerate(dates)}

    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=110)
    ax.bar(range(len(days)), precip, color=colors, width=0.8, zorder=3)

    # garis jadwal
    for e in jadwal.get("events", []):
        ed = datetime.strptime(e["date"], "%Y-%m-%d").date()
        if ed in idx:
            ax.axvline(idx[ed], color=EVCOLOR.get(e["type"], "#999"),
                       ls="--", lw=1.6, zorder=2)

    # garis hari ini
    if today in idx:
        ax.axvline(idx[today], color="#7D7A75", ls=":", lw=1.4, zorder=2)

    # bintang hari pupuk terbaik
    if ins["best"] and ins["best"]["date"] in idx:
        bi = idx[ins["best"]["date"]]
        ymax = max(precip) if precip else 10
        ax.scatter([bi], [ymax * 1.06], marker="*", s=260,
                   color="#C99A2E", zorder=5, clip_on=False)

    # sumbu x: label tiap ~7 hari
    step = max(1, len(days) // 8)
    ticks = list(range(0, len(days), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{dates[i].day} {['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des'][dates[i].month-1]}" for i in ticks], fontsize=9)
    ax.set_ylabel("Hujan (mm)", fontsize=10)
    farm = cuaca.get("farm_name", cfg.get("farm_name", "Kebun"))
    ax.set_title(f"Curah hujan harian — {farm}", fontsize=13, fontweight="bold", loc="left")
    ax.grid(axis="y", color="#E6E5E3", zorder=0)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)

    legend = [
        Patch(color="#2783DE", label="Aktual"),
        Patch(color="#AFD3F2", label="Prakiraan"),
        Patch(color=EVCOLOR["pupuk"], label="Pupuk"),
        Patch(color=EVCOLOR["pruning"], label="Pruning"),
        Patch(color=EVCOLOR["tebas"], label="Tebas"),
    ]
    ax.legend(handles=legend, loc="upper left", fontsize=8, ncol=5, frameon=False)

    fig.tight_layout()
    out = os.path.join(ROOT, "chart.png")
    fig.savefig(out, bbox_inches="tight")
    print("OK chart.png")


if __name__ == "__main__":
    main()
