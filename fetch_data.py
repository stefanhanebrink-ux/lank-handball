#!/usr/bin/env python3
"""Holt alle Spiele der 2. BK Männer (HK Krefeld-Grenzland) von handball.net
und schreibt site/data.json für die App. Nur Standardbibliothek.

Bei Problemen schreibt das Skript site/debug.txt (Rohdaten-Auszug und Fehler)
und beendet sich mit Fehlercode, sodass die App weiter die letzten Daten zeigt."""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BASE = "https://www.handball.net/api/new/matches"
SEASON_FROM = "2026-07-01"
SEASON_TO = "2027-07-31"
ME_ID = 76164
LIGA = "2. Bezirksklasse Männer · HK Krefeld-Grenzland · Saison 2026/27"

# Teams der Staffel (IDs von handball.net)
TEAMS = {
    76164: "TD Lank 3. Herren",
    76161: "VT Kempen II",
    76162: "TV Boisheim II",
    76163: "Tschft. Grefrath III",
    76165: "ASV Süchteln 4M",
    76166: "Handball Oppum IV",
    63438: "Tschft. St. Tönis IV",
    63473: "TuS St. Hubert",
    63534: "Adler Königshof 4M",
    63651: "Eagles Niederrhein III",
    75176: "TV Erkelenz 1860",
    96181: "ASV Rurtal Hückelhoven II",
}
NAME_TO_ID = {re.sub(r"\W+", "", n).lower(): i for i, n in TEAMS.items()}

DEBUG = []


def log(msg):
    print(msg)
    DEBUG.append(str(msg))


def http_json(url):
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; lank-app/1.0)",
            "Accept-Language": "de-DE,de;q=0.9",
        },
    )
    last = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read().decode("utf-8", "replace")
            return json.loads(raw), raw
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{url} -> {last}")


def first(d, *keys):
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def extract_list(resp):
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for k in ("data", "matches", "results", "items", "games"):
            v = resp.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                for kk in ("data", "matches", "items"):
                    if isinstance(v.get(kk), list):
                        return v[kk]
    return []


def fetch_team(team_id):
    """Alle Spiele einer Mannschaft, mehrere Parametervarianten, mit Seiten."""
    variants = [
        {"team_id": team_id, "date_from": SEASON_FROM, "date_to": SEASON_TO},
        {"team_id": team_id},
    ]
    for params in variants:
        out, sample = [], None
        for page in range(1, 11):
            q = dict(params, per_page=100, page=page)
            url = BASE + "?" + urllib.parse.urlencode(q)
            try:
                resp, raw = http_json(url)
            except Exception as e:  # noqa: BLE001
                log(f"Fehler bei {url}: {e}")
                break
            if sample is None:
                sample = raw[:3000]
            items = extract_list(resp)
            out.extend(items)
            if len(items) < 100:
                break
        if out:
            return out, sample
        log(f"Keine Spiele für Team {team_id} mit Parametern {params}")
    return [], None


def parse_dt(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        ts = v / 1000 if v > 1e11 else v
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ZoneInfo("Europe/Berlin"))
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
    m = re.search(r"(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d)", str(v))
    if m:
        return f"{m[1]}-{m[2]}-{m[3]}", f"{m[4]}:{m[5]}"
    m = re.search(r"(\d{4})-(\d\d)-(\d\d)", str(v))
    if m:
        return f"{m[1]}-{m[2]}-{m[3]}", "00:00"
    return None


def team_ref(obj):
    """Liefert (id, name) für ein Team-Feld, das Objekt oder Text sein kann."""
    if isinstance(obj, dict):
        tid = first(obj, "id", "team_id", "teamId")
        name = first(obj, "name", "shortName", "short_name", "title", "teamName")
        try:
            tid = int(tid) if tid is not None else None
        except (TypeError, ValueError):
            tid = None
        return tid, name
    if isinstance(obj, str):
        return None, obj
    return None, None


def resolve(tid, name):
    if tid in TEAMS:
        return tid, TEAMS[tid]
    if name:
        key = re.sub(r"\W+", "", name).lower()
        if key in NAME_TO_ID:
            i = NAME_TO_ID[key]
            return i, TEAMS[i]
    return None, name


