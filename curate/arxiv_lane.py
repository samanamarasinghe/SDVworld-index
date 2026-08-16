#!/usr/bin/env python3
"""Deterministically slice the remaining influential-arXiv worklist for parallel curation.

Usage:  python curate/arxiv_lane.py           # show all slices
        python curate/arxiv_lane.py A         # show only slice A

Recomputes "remaining" from the repo on every run, so a slice shrinks as
other sessions push. Run it again before starting a batch.
"""
import glob, hashlib, json, re, sys

SLICES = ["A", "B", "C", "D"]
SHARD_RANGES = {"A": (63, 69), "B": (70, 76), "C": (77, 83), "D": (84, 90)}

def norm(s):
    return re.sub(r"\W+", "", (s or "")).lower()

def load_tail():
    """Tail records deduped on OpenAlex id.

    data/tail/openalex-citations.json has historically carried the same work
    twice (14 works as of 2026-08-16, 12 of them arXiv). A doubled record emitted two
    worklist rows for one paper, which is how three papers were curated twice
    during the parallel arXiv run. Dedupe on read so the defect in the stored
    file cannot produce duplicate work again.
    """
    seen, out = set(), []
    for r in json.load(open("data/tail/openalex-citations.json")):
        key = r.get("id") or r.get("doi") or norm(r.get("title"))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out

def slice_of(arxiv_id):
    """Assign a paper to a slice by a stable hash of its arXiv id.

    The original round-robin (work[i::4]) assigned by POSITION in the remaining
    list, so every shard that landed reshuffled the rest and a paper moved
    between slices mid-run. Two sessions could then be handed the same paper.
    Hashing the id keeps a paper in one slice for the life of the lane, however
    much of the list has been consumed.
    """
    h = hashlib.sha1(arxiv_id.encode()).hexdigest()
    return SLICES[int(h, 16) % len(SLICES)]

def remaining():
    tail = load_tail()
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
    for s in SLICES:
        mine = [r for r in work if slice_of(r["arxiv_id"]) == s]
        if want and s != want:
            continue
        lo, hi = SHARD_RANGES[s]
        print(f"=== SLICE {s} — {len(mine)} papers — shard numbers {lo}-{hi} ===")
        for r in mine:
            print(f"  {r['arxiv_id']:<12} {r.get('publication_year')}  {(r.get('title') or '')[:88]}")
        print()

if __name__ == "__main__":
    main()
