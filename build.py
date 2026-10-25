#!/usr/bin/env python3
"""Insider Cluster Buys: static-site + member-digest builder (MonRiah, 2026-10-25).

Pulls open-market insider purchases (Form 4 code P) from OUR OWN SEC EDGAR Worker's free MCP
endpoint (which already scans EDGAR under SEC fair-access rules), then writes:
  out/site/      free, indexable static site (hub, per-issuer cluster pages, daily archive, RSS, sitemap)
  out/members/   paid-member files (full 30-day CSV + daily brief .md/.html) -> upload to the gated feed
  out/posts/     DRAFT social posts (not posted; posting needs approval)
History is kept in data/history/*.json so the daily archive grows into unique, original content.
Usage: python3 build.py [--site-url https://example.netlify.app] [--offline /path/mib.json]
"""
import json, os, sys, csv, html, datetime, urllib.request, argparse, pathlib

MCP = "https://sec-edgar-api.kidriahx.workers.dev/mcp"
RAPIDAPI = "https://rapidapi.com/KidriahChannel/api/sec-edgar-insider-trading-financials-api"
APIFY = "https://apify.com/monriah-studio/sec-form4-insider-trades"
MEMBERSHIP = os.environ.get("MEMBERSHIP_URL", "")  # set once the Gumroad membership exists; empty = no membership CTA
DISCLAIMER = "Data from public SEC Form 4 filings. For information only, not investment advice. Created by Caleb Love."
ROOT = pathlib.Path(__file__).resolve().parent
esc = html.escape

