#!/usr/bin/env python3
"""Make every organization carry ONE (affiliation_type, affiliation_country)
across the whole index, by rewriting only the newest shards.

tests/validate.py builds organization_facts over every record in every shard and
fails when one organization string carries two different (type, country) pairs.
Records curated independently cannot satisfy that by construction: the constraint
is global and each judgment was local. This resolves the disagreements.

Shards numbered below FIRST_EDITABLE are AUTHORITATIVE and are never written.
They were validating cleanly before the new shards arrived, so each organization
they mention already has exactly one fact; adopting it means no committed shard
has to change and no correction shard is needed. An organization that appears
only in the new shards is settled by majority vote, with the tie-breaks below.

Three passes, in order, over the editable shards only:
  1. PLACEHOLDERS  drop role descriptors that are not places at all
  2. ALIASES       fold an organization into the name the index already uses
  3. the vote      one (type, country) per surviving organization

The votes are gathered BEFORE passes 1 and 2 and then folded, because a stripped
or aliased organization changes the record's organization sequence: counting
afterwards would lose the evidence of any record whose facet lists no longer
line up with it, and that record would then keep stale lists of the wrong
length. That is a real bug this script shipped with once.

Dry run by default: prints everything it would change, writes nothing.
Pass --write to rewrite the shards.

    python3 curate/canonicalize_affiliations.py            # dry run
    python3 curate/canonicalize_affiliations.py --write
"""
import json, os, re, sys, glob, collections

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if not os.path.isdir(os.path.join(ROOT, "data", "shards")):
    ROOT = os.getcwd()
SHARD_DIR = os.path.join(ROOT, "data", "shards")
FIRST_EDITABLE = 124

# His standing ruling: "Don't put the independent researcher, community
# contributor type things as the affiliation. No affiliations if there is no
# explicit brick-and-mortar type place." A role descriptor is not an
# organization, so it is removed rather than given a type and a country. The
# author slot survives as an explicit null, which is a real answer.
PLACEHOLDERS = {
    "independent", "independent researcher", "independent scholar",
    "independent contributor", "individual researcher", "individual",
    "community contributor", "open source contributor", "freelance",
    "freelancer", "self-employed", "unaffiliated", "none", "n/a", "na",
    "not affiliated", "no affiliation",
}

# Organizations the index already knows under another name. Applied to the
# affiliation string itself, so the entry joins the existing organization
# rather than sitting beside it in the facet list.
ALIASES = {
    # [stated] 2026-08-21: "MIT Lincoln labs can use just MIT."
    "MIT Lincoln Laboratory": "Massachusetts Institute of Technology",
    "Lincoln Laboratory": "Massachusetts Institute of Technology",
}

# Country spellings that name the same place. The PREFERRED member is not the
# one listed first -- it is whichever spelling the authoritative shards already
# use most, computed at run time, so this script follows the index rather than
# imposing a taste on it. The first member is only the fallback when the
# authoritative shards use none of them.
#
# Hong Kong is deliberately NOT grouped with China: the site's region table
# carries Hong Kong as its own country value, and collapsing it would make
# that work harder to find rather than easier.
SYNONYM_GROUPS = [
    ["United States", "United States of America", "USA", "U.S.A.", "US"],
    ["South Korea", "Republic of Korea", "Korea, Republic of", "Korea"],
    ["Turkey", "Turkiye"],
    ["United Kingdom", "UK", "Great Britain"],
    ["Netherlands", "The Netherlands"],
    ["China", "People's Republic of China", "PR China"],
    ["Russia", "Russian Federation"],
    ["Vietnam", "Viet Nam"],
    ["Czechia", "Czech Republic"],
    ["Iran", "Islamic Republic of Iran"],
    ["Taiwan", "Taiwan, Province of China"],
    ["United Arab Emirates", "UAE"],
]

