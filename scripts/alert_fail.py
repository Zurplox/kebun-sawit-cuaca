#!/usr/bin/env python3
"""Kirim peringatan WhatsApp bila workflow GAGAL (dipanggil dengan if: failure())."""
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


def main():
    phone = os.environ.get("WA_PHONE", "").strip()
    apikey = os.environ.get("WA_APIKEY", "").strip()
    if not (phone and apikey):
        print("Tidak ada secret WA - lewati peringatan.")
        return
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%d-%m-%Y %H:%M")
    text = ("\u26a0\ufe0f *Cuaca Kebun GAGAL*\n"
            "Workflow harian error pada " + now + " WIB.\n"
            "Cek tab Actions di GitHub untuk lihat log.")
    q = urllib.parse.urlencode({"phone": phone, "text": text, "apikey": apikey})
    try:
        with urllib.request.urlopen("https://api.callmebot.com/whatsapp.php?" + q, timeout=45) as r:
            print("Alert terkirim:", r.status)
    except Exception as e:
        print("Alert gagal:", e)


if __name__ == "__main__":
    main()
