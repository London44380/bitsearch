# BitSearch

> Command-line torrent search across public BitTorrent networks and your own private indexers — one query, many sources, no dependencies.

```
 ____  _ _   ____                      _
| __ )(_) |_/ ___|  ___  __ _ _ __ ___| |__
|  _ \| | __\___ \ / _ \/ _` | '__/ __| '_ \
| |_) | | |_ ___) |  __/ (_| | | | (__| | | |
|____/|_|\__|____/ \___|\__,_|_|  \___|_| |_|
```

![BitSearch demo](docs/demo.gif)

*Real output of the tool (public sources only, free/Linux content), rendered by `docs/make_demo.py`.*

## Features

- **Public sources, no account needed**: apibay (The Pirate Bay), Nyaa, YTS (with mirror fallback), TorrentsCSV, Archive.org.
- **Private trackers and 80+ more indexers** through your own [Prowlarr](https://prowlarr.com) or [Jackett](https://github.com/Jackett/Jackett) (Torznab). BitSearch only talks to indexers *you* have configured and logged in to — it never bypasses authentication.
- **Fast**: every source is queried in parallel; with Prowlarr, every indexer is queried separately so one slow or broken indexer never blocks the rest.
- Results de-duplicated by infohash, sorted by seeders, with ready-to-use magnet links.
- Interactive mode, JSON output, seeder filter, per-source include/exclude.
- **Pure Python 3.8+ standard library** — nothing to `pip install`.
- API keys are masked in all displayed links and in JSON output.

## Install

```bash
git clone https://forgejo.london.li/London088/bitsearch.git
cd bitsearch
./install.sh            # installs to ~/.local/bin (no root needed)
```

Options: `./install.sh --prefix /some/dir` or `./install.sh --uninstall`. You can also just run `python3 bitsearch.py ...` directly.

## Usage

```bash
bitsearch ubuntu 24.04                 # all sources
bitsearch debian --public -n 10        # public sources only, 10 results
bitsearch debian --min-seeders 5       # hide dead torrents
bitsearch debian -s nyaa -s yts        # only these sources
bitsearch debian -x archive.org        # exclude a source
bitsearch debian -m                    # also print magnet / torrent links
bitsearch debian -i                    # pick a number, open the magnet (xdg-open)
bitsearch debian -p 1                  # print the raw link of result #1
bitsearch debian --json                # machine-readable output
bitsearch --list-sources
```

Colors are disabled automatically when output is not a terminal or when `NO_COLOR` is set.

## Private trackers and extra indexers (optional)

BitSearch works out of the box with the public sources. To add private trackers (and many more public indexers):

1. Run Prowlarr or Jackett yourself and add your indexers there, with **your own** accounts.
2. Create the config: `bitsearch --init-config` (creates `~/.config/bitsearch/config.json`, mode 600).
3. Enable your entry and fill in the API key — or leave `apikey` empty and export `BITSEARCH_APIKEY`:

```json
{
  "torznab": [
    { "name": "prowlarr", "type": "prowlarr", "url": "http://127.0.0.1:9696",
      "apikey": "", "enabled": true, "indexer_timeout": 15 },
    { "name": "jackett",
      "url": "http://127.0.0.1:9117/api/v2.0/indexers/all/results/torznab/api",
      "apikey": "", "enabled": false }
  ]
}
```

`"type": "prowlarr"` uses Prowlarr's JSON API (recommended); without it the entry is treated as a generic Torznab feed (Jackett, etc.).

Private trackers require an account, and often an invitation — BitSearch cannot and will not search them without credentials.

## Privacy and safety notes

- **Searching** only makes web requests, like a browser. **Downloading** a torrent exposes your IP address to every peer in the swarm: consider a VPN, and make sure your torrent client is bound to the VPN interface.
- Remote XML (RSS / Torznab) is checked by expat after decoding and any `DOCTYPE`/`ENTITY` declaration is rejected, whatever the encoding (XXE / entity-expansion protection).
- Everything coming from remote sites (names, links, error messages) is treated as untrusted: control and ANSI escape characters are stripped before display, magnet links are only built from a validated infohash, and only `magnet:` / `http(s):` links are ever opened.
- Run the security tests with `python3 -I tests/test_security.py`.
- Never commit `config.json`: it contains your API key. It is already in `.gitignore`.
- If you run Prowlarr, keep it bound to `127.0.0.1` with authentication enabled.

## When a source stops working

Public sites change domains, add Cloudflare protection or disappear. BitSearch reports the failing source and keeps going with the others. If one keeps failing:

- **Skip it**: `bitsearch <query> -x <source>` (names via `bitsearch --list-sources`).
- **Change the site**: for YTS, set your own mirrors in `~/.config/bitsearch/config.json`: `"yts_hosts": ["yts.example", "yts.mirror"]` (first one that answers is used).
- **Prowlarr indexers**: remove or replace the broken indexer in Prowlarr (Indexers page); BitSearch picks up the change automatically.
- **Update BitSearch**: `git pull` and re-run `./install.sh`; new releases follow site changes.

## Limitations

- The public sources use unofficial APIs; they can change, rate-limit or disappear. A failing source is reported and skipped.
- Some sites sit behind Cloudflare challenges and cannot be used (BitSearch does not try to bypass them).
- Archive.org items have no seeder statistics (shown as 0).

## Disclaimer

BitSearch is a search tool, like a web browser. You are responsible for what you download. Only download content you have the right to — Linux distributions, public-domain works, your own media, and so on — and respect the laws of your country and the terms of the services you use.

## License

MIT — see [LICENSE](LICENSE).
