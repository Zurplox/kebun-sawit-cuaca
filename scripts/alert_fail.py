#!/usr/bin/env python3
"""Kirim peringatan Telegram bila workflow GAGAL (dipanggil dengan if: failure()).

CallMeBot/WhatsApp sudah dihapus. Tanpa secret Telegram skrip ini no-op —
cukup cek tab Actions di GitHub untuk melihat log kegagalan.
"""
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


def main():
    token = os.environ.get("TG_TOKEN", "").strip()
    chat = os.environ.get("TG_CHAT_ID", "").strip()
    if not (token and chat):
        print("Tidak ada secret Telegram - lewati peringatan (cek tab Actions).")
        return
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%d-%m-%Y %H:%M")
    text = ("\u26a0\ufe0f *Cuaca Kebun GAGAL*\n"
            "Workflow harian error pada " + now + " WIB.\n"
            "Cek tab Actions di GitHub untuk lihat log.")
    body = urllib.parse.urlencode(
        {"chat_id": chat, "text": text, "parse_mode": "Markdown"}).encode()
    try:
        with urllib.request.urlopen("https://api.telegram.org/bot" + token + "/sendMessage",
                                    data=body, timeout=45) as r:
            print("Alert Telegram terkirim:", r.status)
    except Exception as e:
        print("Alert gagal:", e)


if __name__ == "__main__":
    main()
