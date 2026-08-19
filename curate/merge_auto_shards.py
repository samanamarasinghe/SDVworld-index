#!/usr/bin/env python3
"""Merge the auto-curated staging records in curate/auto-shards/records/ into
numbered production shards under data/shards/.

Dry run by default: prints the shard layout and every exclusion, writes nothing.
Pass --write to create the shard files.

Run from the repo root:
    python3 merge_auto_shards.py            # dry run
    python3 merge_auto_shards.py --write    # write the shards
"""
import json, os, re, sys, glob, collections

ROOT = os.path.abspath(os.path.dirname(__file__))
if not os.path.isdir(os.path.join(ROOT, "data", "shards")):
    ROOT = os.getcwd()
REC_DIR = os.path.join(ROOT, "curate", "auto-shards", "records")
SHARD_DIR = os.path.join(ROOT, "data", "shards")
FIRST_SHARD = 108
PER_SHARD = 120

# Same-project copies that lost the Q2 test (more commits + more contributors wins).
# Resolved 2026-08-19. Losers to an already-indexed entry, and losers inside the batch.
DROP_LOST_TO_INDEX = [
    "Shreeja7Sheth/Causal-TGAN", "InfintyLab/CausalTGAN",
    "sunnyboy33/FSI_AIxData_Challenge", "scnelMG/FSI-AIxData-Challenge-2024",
    "SPAI-Lab/FSI_AIxData_Challenge_2024", "stvflowers/CosmosAIGraph",
    "nju-lands/ShadowAQP", "kristian10007/NextConvGeN", "dfatpnuk/katabatic",
    "ECaricato/data-synthesizer", "MalwareDataLab/Maldatagen_additional_metrics",
    "nicktom1034/Machine-Learning-Engineering-AWS-developer",
]
DROP_LOST_IN_BATCH = [
    "mohitsarin-tamu/Gradvisor", "ananthy123/Chubb-Churns-25",
    "Ajzboss/145FinalCheckpoint2", "gfin5/CS145Project", "morganmason0606/CS145-RecSys",
    "BrejeshKoushal/MimicData", "Syed-Saadan-Uddin/Flight-Tracking-Pipeline",
    "Mahajanashok2456/IntrusionDetectionSystem", "cybermuhdupa/ai-engineering-hub",
    "PrakharSinghDev/AI-Projects-00", "surajc-15/major_project",
    "AdrianRaposo/TFM_Bayesian_Network_Agentic_RAG", "TanZeus/AnomalyDetection",
    "0xSushmitha/Fraud-detection-in-financial-Transactions",
]
# NOT dropped, awaiting his ruling: steveng9/MIA_on_diffusion, PRAVEENM282/DataSynth,
# Kishankumar1328/SYNTHESIS (Q2 points at retiring an indexed entry), and
# swordsbird/RuleExplorer + Athar04-Stela/skripsi-sample (shared README is boilerplate).

# Field corrections found in the audit. repo -> {field: value}
CORRECTIONS = {
    "tarikibrahimovic/Diabetes-Prediction": {"sdv_component": ["sdv"]},
}

GH = re.compile(r"https?://(?:www\.)?github\.com/([^/#?]+)/([^/#?]+)")

VALID_TYPES = {"academic", "corporate", "government", "nonprofit", "other", "unknown"}


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

    The model emitted one value per affiliation STRING; the schema wants one per
    distinct organization, and a string may name several. Replicate when the
    record carries a single distinct value, since that is what it meant. When the
    values genuinely disagree and cannot be mapped, blank the affiliations rather
    than guess -- authors are kept, so the record stays valid and simply carries
    no affiliation. Returns a short note when it changed something.
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
        authors = rec.get("authors") or []
        rec["affiliations"] = [None] * len(authors)
        rec["affiliation_types"], rec["affiliation_countries"] = [], []
        return "blanked: per-organization values could not be derived"
    bad = [t for t in new_types if t not in VALID_TYPES]
    if bad:
        new_types = ["other" if t not in VALID_TYPES else t for t in new_types]
    rec["affiliation_types"] = new_types
    rec["affiliation_countries"] = new_countries
    return f"aligned to {len(orgs)} organization(s)"


