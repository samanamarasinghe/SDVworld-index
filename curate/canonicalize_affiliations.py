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

Dry run by default: prints every organization it would change, writes nothing.
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

# Country spellings that name the same place. The PREFERRED member is not the
# one listed first -- it is whichever spelling the authoritative shards already
# use most, computed at run time, so this script follows the index rather than
# imposing a taste on it. The first member is only the fallback when the
# authoritative shards use none of them.
#
# Hong Kong is deliberately NOT grouped with China: the site's region table
# carries Hong Kong as its own country value, and collapsing it would make
# African and Asian work harder to find rather than easier.
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
# NAME. The project's existing convention (affiliation_facets.MANUAL_TYPES, the
# DFKI precedent) is that a hospital or a research centre is nonprofit even when
# it is attached to a university. Every use is reported.
NAME_HINTS = [
    (r"(?i)hospital|klinik|klinikum|medical cent|health system|\bclinic\b", "nonprofit"),
    (r"(?i)ministry|national institute of|agency|administration", "government"),
    (r"(?i)universit|college|\bschool\b|academy|polytechnic|\bETH\b|\bKAIST\b", "academic"),
    (r"(?i)research cent|research institute|foundation|laborator", "nonprofit"),
    (r"(?i)\binc\b|\bltd\b|\bllc\b|\bgmbh\b|\bcorp|technologies|\bAG\b|\bplc\b", "corporate"),
]

# Explicit calls that no vote should decide. Organization -> (type, country).
# Seeded empty on purpose: run the dry run first, read what it reports as a
# coin-flip, and put the answers here rather than letting alphabetical order
# decide something that matters.
MANUAL = {}

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

    old_facts = facts_of(old_records)
    new_facts = facts_of(new_records)

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
        print("country spellings the index prefers:",
              ", ".join(f"{k} -> {v}" for k, v in sorted(shown.items())))

    def canon_country(value):
        return preferred.get(str(value or "").casefold(), value)

    # --- one authoritative fact per organization ----------------------------
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

    conflicted = sorted(org for org in set(old_facts) | set(new_facts)
                        if len(old_facts.get(org, {})) + len(new_facts.get(org, {})) > 1
                        or len(set(old_facts.get(org, {})) | set(new_facts.get(org, {}))) > 1)
    print(f"\norganizations: {len(authority)} total, {len(conflicted)} carried more "
          f"than one fact")

    # --- rewrite the editable shards ----------------------------------------
    changed_records, changed_slots = 0, 0
    changes = collections.Counter()
    for path, data in new_files:
        for rec in data:
            if rec.get("override"):
                continue
            orgs = organizations_of(rec)
            types = rec.get("affiliation_types") or []
            countries = rec.get("affiliation_countries") or []
            if len(types) != len(orgs) or len(countries) != len(orgs):
                continue
            touched = False
            for i, org in enumerate(orgs):
                want = authority.get(org)
                if not want:
                    continue
                if (types[i], countries[i]) != want:
                    changes[f"{org}: {(types[i], countries[i])} -> {want}"] += 1
                    types[i], countries[i] = want
                    changed_slots += 1
                    touched = True
            if touched:
                rec["affiliation_types"] = types
                rec["affiliation_countries"] = countries
                changed_records += 1

    if changes:
        print(f"\n{len(changes)} organization-level changes, "
              f"{changed_slots} slots in {changed_records} records:")
        for text, n in changes.most_common():
            print(f"    {n:5d}  {text}")
    else:
        print("\nnothing to change")

    if hinted:
        print(f"\ntype decided by a name hint ({len(hinted)}):")
        for text in hinted:
            print("    " + text)
    if coinflips:
        print(f"\nCOIN FLIPS -- alphabetical order decided these ({len(coinflips)}). "
              f"Put the real answers in MANUAL and re-run:")
        for text in coinflips:
            print("    " + text)

    # --- verify: no organization may carry two facts anywhere ---------------
    residue = {org: dict(c) for org, c in facts_of(old_records + new_records).items()
               if len(c) > 1}
    if residue:
        print(f"\nSTILL CONFLICTING ({len(residue)}) -- nothing written:")
        for org, c in sorted(residue.items())[:40]:
            print(f"    {org}: {sorted(c)}")
        sys.exit(1)
    print("\nverified: every organization now carries exactly one (type, country)")

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