# Tie-breaks for a type vote that comes out level, applied to the organization
# NAME, first match winning. The project's existing convention
# (affiliation_facets.MANUAL_TYPES, the DFKI precedent) is that a hospital or a
# research institute is nonprofit even when it is attached to a university --
# hence a bare "Institut" falls to nonprofit while "Institute of Technology" is
# caught by the academic line above it. Every use is reported.
NAME_HINTS = [
    (r"(?i)hospital|klinik|klinikum|medical cent|health system|\bclinic\b", "nonprofit"),
    (r"(?i)ministry|national institute of|agency|administration", "government"),
    (r"(?i)universit|college|\bschool\b|academy|polytechnic|institute of technology",
     "academic"),
    (r"(?i)research cent|\binstitut|foundation|laborator|\btrust\b", "nonprofit"),
    (r"(?i)\binc\b|\bltd\b|\bllc\b|\bgmbh\b|\bcorp|technologies|\bAG\b|\bplc\b",
     "corporate"),
]

# Explicit calls that no vote should decide. Organization -> (type, country).
# Each of these was a reported coin flip on an earlier run, answered rather than
# left to alphabetical order.
MANUAL = {
    # SAS Institute is Cary, North Carolina; the UK vote is a subsidiary office.
    "SAS": ("corporate", "United States"),
    # Finnish. NEITHER recorded vote was right, so only this table can fix it.
    "Nokia": ("corporate", "Finland"),
    # The other three Hong Kong universities all resolve to Hong Kong.
    "City University of Hong Kong": ("academic", "Hong Kong"),
    # A UK charity; the hospital / research-institute convention says nonprofit.
    "The Institute of Cancer Research": ("nonprofit", "United Kingdom"),
    # A Portuguese non-profit research institute, not a company.
    "INESC-ID": ("nonprofit", "Portugal"),
    # Headquarters, not the campus or office the author sat in. Both were tied
    # votes that alphabetical order happened to get right; pinned so a later
    # batch cannot tip them the other way.
    "Manipal Academy of Higher Education": ("academic", "India"),
    "German Research Center for Artificial Intelligence (DFKI)": ("nonprofit", "Germany"),
}

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


def shard_number(path):
    m = re.match(r"(\d+)-", os.path.basename(path))
    return int(m.group(1)) if m else None


def detect_indent(path):
    """Preserve the file's own indent rather than reflowing it."""
    with open(path, encoding="utf-8") as fh:
        fh.readline()
        second = fh.readline()
    return 2 if second.startswith("  ") and not second.startswith("   ") else 1


def facts_of(records):
    """organization -> Counter of (type, country) pairs actually written."""
    facts = collections.defaultdict(collections.Counter)
    for rec in records:
        if rec.get("override"):
            continue
        orgs = organizations_of(rec)
        types = rec.get("affiliation_types") or []
        countries = rec.get("affiliation_countries") or []
        if len(types) != len(orgs) or len(countries) != len(orgs):
            continue
        for org, t, c in zip(orgs, types, countries):
            facts[org][(t, c)] += 1
    return facts


def clean_affiliations(rec):
    """Strip placeholders and apply aliases in the affiliations strings.

    Returns a list of (kind, detail) describing what changed. The author slot is
    kept -- nulled when nothing survives -- because tests/validate.py requires
    one affiliation entry per author. The facet lists are re-aligned BY NAME to
    the surviving organizations, so the record never leaves this function with
    lists of the wrong length.
    """
    changes = []
    affiliations = rec.get("affiliations")
    if not isinstance(affiliations, list):
        return changes
    before = organizations_of(rec)
    types = list(rec.get("affiliation_types") or [])
    countries = list(rec.get("affiliation_countries") or [])
    aligned = len(types) == len(before) and len(countries) == len(before)
    known = dict(zip(before, zip(types, countries))) if aligned else {}

    out = []
    for affiliation in affiliations:
        if not affiliation:
            out.append(affiliation)
            continue
        kept = []
        for org in (part.strip() for part in str(affiliation).split(";")):
            if not org:
                continue
            if org.casefold().strip(".") in PLACEHOLDERS:
                changes.append(("placeholder", org))
                continue
            alias = ALIASES.get(org)
            if alias:
                changes.append(("alias", f"{org} -> {alias}"))
                if org in known and alias not in known:
                    known[alias] = known[org]
                org = alias
            if org not in kept:
                kept.append(org)
        out.append("; ".join(kept) if kept else None)
    if not changes:
        return changes
    rec["affiliations"] = out
    after = organizations_of(rec)
    if aligned:
        pairs = [known.get(org, ("unknown", "unknown")) for org in after]
        rec["affiliation_types"] = [p[0] for p in pairs]
        rec["affiliation_countries"] = [p[1] for p in pairs]
    return changes