def repo_of(url):
    m = GH.match(url or "")
    return f"{m.group(1)}/{m.group(2)}".removesuffix(".git") if m else None


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
    # (duplicate_of) is absent from data/sdv-index.json but its id and url are
    # still owned by a shard, and re-adding it collides. frhrdr/dp-merf is
    # exactly this case: retired in shard 041 by the Q2 ruling for ParkLabML.
    shard_urls, shard_ids, retired = set(), set(), {}
    for path in sorted(glob.glob(os.path.join(SHARD_DIR, "*.json"))):
        if re.search(r"auto-repo-tail", os.path.basename(path)):
            continue
        for rec in load_json(path, []):
            if rec.get("id"):
                shard_ids.add(rec["id"])
            url = (rec.get("url") or "").lower().rstrip("/")
            if url:
                shard_urls.add(url)
            if rec.get("duplicate_of"):
                retired[rec["id"]] = rec["duplicate_of"]
    indexed_urls = shard_urls
    indexed_repos_lc = {r.lower() for r in (repo_of(u) for u in shard_urls) if r}
    indexed_ids = shard_ids

    never = load_json(os.path.join(ROOT, "curate", "never-readd.json"), {}) or {}
    never_repos = {r.lower() for r in (never.get("repos") or [])}

    drop_q2 = {r.lower() for r in DROP_LOST_TO_INDEX + DROP_LOST_IN_BATCH}

    kept, excluded = [], collections.defaultdict(list)
    for rec in records:
        repo = (repo_of(rec.get("url")) or "").lower()
        url = (rec.get("url") or "").lower().rstrip("/")
        if url in indexed_urls or repo in indexed_repos_lc:
            excluded["already in the index"].append(repo or url)
        elif repo in never_repos:
            excluded["on the never-readd list"].append(repo)
        elif repo in drop_q2:
            excluded["lost the Q2 duplicate test"].append(repo)
        else:
            kept.append(rec)

    for reason, items in sorted(excluded.items()):
        print(f"\nexcluded, {reason}: {len(items)}")
        for it in sorted(items)[:40]:
            print(f"    {it}")
        if len(items) > 40:
            print(f"    ... and {len(items) - 40} more")

    # --- corrections ------------------------------------------------------
    applied = 0
    for rec in kept:
        fix = CORRECTIONS.get(repo_of(rec.get("url")) or "")
        if fix:
            rec.update(fix)
            applied += 1
    print(f"\nfield corrections applied: {applied} of {len(CORRECTIONS)}")

    notes = collections.Counter()
    changed = []
    for rec in kept:
        note = normalize_affiliations(rec)
        if note:
            notes[note.split(" to ")[0]] += 1
            changed.append((rec["id"], note))
    if changed:
        print(f"affiliation trios normalized: {len(changed)}")
        for k, v in notes.most_common():
            print(f"    {v:4d}  {k}")
        for rid, note in changed[:10]:
            print(f"    e.g. {rid}: {note}")

    # --- integrity checks before writing ----------------------------------
    problems = []
    ids = collections.Counter(r["id"] for r in kept)
    for rid, n in ids.items():
        if n > 1:
            problems.append(f"duplicate id within the merge set: {rid} x{n}")
        if rid in indexed_ids:
            problems.append(f"id already used in the index: {rid}")
    urls = collections.Counter((r.get("url") or "").lower().rstrip("/") for r in kept)
    for u, n in urls.items():
        if n > 1:
            problems.append(f"duplicate url within the merge set: {u} x{n}")
    for r in kept:
        if not r.get("summary") or not r.get("title"):
            problems.append(f"record missing title or summary: {r.get('id')}")
        if r.get("integration") != "name_collision" and not r.get("sdv_component"):
            problems.append(f"empty sdv_component: {r.get('id')}")
        if r.get("integration") == "unclear" and r.get("confidence") == "high":
            problems.append(f"unclear with confidence high: {r.get('id')}")
    if problems:
        print("\nINTEGRITY PROBLEMS — nothing written:")
        for p in problems[:50]:
            print("   ", p)
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

    num, plan = FIRST_SHARD, []
    for i, chunk in enumerate(chunks):
        while num in taken:
            num += 1
        plan.append((num, f"{num:03d}-auto-repo-tail-{chr(ord('a') + i)}.json", chunk))
        taken.add(num)

    print(f"\n{len(kept)} records -> {len(plan)} shards")
    for num, name, chunk in plan:
        print(f"    {name:34s} {len(chunk):4d} records   {chunk[0]['id']} .. {chunk[-1]['id']}")

    spread = collections.Counter(r["integration"] for r in kept)
    print("\nintegration spread:", dict(spread.most_common()))
    print("importance spread :", dict(sorted(collections.Counter(r["importance"] for r in kept).items())))
    print("carrying a needs  :", sum(1 for r in kept if r.get("needs")))

    if not write:
        print("\nDRY RUN — nothing written. Re-run with --write to create these shards.")
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
