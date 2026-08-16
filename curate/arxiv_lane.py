#!/usr/bin/env python3
"""Deterministically slice the remaining influential-arXiv worklist for parallel curation.

Usage:  python curate/arxiv_lane.py           # show all slices
        python curate/arxiv_lane.py A         # show only slice A

Recomputes "remaining" from the repo on every run, so a slice shrinks as
other sessions push. Run it again before starting a batch.
"""
import glob, json, re, sys

SLICES = ["A", "B", "C", "D"]
SHARD_RANGES = {"A": (63, 69), "B": (70, 76), "C": (77, 83), "D": (84, 90)}

def norm(s):
    return re.sub(r"\W+", "", (s or "")).lower()

def remaining():
    tail = json.load(open("data/tail/openalex-citations.json"))
    shard = [r for f in glob.glob("data/shards/*.json") for r in json.load(open(f))]
    urls = {(r.get("url") or "").lower().rstrip("/") for r in shard}
    titles = {norm(r.get("title")) for r in shard}

    def done(r):
        for u in (r.get("doi"), (r.get("primary_location") or {}).get("landing_page_url")):
            if u and u.lower().rstrip("/") in urls:
                return True
        return norm(r.get("title")) in titles

    out = []
    for r in tail:
        doi = (r.get("doi") or "").lower()
        if not r.get("influential") or "10.48550/arxiv" not in doi or done(r):
            continue
        r["arxiv_id"] = re.search(r"arxiv\.(.+)$", doi, re.I).group(1)
        out.append(r)
    # stable order: arXiv id ascending, so slices are reproducible across sessions
    return sorted(out, key=lambda r: r["arxiv_id"])

def main():
    work = remaining()
    want = sys.argv[1].upper() if len(sys.argv) > 1 else None
    print(f"{len(work)} influential arXiv works remaining\n")
    for i, s in enumerate(SLICES):
        mine = work[i::len(SLICES)]        # round-robin: every slice stays balanced as the list shrinks
        if want and s != want:
            continue
        lo, hi = SHARD_RANGES[s]
        print(f"=== SLICE {s} — {len(mine)} papers — shard numbers {lo}-{hi} ===")
        for r in mine:
            print(f"  {r['arxiv_id']:<12} {r.get('publication_year')}  {(r.get('title') or '')[:88]}")
        print()

if __name__ == "__main__":
    main()
