#!/usr/bin/env python3
"""Merge the auto-curated PAPER staging records in curate/paper-shards/records/
into numbered production shards under data/shards/.

Sibling of merge_auto_shards.py, which serves the repo lane and keys every
exclusion on a GitHub repo slug. Papers are keyed on DOI and url instead, and
that script's Q2 drop lists and field corrections are repo-specific and absent
here.

His 2026-08-21 ruling: a preprint and its published version may BOTH be in the
index, so there is no preprint/published sweep and nothing gates on one.
Exclusion is exact url or DOI only, plus the never-readd list.

Dry run by default: prints the shard layout and every exclusion, writes nothing.
Pass --write to create the shard files.

Run from the repo root:
    python3 curate/merge_paper_shards.py            # dry run
    python3 curate/merge_paper_shards.py --write    # write the shards
"""
import json, os, re, sys, glob, collections

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if not os.path.isdir(os.path.join(ROOT, "data", "shards")):
    ROOT = os.getcwd()
REC_DIR = os.path.join(ROOT, "curate", "paper-shards", "records")
SHARD_DIR = os.path.join(ROOT, "data", "shards")
FIRST_SHARD = 124
PER_SHARD = 120
SHARD_STEM = "auto-paper-tail"

VALID_TYPES = {"academic", "corporate", "government", "nonprofit", "other", "unknown"}

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+")


def doi_of(rec):
    """Lowercased bare DOI, from the record's doi field or out of its url."""
    raw = (rec.get("doi") or "").strip().lower()
    if not raw:
        m = DOI_RE.search((rec.get("url") or "").lower())
        raw = m.group(0) if m else ""
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        raw = raw.removeprefix(prefix)
    return raw.rstrip("/").strip()


def organizations_of(rec):
    """Deduped ;-split organization sequence, exactly as tests/validate.py counts it."""
    out, seen = [], set()
    for affiliation in rec.get("affiliations") or []:
        if not affiliation:
            continue
        for org in (part.strip() for part in affiliation.split(";")):
            if org and org not in seen:
                seen.add(org)
                out.append(org)
    return out