def main():
    write = "--write" in sys.argv

    old_records, new_records, new_files = [], [], []
    for path in sorted(glob.glob(os.path.join(SHARD_DIR, "*.json"))):
        num = shard_number(path)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if num is not None and num >= FIRST_EDITABLE:
            new_files.append((path, data))
            new_records.extend(data)
        else:
            old_records.extend(data)
    if not new_files:
        sys.exit(f"no shards numbered {FIRST_EDITABLE} or above under {SHARD_DIR}")
    print(f"{len(old_records)} authoritative records, "
          f"{len(new_records)} records in {len(new_files)} editable shards")

    # Votes first, while every record's facet lists still line up with its own
    # organization sequence. Placeholders are dropped and aliases folded here
    # rather than being counted under a name that will not survive.
    raw_facts = facts_of(new_records)
    new_facts = collections.defaultdict(collections.Counter)
    for org, counter in raw_facts.items():
        if org.casefold().strip(".") in PLACEHOLDERS:
            continue
        new_facts[ALIASES.get(org, org)].update(counter)

    # --- pass 1 and 2: placeholders and aliases ------------------------------
    string_changes = collections.Counter()
    for rec in new_records:
        if rec.get("override"):
            continue
        for kind, detail in clean_affiliations(rec):
            string_changes[f"{kind}: {detail}"] += 1
    if string_changes:
        print(f"\naffiliation strings rewritten ({sum(string_changes.values())} slots):")
        for text, n in string_changes.most_common():
            print(f"    {n:5d}  {text}")

    old_facts = facts_of(old_records)

    # --- preferred country spelling, learned from the authoritative shards ---
    old_country_use = collections.Counter()
    for counter in old_facts.values():
        for (_, country), n in counter.items():
            old_country_use[country] += n
    preferred = {}
    for group in SYNONYM_GROUPS:
        best = max(group, key=lambda name: (old_country_use.get(name, 0), -group.index(name)))
        for name in group:
            preferred[name.casefold()] = best
    shown = {g[0]: preferred[g[0].casefold()] for g in SYNONYM_GROUPS
             if preferred[g[0].casefold()] != g[0]}
    if shown:
        print("\ncountry spellings the index prefers:",
              ", ".join(f"{k} -> {v}" for k, v in sorted(shown.items())))

    def canon_country(value):
        return preferred.get(str(value or "").casefold(), value)

    # --- pass 3: one authoritative fact per organization --------------------
    authority, coinflips, hinted = {}, [], []
    for org in set(old_facts) | set(new_facts):
        if org in MANUAL:
            authority[org] = MANUAL[org]
            continue
        if org in old_facts:
            # Authoritative shards validated clean, so there is exactly one.
            authority[org] = old_facts[org].most_common(1)[0][0]
            continue
        votes = new_facts[org]

        countries = collections.Counter()
        for (_, country), n in votes.items():
            countries[canon_country(country)] += n
        real = {c: n for c, n in countries.items() if c and c != "unknown"}
        pool = real or countries
        top = max(pool.values())
        winners = sorted(c for c, n in pool.items() if n == top)
        country = winners[0]
        if len(winners) > 1:
            coinflips.append(f"{org}: country {winners} -> {country}")

        types = collections.Counter()
        for (t, _), n in votes.items():
            types[t if t in VALID_TYPES else "other"] += n
        top = max(types.values())
        winners = sorted(t for t, n in types.items() if n == top)
        otype = winners[0]
        if len(winners) > 1:
            hint = next((v for pat, v in NAME_HINTS if re.search(pat, org)), None)
            if hint and hint in winners:
                otype = hint
                hinted.append(f"{org}: type {winners} -> {otype} by name")
            else:
                coinflips.append(f"{org}: type {winners} -> {otype}")
        authority[org] = (otype, country)

    print(f"\norganizations: {len(authority)} total")

    # --- rewrite the editable shards ----------------------------------------
    changed_records, changed_slots, orphans = 0, 0, []
    changes = collections.Counter()
    for path, data in new_files:
        for rec in data:
            if rec.get("override"):
                continue
            orgs = organizations_of(rec)
            types = list(rec.get("affiliation_types") or [])
            countries = list(rec.get("affiliation_countries") or [])
            want = [authority.get(org) for org in orgs]
            missing = [org for org, w in zip(orgs, want) if w is None]
            if missing:
                orphans.append(f"{rec.get('id')}: {missing}")
                continue
            new_types = [w[0] for w in want]
            new_countries = [w[1] for w in want]
            if new_types == types and new_countries == countries:
                continue
            for i, org in enumerate(orgs):
                before = (types[i], countries[i]) if i < len(types) and i < len(countries) else None
                if before != want[i]:
                    changes[f"{org}: {before} -> {want[i]}"] += 1
                    changed_slots += 1
            rec["affiliation_types"] = new_types
            rec["affiliation_countries"] = new_countries
            changed_records += 1

    if changes:
        print(f"\n{len(changes)} organization-level changes, "
              f"{changed_slots} slots in {changed_records} records:")
        for text, n in changes.most_common():
            print(f"    {n:5d}  {text}")
    else:
        print("\nnothing to change")

    if orphans:
        print(f"\nORGANIZATIONS WITH NO FACT AT ALL ({len(orphans)}) -- records skipped, "
              f"which leaves their facet lists as they were:")
        for text in orphans[:20]:
            print("    " + text)

    if hinted:
        print(f"\ntype decided by a name hint ({len(hinted)}):")
        for text in hinted:
            print("    " + text)
    if coinflips:
        print(f"\nCOIN FLIPS -- alphabetical order decided these ({len(coinflips)}). "
              f"Put the real answers in MANUAL and re-run:")
        for text in coinflips:
            print("    " + text)
    else:
        print("\nno coin flips: every organization was settled by evidence or by MANUAL")

    # --- verify: alignment, and no organization carrying two facts ----------
    problems = []
    for rec in old_records + new_records:
        if rec.get("override"):
            continue
        n = len(organizations_of(rec))
        if len(rec.get("affiliation_types") or []) != n or \
                len(rec.get("affiliation_countries") or []) != n:
            problems.append(f"{rec.get('id')}: facet lists do not match {n} organizations")
    residue = {org: dict(c) for org, c in facts_of(old_records + new_records).items()
               if len(c) > 1}
    for org, c in sorted(residue.items()):
        problems.append(f"{org}: still carries {sorted(c)}")
    if problems:
        print(f"\nPROBLEMS ({len(problems)}) -- nothing written:")
        for text in problems[:40]:
            print("    " + text)
        sys.exit(1)
    print("\nverified: every record aligned, every organization one (type, country)")

    if not write:
        print("\nDRY RUN -- nothing written. Re-run with --write to apply.")
        return

    for path, data in new_files:
        indent = detect_indent(path)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=indent, ensure_ascii=False)
            fh.write("\n")
        print(f"rewrote {os.path.basename(path)}")
    print("\nnow run:  python3 tests/validate.py && python3 build.py --write")


if __name__ == "__main__":
    main()
