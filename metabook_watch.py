#!/usr/bin/env python3
"""
Παρακολούθηση metabook.gr: νέοι τίτλοι + επανεμφάνιση διαθεσιμότητας.
Ειδοποίηση με email και Telegram. Τρέχει μία φορά ανά εκτέλεση (βάλ' το σε cron / Task Scheduler).

Εγκατάσταση:
    pip install playwright
    playwright install chromium

Δοκιμή (δείχνει τι διαβάζει, δεν στέλνει τίποτα):
    python metabook_watch.py --debug
"""
import json, os, re, smtplib, ssl, sys, urllib.parse, urllib.request
from email.message import EmailMessage
from pathlib import Path

from playwright.sync_api import sync_playwright

SEARCH_URL = "https://metabook.gr/search/?query=Jill%20barklem"
STATE_FILE = Path(__file__).with_name("state.json")

# Λέξεις που σημαίνουν "όχι διαθέσιμο" (πρόσθεσε ό,τι δεις στο σάιτ)
OUT_OF_STOCK = ["εξαντλ", "μη διαθέσιμ", "μη διαθεσιμ", "out of stock", "ανεπαρκ"]

# --- Ρυθμίσεις από μεταβλητές περιβάλλοντος ---
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")        # π.χ. το gmail σου
SMTP_PASS = os.getenv("SMTP_PASS", "")        # Gmail: "κωδικός εφαρμογής"
EMAIL_TO = os.getenv("EMAIL_TO", SMTP_USER)
TG_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

# Βρίσκει κάρτες αποτελεσμάτων: ανεβαίνει από κάθε link μέχρι να βρει γονέα με τιμή (€)
JS_EXTRACT = """
() => {
  const out = new Map();
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href;
    if (!href.startsWith(location.origin) || href.includes('/search')) continue;
    const title = (a.innerText || a.title || '').trim();
    if (title.length < 6) continue;
    let card = a;
    for (let i = 0; i < 5 && card.parentElement; i++) {
      card = card.parentElement;
      if (/€/.test(card.innerText || '')) break;
    }
    if (!/€/.test(card.innerText || '')) continue;
    if (!out.has(href)) out.set(href, {url: href, title, text: card.innerText});
  }
  return [...out.values()];
}
"""


def fetch_items(debug=False):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=os.getenv("HEADED") != "1")
        ctx = browser.new_context(locale="el-GR", viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        page.goto(SEARCH_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2500)
        items = page.evaluate(JS_EXTRACT)
        if debug:
            Path("debug.html").write_text(page.content(), encoding="utf-8")
        browser.close()
    result = {}
    for it in items:
        txt = it["text"].lower()
        available = not any(k in txt for k in OUT_OF_STOCK)
        result[it["url"]] = {"title": it["title"], "available": available}
    return result


def notify(subject, body):
    if SMTP_USER and SMTP_PASS:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, SMTP_USER, EMAIL_TO
        msg.set_content(body)
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context()) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    if TG_TOKEN and TG_CHAT:
        data = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": f"{subject}\n\n{body}"}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data=data, timeout=20)


def main():
    debug = "--debug" in sys.argv
    current = fetch_items(debug)

    if debug:
        print(f"Βρέθηκαν {len(current)} αποτελέσματα:")
        for url, d in current.items():
            print(("✅" if d["available"] else "❌"), d["title"], "-", url)
        if not current:
            print("Τίποτα. Δες το debug.html (πιθανό μπλοκάρισμα ή άλλη δομή σελίδας).")
        return

    if not current:
        print("Κανένα αποτέλεσμα – παραλείπω (πιθανό μπλοκάρισμα), κρατάω το παλιό state.")
        return

    first_run = not STATE_FILE.exists()
    old = {} if first_run else json.loads(STATE_FILE.read_text(encoding="utf-8"))

    alerts = []
    if not first_run:
        for url, d in current.items():
            if url not in old:
                alerts.append(("🆕 Νέος τίτλος" + (" (διαθέσιμος)" if d["available"] else " (εξαντλημένος)"), d, url))
            elif d["available"] and not old[url]["available"]:
                alerts.append(("✅ Ξαναδιαθέσιμο", d, url))

    for kind, d, url in alerts:
        notify(f"{kind}: {d['title']}", f"{d['title']}\n{url}")
        print("Στάλθηκε:", kind, d["title"])

    STATE_FILE.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    if first_run:
        print(f"Πρώτη εκτέλεση: αποθηκεύτηκαν {len(current)} αποτελέσματα ως βάση.")


if __name__ == "__main__":
    main()