def mcp_call(args):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "get_market_insider_buys", "arguments": args}}).encode()
    req = urllib.request.Request(MCP, data=body, headers={"content-type": "application/json",
            "accept": "application/json, text/event-stream", "user-agent": "MonRiah insider-clusters builder"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    return json.loads(d["result"]["content"][0]["text"])

def money(v):
    v = float(v or 0)
    return f"${v/1e6:.2f}M" if v >= 1e6 else (f"${v/1e3:.0f}K" if v >= 1e3 else f"${v:,.0f}")

def slug(t): return "".join(ch for ch in (t or "").lower() if ch.isalnum() or ch == "-") or "na"

def summary(r):
    """Deterministic plain-English read of the numbers (no LLM, no advice)."""
    roles = [i["role"] for i in r.get("insiders", [])]
    officers = sum(1 for x in roles if any(k in x for k in ("Chief", "CEO", "CFO", "President", "Officer")))
    directors = sum(1 for x in roles if "Director" in x)
    owners = sum(1 for x in roles if "10%" in x)
    top = max(r.get("insiders", []), key=lambda i: i.get("valueUsd", 0), default=None)
    span = (f"on {r['firstDate']}" if r["firstDate"] == r["lastDate"] else f"between {r['firstDate']} and {r['lastDate']}")
    s = (f"{r['insiderCount']} insiders of {esc(r['issuer'])} bought shares on the open market {span}, "
         f"{money(r['totalValueUsd'])} in total ({int(r['totalShares']):,} shares at an average of ${r['avgPrice']:,.2f}). ")
    parts = [f"{n} {w}" for n, w in ((officers, "officer(s)"), (directors, "director(s)"), (owners, "10% owner(s)")) if n]
    if parts: s += "Buyers include " + ", ".join(parts) + ". "
    if top and r["totalValueUsd"]:
        s += f"The largest single buyer, {esc(top['name'])} ({esc(top['role'])}), accounts for {100*top['valueUsd']/r['totalValueUsd']:.0f}% of the dollar value."
    return s

CSS = ("body{font:16px/1.55 system-ui,sans-serif;max-width:980px;margin:0 auto;padding:1rem;color:#1b1b1b}"
       "table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid #ddd;padding:.35rem;text-align:left}"
       "th{background:#f4f4f4}.note{font-size:13px;color:#555}.cta{background:#f6f8ff;border:1px solid #cdd6ff;padding:1rem;border-radius:8px;margin:1rem 0}"
       "a{color:#1a4fd6}nav a{margin-right:1rem}.disclaimer{background:#fff8e1;border:1px solid #f0d58a;padding:.5rem .75rem;border-radius:6px;font-size:14px}")

def cta():
    m = (f'<strong>Daily member feed:</strong> full 30-day CSV, every issuer and a private RSS feed: <a href="{MEMBERSHIP}">Insider Clusters Daily</a>. ' if MEMBERSHIP else "")
    return (f'<div class="cta">{m}<strong>Developers:</strong> <a href="{RAPIDAPI}">REST API on RapidAPI</a> · <a href="{APIFY}">Apify actor</a> · '
            f'free MCP endpoint <code>{MCP}</code>.</div>')

def page(title, desc, body, canon, depth):
    up = "../" * depth
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}"><link rel="canonical" href="{canon}">
<link rel="alternate" type="application/rss+xml" title="Insider cluster buys" href="{up}feed.xml"><link rel="stylesheet" href="{up}style.css"></head><body>
<nav><a href="{up}">Cluster buys today</a><a href="{up}archive/">Daily archive</a><a href="{up}methodology/">Methodology</a><a href="{up}feed.xml">RSS</a></nav>
<p class="disclaimer"><strong>{DISCLAIMER}</strong></p>
{body}
{cta()}
<p class="note">Data: U.S. SEC EDGAR Form 4 filings (public domain), open-market non-derivative purchases (code P) only, parsed automatically by MonRiah Studio. Pages are generated by software from those filings; summaries are computed from the numbers, not written by a person. Not affiliated with the SEC. <strong>Not investment advice</strong>; insider buying is one data point, filings can be amended, and parsing can be wrong; always check the linked filing. </p>
<footer><p class="disclaimer"><strong>{DISCLAIMER}</strong></p></footer>
</body></html>"""

def table(rows, depth, link_clusters=True):
    up = "../" * depth
    h = "<table><tr><th>Ticker</th><th>Company</th><th>Insiders</th><th>Total bought</th><th>Avg price</th><th>Dates</th><th>Filing</th></tr>"
    for r in rows:
        t = esc(r["ticker"] or "n/a")
        tl = f'<a href="{up}{slug(r["ticker"] or r["cik"])}/">{t}</a>' if (link_clusters and r["clusterBuy"]) else t
        h += (f"<tr><td>{tl}</td><td>{esc(r['issuer'])}</td><td>{r['insiderCount']}</td><td>{money(r['totalValueUsd'])}</td>"
              f"<td>${r['avgPrice']:,.2f}</td><td>{r['firstDate']}–{r['lastDate']}</td><td><a href=\"{esc(r['latestFilingUrl'])}\" rel=\"nofollow\">SEC</a></td></tr>")
    return h + "</table>"

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--site-url", default="https://insider-clusters.netlify.app")
    ap.add_argument("--offline"); a = ap.parse_args(); base = a.site_url.rstrip("/") + "/"
    d30 = json.load(open(a.offline)) if a.offline else mcp_call({"days": 30, "limit": 100})
    if a.offline and "result" in d30: d30 = json.loads(d30["result"]["content"][0]["text"])
    rows = d30["results"]; today = d30["window"]["to"]
    for r in rows:
        r.setdefault("ticker", ""); r["ticker"] = r["ticker"] or ""
        for k, dv in (("avgPrice", 0), ("totalShares", 0), ("totalValueUsd", 0), ("insiders", []), ("latestFilingUrl", ""), ("issuer", "")):
            if r.get(k) is None: r[k] = dv
        r.setdefault("firstDate", r.get("lastDate", "")); r.setdefault("lastDate", r["firstDate"])
    hist = ROOT / "data/history"; hist.mkdir(parents=True, exist_ok=True)
    (hist / f"{today}.json").write_text(json.dumps(d30))
    site = ROOT / "out/site"; mem = ROOT / "out/members"; posts = ROOT / "out/posts"
    for p in (site, mem, posts): p.mkdir(parents=True, exist_ok=True)
    (site / "style.css").write_text(CSS)
    week_cut = (datetime.date.fromisoformat(today) - datetime.timedelta(days=7)).isoformat()
    clusters = [r for r in rows if r["clusterBuy"]]
    week = [r for r in clusters if r["lastDate"] >= week_cut]
    urls = [base]
    # hub
    body = (f"<h1>Insider cluster buys: {today}</h1><p>Companies where <strong>two or more insiders</strong> bought their own stock on the open market. "
            f"Updated daily from SEC Form 4 filings. {len(week)} cluster buys in the last 7 days, {len(clusters)} in the last 30.</p>"
            f"<h2>Last 7 days</h2>{table(week,0)}<h2>Last 30 days (all cluster buys)</h2>{table(clusters,0)}"
            f"<h2>Largest single-insider purchases (30 days)</h2>{table(sorted([r for r in rows if not r['clusterBuy']], key=lambda r:-r['totalValueUsd'])[:10],0,False)}")
    (site / "index.html").write_text(page(f"Insider cluster buys today ({today}): SEC Form 4 open-market purchases",
        "Daily list of stocks where 2+ insiders bought shares on the open market, from SEC Form 4 filings.", body, base, 0))
    # per-issuer pages (clusters only, so every page has substance)
    for r in clusters:
        s = slug(r["ticker"] or r["cik"]); (site / s).mkdir(exist_ok=True); u = base + s + "/"; urls.append(u)
        ins = "".join(f"<tr><td>{esc(i['name'])}</td><td>{esc(i['role'])}</td><td>{money(i['valueUsd'])}</td></tr>" for i in r["insiders"])
        b = (f"<h1>{esc(r['ticker'] or '')} insider buying: {esc(r['issuer'])}</h1><p>{summary(r)}</p>"
             f"<table><tr><th>Insider</th><th>Role</th><th>Bought</th></tr>{ins}</table>"
             f"<p>Latest filing: <a href=\"{esc(r['latestFilingUrl'])}\" rel=\"nofollow\">SEC EDGAR</a> · "
             f"<a href=\"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={r['cik']}&type=4\" rel=\"nofollow\">all Form 4s for CIK {r['cik']}</a></p>")
        (site / s / "index.html").write_text(page(f"{r['ticker']} insider buying: {r['insiderCount']} insiders bought {money(r['totalValueUsd'])} ({r['lastDate']})",
            f"{r['insiderCount']} insiders of {r['issuer']} bought {money(r['totalValueUsd'])} of stock on the open market. Source: SEC Form 4.", b, u, 1))
    # daily archive (grows with history)
    arch = site / "archive"; arch.mkdir(exist_ok=True); items = []
    for f in sorted(hist.glob("*.json"), reverse=True):
        dd = json.loads(f.read_text()); day = f.stem; (arch / day).mkdir(exist_ok=True)
        cl = [r for r in dd["results"] if r["clusterBuy"]]
        (arch / day / "index.html").write_text(page(f"Insider cluster buys as of {day}", f"Snapshot of SEC Form 4 cluster buys on {day}.",
            f"<h1>Snapshot: {day}</h1><p>{len(cl)} cluster buys in the 30 days to {day}.</p>{table(cl,2,False)}", base+f"archive/{day}/", 2))
        urls.append(base + f"archive/{day}/"); items.append(f'<li><a href="{day}/">{day}</a>: {len(cl)} cluster buys</li>')
    (arch / "index.html").write_text(page("Insider cluster buys: daily archive", "Every daily snapshot.", "<h1>Daily archive</h1><ul>"+"".join(items)+"</ul>", base+"archive/", 1)); urls.append(base+"archive/")
    (site / "methodology").mkdir(exist_ok=True); urls.append(base+"methodology/")
    (site / "methodology/index.html").write_text(page("Methodology: how insider cluster buys are detected", "How the list is built from SEC Form 4.",
        "<h1>Methodology</h1><ul><li>Source: every new Form 4 on SEC EDGAR, scanned every 10 minutes by our Worker under SEC fair-access rules (declared User-Agent, &lt;10 req/s).</li>"
        "<li>Only non-derivative transactions with code <b>P</b> (open-market or private purchase) count. Awards, option exercises, tax withholding and gifts are excluded.</li>"
        "<li>Grouped by issuer over the look-back window; a <b>cluster buy</b> = 2+ distinct reporting owners.</li><li>Coverage starts when the scanner was deployed and rolls up to 30 days.</li>"
        "<li>Known limits: amended filings, joint filers (funds and their managers can both appear), and parsing errors. Always read the filing.</li></ul>", base+"methodology/", 1))
    # RSS + sitemap + robots
    it = "".join(f"<item><title>{esc(r['ticker'] or '')}: {r['insiderCount']} insiders bought {money(r['totalValueUsd'])}</title><link>{base}{slug(r['ticker'] or r['cik'])}/</link>"
                 f"<guid isPermaLink=\"false\">{r['cik']}-{r['lastDate']}-{r['insiderCount']}</guid><description>{esc(summary(r))} {esc(DISCLAIMER)}</description></item>" for r in week)
    (site / "feed.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Insider cluster buys</title><link>{base}</link><description>2+ insiders buying on the open market. {esc(DISCLAIMER)}</description><copyright>Created by Caleb Love</copyright>{it}</channel></rss>')
    (site / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(f"<url><loc>{u}</loc><lastmod>{today}</lastmod></url>" for u in urls) + "</urlset>")
    (site / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base}sitemap.xml\n")
    (site / "netlify.toml").write_text('[build]\n  publish = "."\n  command = ""\n')
    # members: full CSV + brief
    with open(mem / f"insider_buys_30d_{today}.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["ticker","issuer","cik","insider_count","cluster","total_usd","shares","avg_price","first_date","last_date","insiders","filing_url"])
        for r in rows: w.writerow([r["ticker"], r["issuer"], r["cik"], r["insiderCount"], r["clusterBuy"], round(r["totalValueUsd"],2), r["totalShares"], r["avgPrice"], r["firstDate"], r["lastDate"], "; ".join(f"{i['name']} ({i['role']})" for i in r["insiders"]), r["latestFilingUrl"]])
    brief = [f"# Insider Clusters Daily: {today}", "", f"{len(week)} cluster buys in 7 days · {len(clusters)} in 30 days · {len(rows)} issuers with any open-market insider buying.", "", "## New or growing clusters (7 days)"]
    brief += [f"- **{r['ticker']}** {r['issuer']}: {summary(r)}".replace("&amp;","&") for r in week] or ["- none"]
    brief += ["", "## Biggest solo buys (30 days)"] + [f"- **{r['ticker']}** {r['issuer']}: {money(r['totalValueUsd'])} by {r['insiders'][0]['name']} ({r['insiders'][0]['role']}), {r['lastDate']}" for r in sorted([r for r in rows if not r['clusterBuy'] and r['insiders']], key=lambda r:-r['totalValueUsd'])[:10]]
    brief += ["", f"_{DISCLAIMER} Parsed automatically; check every filing._"]
    (mem / f"brief_{today}.md").write_text("\n".join(brief))
    # draft posts (NOT posted)
    top = week[:3]
    x = f"Insider cluster buys, week to {today} (SEC Form 4, open-market only):\n" + "\n".join(f"${r['ticker'] or r['issuer'][:20]}: {r['insiderCount']} insiders, {money(r['totalValueUsd'])}" for r in top) + f"\nFull list + filings: {base}\n{DISCLAIMER}"
    (posts / f"x_{today}.txt").write_text(x)
    print(f"built {len(urls)} urls, {len(clusters)} cluster pages, {len(rows)} issuers; x draft {len(x)} chars")

if __name__ == "__main__": main()