def normalize_affiliations(rec):
    """Align affiliation_types/countries to the ORGANIZATION sequence.

    On this lane it should be a NO-OP: paper_curate.py already enforces exact
    equality before a record reaches records/. It is kept as a safety net, and
    anything it changes is PRINTED -- if it fires at all, something upstream is
    wrong and the dry run is the place to notice.
    """
    orgs = organizations_of(rec)
    types = list(rec.get("affiliation_types") or [])
    countries = list(rec.get("affiliation_countries") or [])
    if len(types) == len(orgs) and len(countries) == len(orgs):
        return None
    if not orgs:
        rec["affiliation_types"], rec["affiliation_countries"] = [], []
        return "cleared empty affiliation trio"

    def spread(values, fallback):
        distinct = {v for v in values if isinstance(v, str) and v.strip()}
        if len(distinct) == 1:
            return [distinct.pop()] * len(orgs)
        if not distinct:
            return [fallback] * len(orgs)
        return None

    new_types = spread(types, "unknown")
    new_countries = spread(countries, "unknown")
    if new_types is None or new_countries is None:
        rec["affiliations"] = [None] * len(rec.get("authors") or [])
        rec["affiliation_types"], rec["affiliation_countries"] = [], []
        return "blanked: per-organization values could not be derived"
    rec["affiliation_types"] = [t if t in VALID_TYPES else "other" for t in new_types]
    rec["affiliation_countries"] = new_countries
    return f"aligned to {len(orgs)} organization(s)"


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    write = "--write" in sys.argv

    files = sorted(glob.glob(os.path.join(REC_DIR, "*.json")))
    if not files:
        sys.exit(f"no records found under {REC_DIR}")
    records = []
    for path in files:
        with open(path, encoding="utf-8") as fh:
            records.append(json.load(fh))
    print(f"loaded {len(records)} staging records")

    # --- exclusions -------------------------------------------------------
    # Read the SHARDS, not the built index. An entry retired by a correction
    # (duplicate_of) is absent from data/sdv-index.json while its id, url and
    # DOI are still owned by a shard, and re-adding it collides.
    #
    # Every shard counts, INCLUDING the ones this script wrote on a previous
    # run. To redo a merge, delete its shards first.
    shard_urls, shard_ids, shard_dois = set(), set(), set()
    for path in sorted(glob.glob(os.path.join(SHARD_DIR, "*.json"))):
        for rec in load_json(path, []):
            if rec.get("id"):
                shard_ids.add(rec["id"])
            url = (rec.get("url") or "").lower().rstrip("/")
            if url:
                shard_urls.add(url)
            doi = doi_of(rec)
            if doi:
                shard_dois.add(doi)

    never = load_json(os.path.join(ROOT, "curate", "never-readd.json"), {}) or {}
    never_dois = {d.strip().lower() for d in (never.get("dois") or []) if d}

    kept, excluded = [], collections.defaultdict(list)
    for rec in records:
        url = (rec.get("url") or "").lower().rstrip("/")
        doi = doi_of(rec)
        if (url and url in shard_urls) or (doi and doi in shard_dois):
            excluded["already in the index"].append(doi or url)
        elif doi and doi in never_dois:
            excluded["on the never-readd list"].append(doi)
        else:
            kept.append(rec)

    for reason, items in sorted(excluded.items()):
        print(f"\nexcluded, {reason}: {len(items)}")
        for it in sorted(items)[:40]:
            print(f"    {it}")
        if len(items) > 40:
            print(f"    ... and {len(items) - 40} more")

    # --- affiliation safety net -------------------------------------------
    notes = collections.Counter()
    changed = []
    for rec in kept:
        note = normalize_affiliations(rec)
        if note:
            notes[note.split(" to ")[0]] += 1
            changed.append((rec.get("id"), note))
    if changed:
        print(f"\nAFFILIATION TRIOS NORMALIZED: {len(changed)} -- expected 0 on this lane")
        for k, v in notes.most_common():
            print(f"    {v:4d}  {k}")
        for rid, note in changed[:10]:
            print(f"    e.g. {rid}: {note}")
    else:
        print("\naffiliation trios: already aligned, nothing changed")

    # --- integrity checks before writing ----------------------------------
    problems = []
    ids = collections.Counter(r.get("id") for r in kept)
    for rid, n in ids.items():
        if n > 1:
            problems.append(f"duplicate id within the merge set: {rid} x{n}")
        if rid in shard_ids:
            problems.append(f"id already used in the index: {rid}")
    urls = collections.Counter((r.get("url") or "").lower().rstrip("/") for r in kept)
    for u, n in urls.items():
        if n > 1:
            problems.append(f"duplicate url within the merge set: {u} x{n}")
    dois = collections.Counter(d for d in (doi_of(r) for r in kept) if d)
    for d, n in dois.items():
        if n > 1:
            problems.append(f"duplicate doi within the merge set: {d} x{n}")
    for r in kept:
        if not r.get("summary") or not r.get("title"):
            problems.append(f"record missing title or summary: {r.get('id')}")
        if not r.get("sdv_component"):
            problems.append(f"empty sdv_component: {r.get('id')}")
        if r.get("integration") == "unclear" and r.get("confidence") == "high":
            problems.append(f"unclear with confidence high: {r.get('id')}")
    if problems:
        print(f"\nINTEGRITY PROBLEMS ({len(problems)}) -- nothing written:")
        for p in problems[:50]:
            print("   ", p)
        if len(problems) > 50:
            print(f"    ... and {len(problems) - 50} more")
        sys.exit(1)
    print("integrity checks: clean")

    # --- shard layout -----------------------------------------------------
    taken = set()
    for path in glob.glob(os.path.join(SHARD_DIR, "*.json")):
        m = re.match(r"(\d+)-", os.path.basename(path))
        if m:
            taken.add(int(m.group(1)))
    kept.sort(key=lambda r: r["id"])
    chunks = [kept[i:i + PER_SHARD] for i in range(0, len(kept), PER_SHARD)]
    if len(chunks) > 26:
        sys.exit(f"{len(chunks)} chunks exceeds the a-z suffix; raise PER_SHARD")

    num, plan = FIRST_SHARD, []
    for i, chunk in enumerate(chunks):
        while num in taken:
            num += 1
        plan.append((num, f"{num:03d}-{SHARD_STEM}-{chr(ord('a') + i)}.json", chunk))
        taken.add(num)

    print(f"\n{len(kept)} records -> {len(plan)} shards")
    for num, name, chunk in plan:
        print(f"    {name:34s} {len(chunk):4d} records   {chunk[0]['id']} .. {chunk[-1]['id']}")

    def spread_of(key):
        return dict(collections.Counter(r.get(key) for r in kept).most_common())

    print("\nkind spread       :", spread_of("kind"))
    print("integration spread:", spread_of("integration"))
    print("importance spread :", dict(sorted(collections.Counter(r.get("importance") for r in kept).items())))
    print("evidence tier     :", spread_of("evidence_tier"))
    print("confidence        :", spread_of("confidence"))
    print("carrying a needs  :", sum(1 for r in kept if r.get("needs")))

    if not write:
        print("\nDRY RUN -- nothing written. Re-run with --write to create these shards.")
        return

    for num, name, chunk in plan:
        path = os.path.join(SHARD_DIR, name)
        if os.path.exists(path):
            sys.exit(f"refusing to overwrite existing shard {path}")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(chunk, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        print(f"wrote {path} ({os.path.getsize(path)} bytes)")
    print("\nnow run:  python3 tests/validate.py && python3 build.py --write")


if __name__ == "__main__":
    main()
