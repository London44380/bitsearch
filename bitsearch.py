#!/usr/bin/env python3
"""BitSearch - search for torrents across public and private BitTorrent networks.

* Public sources: apibay (TPB), Nyaa, YTS, TorrentsCSV and Archive.org, queried
  directly through their APIs / RSS feeds.
* Private trackers and many more indexers: through your own Prowlarr or Jackett
  instance (Torznab). BitSearch never bypasses any authentication: a private
  tracker is only searched if YOUR Prowlarr/Jackett is already logged in to it.

Dependencies: none (Python 3.8+, standard library only).

Only use this tool to find content you are legally allowed to download.
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import xml.parsers.expat as expat

VERSION = "1.0.0"
UA = "BitSearch/" + VERSION
TIMEOUT = 15
CONFIG_PATH = os.path.expanduser("~/.config/bitsearch/config.json")

TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.tracker.cl:1337/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://open.stealth.si:80/announce",
    "udp://exodus.desync.com:6969/announce",
]

# ------------------------------------------------------------------ banner
BANNER = r"""
 ____  _ _   ____                      _
| __ )(_) |_/ ___|  ___  __ _ _ __ ___| |__
|  _ \| | __\___ \ / _ \/ _` | '__/ __| '_ \
| |_) | | |_ ___) |  __/ (_| | | | (__| | | |
|____/|_|\__|____/ \___|\__,_|_|  \___|_| |_|
"""
PURPLES = [93, 99, 105, 135, 141, 177]  # purple gradient (256-color palette)


def use_color(stream):
    return stream.isatty() and "NO_COLOR" not in os.environ


def paint(text, code, stream=sys.stdout):
    return f"\033[38;5;{code}m{text}\033[0m" if use_color(stream) else text


def print_banner(stream=sys.stderr):
    lines = BANNER.strip("\n").split("\n")
    for i, line in enumerate(lines):
        print(paint(line, PURPLES[i % len(PURPLES)], stream), file=stream)
    print(paint(f"  torrent search - public + private (Prowlarr/Torznab) - v{VERSION}\n", 99, stream),
          file=stream)


# ------------------------------------------------------------------ helpers
MAX_BYTES = 20 * 1024 * 1024  # refuse absurdly large responses (memory exhaustion)


class _HttpOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects to http(s) only (urllib would also follow ftp://)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not re.match(r"(?i)https?://", newurl):
            raise urllib.error.URLError(f"redirect to unsupported scheme refused: {clean(newurl)[:60]}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpOnlyRedirect)


def http_get(url, headers=None, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with _OPENER.open(req, timeout=timeout) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("response too large, refused")
    return data


def _refuse_decl(*_args):
    raise ValueError("XML rejected (DOCTYPE/ENTITY declarations are not allowed)")


def safe_xml(data):
    """Parse remote XML, refusing any DOCTYPE/ENTITY declaration (XXE, billion laughs).

    A first expat pass with raising handlers runs on the DECODED document, so the check
    cannot be bypassed by re-encoding it (UTF-16, etc.). Only documents without any
    declaration reach the real parser."""
    if re.match(rb"\s*<!DOCTYPE html", data, re.I):
        raise ValueError("got an HTML page: no indexer configured in Prowlarr/Jackett, or invalid API key")
    guard = expat.ParserCreate()
    guard.StartDoctypeDeclHandler = _refuse_decl
    guard.EntityDeclHandler = _refuse_decl
    guard.ExternalEntityRefHandler = _refuse_decl
    try:
        guard.Parse(data, True)
        return ET.fromstring(data)
    except (expat.ExpatError, ET.ParseError) as e:
        raise ValueError(f"invalid XML: {clean(e)}") from None


CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
INFOHASH_RE = re.compile(r"[0-9a-fA-F]{40}|[A-Za-z2-7]{32}")


def clean(s):
    """Strip control characters (incl. ANSI escapes) from untrusted remote text."""
    return CTRL_RE.sub("", str(s if s is not None else ""))


def valid_infohash(h):
    return bool(INFOHASH_RE.fullmatch(h or ""))


def magnet(infohash, name):
    """Build a magnet link, only from a validated infohash ('' if invalid)."""
    if not valid_infohash(infohash):
        return ""
    q = "&".join(["xt=urn:btih:" + urllib.parse.quote(infohash, safe=""),
                  "dn=" + urllib.parse.quote(clean(name))]
                 + ["tr=" + urllib.parse.quote(t, safe="") for t in TRACKERS])
    return "magnet:?" + q


def safe_link(link):
    """Only magnet:, http: and https: links are ever kept or opened."""
    link = clean(link).strip()
    return link if re.match(r"(?i)(magnet:\?|https?://)", link) else ""


def mask(url):
    """Hide API keys / tokens in a displayed link or message."""
    return re.sub(r"(?i)((?:api[_-]?key|token)=)[^&\s'\"<>]+", r"\1***", url or "")


def redact(text, secrets=()):
    """mask() plus removal of the exact secret values (raw or URL-encoded) from a message."""
    text = mask(clean(text))
    for sec in secrets:
        if sec and len(sec) >= 6:
            for variant in {sec, urllib.parse.quote(sec), urllib.parse.quote(sec, safe="")}:
                text = text.replace(variant, "***")
    return text


def human(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "?"
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{u}" if u != "B" else f"{int(n)}B"
        n /= 1024
    return f"{n:.1f}PB"


def to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def result(source, name, size, seeders, leechers, link, infohash=""):
    infohash = (infohash or "").strip()
    return {"source": clean(source), "name": clean(name), "size": to_int(size),
            "seeders": to_int(seeders), "leechers": to_int(leechers), "link": safe_link(link),
            "infohash": infohash.lower() if valid_infohash(infohash) else ""}


# ------------------------------------------------------------------ public sources
def s_apibay(q, cfg):
    data = json.loads(http_get("https://apibay.org/q.php?q=" + urllib.parse.quote(q)))
    out = []
    for d in data:
        h = d.get("info_hash", "")
        if not h or set(h) == {"0"}:  # apibay returns a dummy row when nothing matches
            continue
        out.append(result("apibay", d["name"], d["size"], d["seeders"], d["leechers"],
                          magnet(h, d["name"]), h))
    return out


def s_nyaa(q, cfg):
    root = safe_xml(http_get("https://nyaa.si/?page=rss&q=" + urllib.parse.quote(q)))
    ns = {"n": "https://nyaa.si/xmlns/nyaa"}
    out = []
    for it in root.iter("item"):
        g = lambda t: (it.findtext(f"n:{t}", namespaces=ns) or "")
        h = g("infoHash")
        name = it.findtext("title") or ""
        size = g("size")
        m = re.match(r"([\d.]+)\s*(\w+)", size)
        if m:
            mult = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4}
            size = float(m.group(1)) * mult.get(m.group(2), 1)
        out.append(result("nyaa", name, size, g("seeders"), g("leechers"), magnet(h, name), h))
    return out


def s_yts(q, cfg):
    path = "/api/v2/list_movies.json?limit=20&query_term=" + urllib.parse.quote(q)
    last = None
    hosts = load_config().get("yts_hosts") or ["yts.mx", "yts.lt", "yts.am"]
    for host in hosts:  # mirrors: the first one that answers wins (override: "yts_hosts" in config)
        try:
            if not re.fullmatch(r"[A-Za-z0-9.-]+", str(host)):
                continue  # ignore malformed mirror names from the config
            movies = json.loads(http_get("https://" + host + path)).get("data", {}).get("movies") or []
            break
        except Exception as e:
            last = e
    else:
        raise last
    out = []
    for m in movies:
        for t in m.get("torrents", []):
            name = f"{m['title_long']} [{t['quality']} {t.get('type', '')}]"
            out.append(result("yts", name, t["size_bytes"], t["seeds"], t["peers"],
                              magnet(t["hash"], name), t["hash"]))
    return out


def s_torrentscsv(q, cfg):
    url = "https://torrents-csv.com/service/search?size=25&q=" + urllib.parse.quote(q)
    data = json.loads(http_get(url)).get("torrents", [])
    return [result("torrents-csv", d["name"], d["size_bytes"], d["seeders"], d["leechers"],
                   magnet(d["infohash"], d["name"]), d["infohash"]) for d in data]


def s_archive(q, cfg):
    """Archive.org: items that ship an official .torrent (no seeder statistics)."""
    term = re.sub(r'["\\]', " ", q)
    query = f'title:({term}) AND format:"Archive BitTorrent"'
    url = ("https://archive.org/advancedsearch.php?rows=25&output=json&sort%5B%5D=downloads+desc"
           "&fl%5B%5D=identifier&fl%5B%5D=title&fl%5B%5D=item_size&q=" + urllib.parse.quote(query))
    docs = json.loads(http_get(url)).get("response", {}).get("docs", [])
    out = []
    for d in docs:
        i = urllib.parse.quote(d["identifier"])
        out.append(result("archive.org", str(d.get("title", d["identifier"])), d.get("item_size", 0),
                          0, 0, f"https://archive.org/download/{i}/{i}_archive.torrent"))
    return out


# ------------------------------------------------------------------ private / aggregated sources
def s_torznab(q, cfg, label="torznab"):
    """Jackett or any Torznab feed. cfg = {"url": ..., "apikey": ...}"""
    key = cfg.get("apikey") or os.environ.get("BITSEARCH_APIKEY", "")
    if not cfg.get("url") or not key:
        raise RuntimeError("missing url/apikey")
    sep = "&" if "?" in cfg["url"] else "?"
    url = f"{cfg['url']}{sep}apikey={urllib.parse.quote(key)}&t=search&q={urllib.parse.quote(q)}"
    root = safe_xml(http_get(url))
    if root.tag == "error":
        raise RuntimeError(root.get("description", "torznab error"))
    out = []
    for it in root.iter("item"):
        attrs = {a.get("name"): a.get("value") for a in it.iter() if a.tag.endswith("attr")}
        name = it.findtext("title") or ""
        h = attrs.get("infohash", "")
        link = attrs.get("magneturl") or (magnet(h, name) if h else "") \
            or (it.find("enclosure").get("url") if it.find("enclosure") is not None else "") \
            or (it.findtext("link") or "")
        seeders = attrs.get("seeders", 0)
        peers = to_int(attrs.get("peers", 0))
        out.append(result(f"{label}:{attrs.get('indexer') or it.findtext('jackettindexer') or 'idx'}",
                          name, it.findtext("size") or attrs.get("size", 0),
                          seeders, max(peers - to_int(seeders), 0), link, h))
    return out


def s_prowlarr(q, cfg, label="prowlarr"):
    """Prowlarr (JSON API). One request PER indexer, in parallel: a slow or broken
    indexer never prevents the others from answering. cfg = {"url", "apikey"}"""
    key = cfg.get("apikey") or os.environ.get("BITSEARCH_APIKEY", "")
    if not cfg.get("url") or not key:
        raise RuntimeError("missing url/apikey")
    base, hdr = cfg["url"].rstrip("/"), {"X-Api-Key": key}
    indexers = [i for i in json.loads(http_get(base + "/api/v1/indexer", hdr)) if i.get("enable")]
    if not indexers:
        raise RuntimeError("no enabled indexer in Prowlarr")

    def one(idx):
        url = (f"{base}/api/v1/search?type=search&limit=50&indexerIds={idx['id']}&query="
               + urllib.parse.quote(q))
        return json.loads(http_get(url, hdr, timeout=int(cfg.get("indexer_timeout", 15))))

    out = []
    with cf.ThreadPoolExecutor(max_workers=min(len(indexers), 16)) as ex:
        for fut in cf.as_completed([ex.submit(one, i) for i in indexers]):
            try:
                data = fut.result()
            except Exception:
                continue  # slow or broken indexer: skip it
            for d in data:
                h = (d.get("infoHash") or "").lower()
                mu = d.get("magnetUrl") or ""
                link = (magnet(h, d.get("title", "")) or
                        (mu if mu.startswith("magnet:") else d.get("downloadUrl") or mu))
                out.append(result(f"{label}:{d.get('indexer', 'idx')}", d.get("title", ""),
                                  d.get("size", 0), d.get("seeders") or 0,
                                  d.get("leechers") or 0, link, h))
    return out


PUBLIC = {"apibay": s_apibay, "nyaa": s_nyaa, "yts": s_yts, "torrents-csv": s_torrentscsv,
          "archive.org": s_archive}


# ------------------------------------------------------------------ config
EXAMPLE_CONFIG = {
    "_help": "Private trackers: point BitSearch at your own Prowlarr or Jackett. The API key may "
             "also come from the BITSEARCH_APIKEY environment variable. This file is created "
             "with mode 600 - never commit it.",
    "torznab": [
        {"name": "prowlarr", "type": "prowlarr", "url": "http://127.0.0.1:9696",
         "apikey": "", "enabled": False},
        {"name": "jackett", "url": "http://127.0.0.1:9117/api/v2.0/indexers/all/results/torznab/api",
         "apikey": "", "enabled": False},
    ],
}


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def init_config():
    if os.path.exists(CONFIG_PATH):
        print(f"Already exists: {CONFIG_PATH}")
        return
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    fd = os.open(CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(EXAMPLE_CONFIG, f, indent=2)
    print(f"Config created (mode 600): {CONFIG_PATH}\nEdit it to enable your private indexers.")


# ------------------------------------------------------------------ search
def search(query, only=None, skip=None, privacy="all"):
    cfg = load_config()
    secrets = [t.get("apikey") for t in cfg.get("torznab", [])] + [os.environ.get("BITSEARCH_APIKEY")]
    jobs = {}
    if privacy in ("all", "public"):
        for n, fn in PUBLIC.items():
            jobs[n] = (fn, {})
    if privacy in ("all", "private"):
        for t in cfg.get("torznab", []):
            if t.get("enabled", True) and t.get("url"):
                fn = s_prowlarr if t.get("type") == "prowlarr" else s_torznab
                jobs[t["name"]] = (lambda q, c, n=t["name"], f=fn: f(q, c, n), t)
    if only:
        jobs = {k: v for k, v in jobs.items() if k in only}
    if skip:
        jobs = {k: v for k, v in jobs.items() if k not in skip}

    results, errors = [], {}
    with cf.ThreadPoolExecutor(max_workers=max(len(jobs), 1)) as ex:
        futs = {ex.submit(fn, query, c): n for n, (fn, c) in jobs.items()}
        for fut in cf.as_completed(futs):
            n = futs[fut]
            try:
                results += fut.result()
            except Exception as e:  # a failing source never blocks the others
                errors[n] = redact(f"{type(e).__name__}: {e}", secrets)
    # de-duplicate by infohash (keep the entry with the most seeders)
    best = {}
    for r in results:
        k = r["infohash"] or r["link"] or r["name"]
        if k not in best or r["seeders"] > best[k]["seeders"]:
            best[k] = r
    return list(best.values()), errors, list(jobs)


def show(results, limit):
    if not results:
        print(paint("No results.", 135))
        return
    results = results[:limit]
    w = min(max(len(r["name"]) for r in results), 70)
    head = f"{'#':>3}  {'SEED':>5} {'LEECH':>5} {'SIZE':>9}  {'SOURCE':<18} NAME"
    print(paint(head, 177))
    for i, r in enumerate(results, 1):
        name = r["name"] if len(r["name"]) <= w else r["name"][: w - 1] + "…"
        seeds = paint(format(r["seeders"], ">5"), 135)
        print(f"{i:>3}  {seeds} {r['leechers']:>5} "
              f"{human(r['size']):>9}  {r['source'][:18]:<18} {name}")


def main():
    ap = argparse.ArgumentParser(prog="bitsearch",
                                 description="Search for torrents (public + private networks).")
    ap.add_argument("query", nargs="*", help="search terms")
    ap.add_argument("-n", "--limit", type=int, default=25, help="number of results (default 25)")
    ap.add_argument("-s", "--source", action="append", help="only use this source (repeatable)")
    ap.add_argument("-x", "--skip", action="append", help="exclude this source (repeatable)")
    ap.add_argument("--public", action="store_true", help="public networks only")
    ap.add_argument("--private", action="store_true", help="private indexers (Prowlarr/Torznab) only")
    ap.add_argument("--min-seeders", type=int, default=0, metavar="N",
                    help="hide results with fewer than N seeders")
    ap.add_argument("-m", "--magnet", action="store_true", help="also print magnet/torrent links")
    ap.add_argument("-p", "--pick", type=int,
                    help="print only the raw link of result N (may contain an API key for "
                         "Prowlarr .torrent links - do not share it)")
    ap.add_argument("-i", "--interactive", action="store_true",
                    help="pick a result, then open its magnet link (xdg-open)")
    ap.add_argument("--json", action="store_true", help="JSON output (API keys masked)")
    ap.add_argument("--list-sources", action="store_true", help="list available sources")
    ap.add_argument("--init-config", action="store_true",
                    help="create ~/.config/bitsearch/config.json")
    ap.add_argument("--no-banner", action="store_true", help="do not print the banner")
    ap.add_argument("--version", action="version", version="bitsearch " + VERSION)
    a = ap.parse_args()

    if not a.no_banner and not a.json and a.pick is None:
        print_banner()
    if a.init_config:
        return init_config()
    if a.list_sources:
        print("Public :", ", ".join(PUBLIC))
        print("Private:", ", ".join(t["name"] for t in load_config().get("torznab", [])
                                    if t.get("enabled", True)) or "(none - see --init-config)")
        return
    if not a.query:
        ap.error("please give a search query")

    privacy = "public" if a.public else "private" if a.private else "all"
    q = " ".join(a.query)
    results, errors, used = search(q, a.source, a.skip, privacy)
    results.sort(key=lambda r: r["seeders"], reverse=True)
    results = [r for r in results if r["seeders"] >= a.min_seeders and r["link"]]

    if a.json:
        print(json.dumps({"query": q,
                          "results": [{**r, "link": mask(r["link"])} for r in results[: a.limit]],
                          "errors": errors}, indent=2))
        return
    if a.pick is not None:
        if not 1 <= a.pick <= len(results):
            sys.exit("Result number out of range")
        print(results[a.pick - 1]["link"])
        return

    print(paint(f"Searching '{q}' on {len(used)} source(s): {', '.join(used)}", 99))
    show(results, a.limit)
    if a.magnet:
        for i, r in enumerate(results[: a.limit], 1):
            print(f"\n[{i}] {r['name']}\n    {mask(r['link'])}")
    for n, e in errors.items():
        print(paint(f"! {clean(n)}: {clean(e)}", 125), file=sys.stderr)
    if errors:
        print(paint(
            "  Sites change or go down. A failing source is skipped; to silence it use "
            "'-x <source>' (see --list-sources).\n"
            "  If it keeps failing: update BitSearch, replace the site in your config "
            "(e.g. \"yts_hosts\"), or remove/replace that indexer in Prowlarr.", 245), file=sys.stderr)
    if a.interactive and results and sys.stdin.isatty():
        shown = results[: a.limit]
        while True:
            try:
                c = input(paint("\nNumber to open (c N = print link, q = quit): ", 177)).strip()
            except EOFError:
                break
            if c in ("q", ""):
                break
            copy = c.startswith("c ")
            if copy:
                c = c[2:].strip()
            if not c.isdigit() or not 1 <= int(c) <= len(shown):
                print("Invalid number")
                continue
            r = shown[int(c) - 1]
            if copy:
                print(mask(r["link"]))
            else:
                if not safe_link(r["link"]) or r["link"].startswith("-"):
                    print("Refusing to open this link (unsupported scheme)")
                    continue
                subprocess.Popen(["xdg-open", r["link"]], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                print(paint("Opened: " + r["name"], 99))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
