#!/usr/bin/env python3
"""Backfill sdv_component values the auto-curation missed.

The model recorded the synthesizer import and often missed a second SDV-family
import in the same file -- most commonly sdmetrics, read a few lines after the
synthesizer. This finds those and emits a correction shard.

An import counts only when all three hold:
  1. it is on the HIT LINE itself, not in the surrounding context, because a
     hit's context carries whatever else that file imports nearby;
  2. it is not commented out;
  3. it is not inside a vendored or package tree. A vendored ctgan copy imports
     rdt internally, which is ctgan's dependency, not this repo's component.

Dry run by default. Run from the repo root:
    python3 curate/component_backfill.py            # dry run
    python3 curate/component_backfill.py --write    # write the shard
"""
import json, os, re, sys, glob, collections

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if not os.path.isdir(os.path.join(ROOT, "data", "shards")):
    ROOT = os.getcwd()
REC_DIR = os.path.join(ROOT, "curate", "auto-shards", "records")
EVIDENCE_DIR = os.path.join(ROOT, "harvest", "evidence")
OUT = os.path.join(ROOT, "data", "shards", "121-component-backfill.json")

PACKAGES = ["ctgan", "rdt", "copulas", "sdmetrics", "sdgym", "deepecho", "sdv"]
IMPORTS = {p: re.compile(r'(?:^|["\s(])(?:import\s+%s\b|from\s+%s(?:\.[\w.]+)?\s+import)' % (p, p))
           for p in PACKAGES}
STATEMENT = {p: re.compile(r'(?:import\s+%s\b|from\s+%s(?:\.[\w.]+)?\s+import)' % (p, p))
             for p in PACKAGES}
VENDOR_DIR = re.compile(
    r"(^|/)(site-packages|node_modules|third_party|thirdparty|vendor|vendored"
    r"|external|externals|baselines?|submodules?)(/|$)", re.I)


def commented_out(text, package):
    match = STATEMENT[package].search(text)
    return "#" in text[:match.start()] if match else True


def in_vendored_tree(path, package, vendored_dirs):
    lowered = path.lower()
    if VENDOR_DIR.search(lowered):
        return True
    if re.search(r"(^|/)%s/" % package, lowered):
        return True
    return any(("/" + lowered).find("/" + d + "/") >= 0 for d in vendored_dirs if d)


def main():
    write = "--write" in sys.argv

    records = {}
    for path in sorted(glob.glob(os.path.join(REC_DIR, "*.json"))):
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
        records[rec["url"].replace("https://github.com/", "")] = rec
    evidence = {}
    for path in glob.glob(os.path.join(EVIDENCE_DIR, "*.json")):
        with open(path, encoding="utf-8") as fh:
            item = json.load(fh)
        evidence[item["repo"]] = item

    index_path = os.path.join(ROOT, "data", "sdv-index.json")
    with open(index_path, encoding="utf-8") as fh:
        index = json.load(fh)
    live_ids = {entry["id"] for entry in index}

    additions, skipped = {}, collections.Counter()
    for repo, rec in records.items():
        if rec["id"] not in live_ids:
            skipped["not in the built index"] += 1
            continue
        if rec.get("integration") == "name_collision":
            continue
        item = evidence.get(repo) or {}
        vendored = [d.lower().rstrip("/") for d in (item.get("vendored_dirs") or [])]
        claimed = set(rec.get("sdv_component") or [])
        found = set()
        for hits in (item.get("hits") or {}).values():
            for hit in hits:
                text, path = hit.get("text") or "", hit.get("file") or ""
                for package in PACKAGES:
                    if package in claimed or not IMPORTS[package].search(text):
                        continue
                    if in_vendored_tree(path, package, vendored):
                        skipped["vendored or package tree"] += 1
                        continue
                    if commented_out(text, package):
                        skipped["commented out"] += 1
                        continue
                    found.add(package)
        if found:
            additions[repo] = (rec, sorted(claimed | found), sorted(found))

    print(f"{len(additions)} records would gain a component")
    print("  added:", dict(collections.Counter(
        p for _, _, gained in additions.values() for p in gained).most_common()))
    print("  hits skipped:", dict(skipped))
    for repo, (rec, merged, gained) in sorted(additions.items())[:10]:
        print(f"    {rec['id'][:44]:46s} +{gained} -> {merged}")
    if len(additions) > 10:
        print(f"    ... and {len(additions) - 10} more")

    shard = []
    for repo, (rec, merged, gained) in sorted(additions.items(), key=lambda kv: kv[1][0]["id"]):
        shard.append({
            "id": rec["id"],
            "override": True,
            "sdv_component": merged,
            "evidence": (
                f"sdv_component backfill: {', '.join(gained)} "
                f"{'is' if len(gained) == 1 else 'are'} imported in the repository's "
                f"own code and was missed at curation time."),
        })

    if not write:
        print("\nDRY RUN -- nothing written. Re-run with --write to create the shard.")
        return
    if os.path.exists(OUT):
        sys.exit(f"refusing to overwrite existing shard {OUT}")
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(shard, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"\nwrote {OUT} ({os.path.getsize(OUT)} bytes, {len(shard)} records)")
    print("now run:  python3 tests/validate.py && python3 build.py --write")


if __name__ == "__main__":
    main()