def to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_match(m):
    dt = parse_dt(first(m, "date", "start", "startsAt", "starts_at", "datetime", "kickoff", "startDate"))
    if not dt:
        return None
    home = first(m, "local", "home", "homeTeam", "home_team", "team1", "teamHome")
    away = first(m, "visitor", "away", "awayTeam", "away_team", "team2", "teamAway")
    hid, hname = resolve(*team_ref(home))
    aid, aname = resolve(*team_ref(away))
    if not hname or not aname:
        return None

    status = first(m, "status", "state")
    finished = None
    if isinstance(status, dict):
        finished = first(status, "is_finished", "isFinished", "finished")
        sname = str(first(status, "name", "label") or "")
    else:
        sname = str(status or "")
    if finished is None and sname:
        finished = bool(re.search(r"(beend|finish|final|ended|played|gespielt)", sname, re.I))

    res = first(m, "result", "score", "results")
    hs = as_ = None
    if isinstance(res, dict):
        hs = to_int(first(res, "local", "home", "homeGoals", "home_goals"))
        as_ = to_int(first(res, "visitor", "away", "awayGoals", "away_goals"))
    if hs is None:
        hs = to_int(first(m, "homeGoals", "home_goals", "homeScore", "home_score", "goalsHome", "local_score"))
        as_ = to_int(first(m, "awayGoals", "away_goals", "awayScore", "away_score", "goalsAway", "visitor_score"))
    if isinstance(res, str):
        mm = re.search(r"(\d+)\s*[:\-]\s*(\d+)", res)
        if mm:
            hs, as_ = int(mm[1]), int(mm[2])

    played = hs is not None and as_ is not None
    if finished is False:
        played = False
    elif finished is None and played and hs + as_ == 0:
        played = False
    if not played:
        hs = as_ = None

    venue = first(m, "field", "installation", "venue", "location", "hall", "gym")
    if isinstance(venue, dict):
        venue = first(venue, "name", "title") or ""
    cancelled = bool(re.search(r"(abgesetzt|cancel|postponed|verlegt)", sname, re.I))

    return {
        "key": str(first(m, "id", "match_id", "matchId") or f"{dt[0]}-{hname}-{aname}"),
        "date": dt[0],
        "time": dt[1],
        "home": hname,
        "away": aname,
        "hid": hid,
        "aid": aid,
        "hs": hs,
        "as": as_,
        "venue": str(venue or ""),
        "cancelled": cancelled,
    }


def main():
    os.makedirs("site", exist_ok=True)
    seen, matches, samples = {}, [], {}
    for tid in TEAMS:
        items, sample = fetch_team(tid)
        samples[tid] = sample
        log(f"Team {tid} ({TEAMS[tid]}): {len(items)} Roh-Einträge")
        for it in items:
            p = parse_match(it)
            if not p:
                continue
            # nur Spiele innerhalb der Staffel (beide Teams bekannt)
            if p["hid"] not in TEAMS or p["aid"] not in TEAMS:
                continue
            if p["cancelled"]:
                continue
            if p["key"] in seen:
                continue
            seen[p["key"]] = True
            matches.append(p)

    mine = [m for m in matches if ME_ID in (m["hid"], m["aid"])]
    log(f"Gesamt: {len(matches)} Spiele, davon {len(mine)} der Lank, "
        f"{sum(1 for m in matches if m['hs'] is not None)} gespielt")

    def write_debug():
        import html as _h
        parts = ["\n".join(DEBUG), "", "Rohdaten-Auszug (erstes Team mit Antwort):"]
        for tid, smp in samples.items():
            if smp:
                parts.append(f"--- Team {tid} ---\n{smp}")
                break
        with open("site/debug.html", "w", encoding="utf-8") as f:
            f.write("<!doctype html><meta charset='utf-8'><pre style='white-space:pre-wrap'>"
                    + _h.escape("\n".join(parts)) + "</pre>")

    if not mine:
        log("FEHLER: Keine Spiele der Lank erkannt. Das Antwortformat der Schnittstelle weicht ab.")
        write_debug()
        sys.exit(1)

    matches.sort(key=lambda m: (m["date"], m["time"]))
    for m in matches:
        for k in ("key", "hid", "aid", "cancelled"):
            m.pop(k, None)

    stand = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y, %H:%M Uhr")
    data = {
        "team": TEAMS[ME_ID],
        "teamId": ME_ID,
        "liga": LIGA,
        "stand": stand,
        "teams": sorted(TEAMS.values()),
        "matches": matches,
    }
    with open("site/data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    write_debug()
    log("OK: site/data.json geschrieben")


if __name__ == "__main__":
    main()
