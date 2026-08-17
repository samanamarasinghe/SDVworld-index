#!/usr/bin/env python3
"""Build a conservative canonical display-name map.

This is presentation cleanup, not legal identity resolution. It normalizes
spacing/case, removes clear honorifics and degree suffixes, selects one display
variant for punctuation/case/diacritic equivalents, and reports when the same
name is used by multiple GitHub numeric IDs. Different IDs are never merged.

Output:
  data/public-name-normalizations.json
"""

import datetime
import json
import os
import re
import unicodedata


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "data", "github-repo-authors.json")
OUT = os.path.join(ROOT, "data", "public-name-normalizations.json")
PERSON_TYPES = {"person", "anonymous"}
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
HONORIFIC_RE = re.compile(r"(?i)^(?:dr\.?|prof(?:essor)?\.?|mr\.?|mrs\.?|ms\.?)\s+")
DEGREE_RE = re.compile(
    r"(?i)(?:,\s*)+(?:ph\.?d\.?|m\.?s\.?|m\.?sc\.?|m\.?b\.?a\.?|pmp)"
    r"(?:\s*,\s*(?:ph\.?d\.?|m\.?s\.?|m\.?sc\.?|m\.?b\.?a\.?|pmp))*\s*$"
)
TRANSLITERATION = str.maketrans({
    "ø": "o", "Ø": "O", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D",
    "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th", "ß": "ss", "æ": "ae",
    "Æ": "Ae", "œ": "oe", "Œ": "Oe",
})


def today():
    return datetime.date.today().isoformat()


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def atomic_write(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)


def collapse_space(value):
    return " ".join((value or "").replace("\u200b", "").split())


def is_name_text(value):
    return bool(value and re.fullmatch(r"[^\W\d_][^\d@|/]*", value, re.UNICODE))


def smart_title(value):
    letters = "".join(character for character in value if character.isalpha())
    words = value.split()
    if any("CJK" in unicodedata.name(character, "") or
           "HIRAGANA" in unicodedata.name(character, "") or
           "KATAKANA" in unicodedata.name(character, "") or
           "HANGUL" in unicodedata.name(character, "") for character in value):
        return value
    # Mixed-case strings often contain meaningful initials, acronyms, or a
    # family name intentionally written in capitals.  Do not "fix" those.
    if len(words) < 2 or not letters or not (letters.islower() or letters.isupper()):
        return value
    blocked_tokens = {
        "AI", "BOT", "ENTERPRISE", "GROUP", "INC", "LAB", "LLC", "LTD",
        "ML", "PLATFORM", "TEAM",
    }
    if (any(word.strip(".,:;()[]{}").upper() in blocked_tokens for word in words)
            or any(marker in value for marker in ("&", "|", "@"))):
        return value
    particles = {"al", "bin", "da", "de", "del", "der", "di", "dos", "du",
                 "la", "le", "van", "von"}
    result = []
    for index, word in enumerate(words):
        stripped = word.strip(".,")
        if len(stripped) == 1 and stripped.isalpha():
            replacement = word.upper()
        elif index and stripped.casefold() in particles:
            replacement = word.lower()
        else:
            replacement = word.title()
        result.append(replacement)
    return " ".join(result)


def format_person_name(raw):
    value = unicodedata.normalize("NFC", collapse_space(raw))
    notes = []
    if value.casefold() in {"", ".", "=", "?", "first last", "test user",
                            "unknown", "xxxx xxxx", "your name"}:
        return None, "invalid_public_name", ["not a usable person name"]
    if value != raw:
        notes.append("normalized whitespace")

    emails = EMAIL_RE.findall(value)
    if emails:
        without_email = collapse_space(EMAIL_RE.sub("", value).strip(" -|,;"))
        if not without_email:
            return None, "invalid_public_name", ["email address is not a public name"]
        value = without_email
        notes.append("removed appended email address")

    without_honorific = HONORIFIC_RE.sub("", value)
    if without_honorific != value:
        value = collapse_space(without_honorific)
        notes.append("removed honorific")

    without_degree = DEGREE_RE.sub("", value)
    if without_degree != value:
        value = collapse_space(without_degree)
        notes.append("removed degree/certification suffix")

    if value.count(",") == 1:
        family, given = [collapse_space(part) for part in value.split(",", 1)]
        if is_name_text(family) and is_name_text(given):
            value = f"{given} {family}"
            notes.append("changed comma-order name to given-name-first display")

    titled = smart_title(value)
    if titled != value:
        value = titled
        notes.append("normalized all-upper/all-lower casing")

    status = "format_normalized" if value != raw or notes else "unchanged"
    return value, status, notes


def format_nonperson_name(raw):
    value = unicodedata.normalize("NFC", collapse_space(raw))
    status = "format_normalized" if value != raw else "unchanged"
    return value or None, status, (["normalized whitespace"] if value != raw else [])


def comparison_key(value):
    if not value:
        return None
    folded = unicodedata.normalize("NFKD", value.translate(TRANSLITERATION))
    folded = "".join(character for character in folded if not unicodedata.combining(character))
    folded = folded.casefold()
    folded = re.sub(r"[^\w]+", " ", folded, flags=re.UNICODE)
    return collapse_space(folded)


def case_quality(value):
    letters = "".join(character for character in value if character.isalpha())
    if not letters:
        return 0
    return 2 if not (letters.islower() or letters.isupper()) else 1


def candidate_score(record):
    value = record["formatted"]
    status_weight = 30 if "profile_stated" in record["source_statuses"] else 20
    diacritics = sum(ord(character) > 127 for character in value)
    awkward_capitals = sum(
        len("".join(character for character in word if character.isalpha())) > 1
        and word.strip(".,:;()[]{}").isupper()
        for word in value.split()
    )
    return (case_quality(value), -awkward_capitals, diacritics,
            status_weight, -len(value), value.casefold())


def category(account_type):
    return "person" if account_type in PERSON_TYPES else account_type


def main():
    payload = load(SOURCE)
    aggregate = {}
    for row in payload.get("rows") or []:
        raw = row.get("public_name_raw") or row.get("public_name")
        if not raw:
            continue
        account_type = row.get("account_type") or "unknown"
        item = aggregate.setdefault((account_type, raw), {
            "account_type": account_type,
            "raw": raw,
            "source_statuses": set(),
            "github_ids": set(),
            "github_logins": set(),
            "rows": 0,
        })
        item["source_statuses"].add(row.get("name_status") or "unresolved")
        if row.get("github_user_id") is not None:
            item["github_ids"].add(row["github_user_id"])
        if row.get("github_login"):
            item["github_logins"].add(row["github_login"])
        item["rows"] += 1

    records = []
    clusters = {}
    for item in aggregate.values():
        if item["account_type"] in PERSON_TYPES:
            formatted, status, notes = format_person_name(item["raw"])
        else:
            formatted, status, notes = format_nonperson_name(item["raw"])
        record = {
            **item,
            "source_statuses": sorted(item["source_statuses"]),
            "github_ids": sorted(item["github_ids"]),
            "github_logins": sorted(item["github_logins"], key=lambda value: (value.casefold(), value)),
            "formatted": formatted,
            "canonical_name": formatted,
            "normalization_status": status,
            "normalization_notes": notes,
            "canonical_name_key": comparison_key(formatted),
        }
        records.append(record)
        if formatted:
            cluster_key = (category(item["account_type"]), comparison_key(formatted))
            clusters.setdefault(cluster_key, []).append(record)

    for (_, key), members in clusters.items():
        chosen = max(members, key=candidate_score)["formatted"]
        variants = sorted(
            {member["formatted"] for member in members},
            key=lambda value: (value.casefold(), value),
        )
        ids = sorted({github_id for member in members for github_id in member["github_ids"]})
        for member in members:
            if member["formatted"] != chosen:
                member["normalization_status"] = "variant_canonicalized"
                member["normalization_notes"].append(
                    "selected one display form from an equivalent case/punctuation/diacritic cluster")
            member["canonical_name"] = chosen
            member["canonical_name_key"] = key
            member["equivalent_name_variants"] = variants
            member["same_name_github_account_count"] = len(ids)
            if len(ids) > 1:
                member["normalization_notes"].append(
                    "multiple GitHub numeric IDs use this name; accounts were not merged")

    records.sort(key=lambda item: (item["account_type"], item["raw"].casefold(), item["raw"]))
    counts = {}
    for record in records:
        status = record["normalization_status"]
        counts[status] = counts.get(status, 0) + 1
    atomic_write(OUT, {
        "note": (
            "Canonical display names derived conservatively from public GitHub profile and "
            "Git commit names. Raw values are preserved. Equivalent formatting variants share "
            "one display name, but distinct GitHub numeric IDs are never merged solely by name."
        ),
        "generated": today(),
        "counts": dict(sorted(counts.items())),
        "mappings": records,
    })
    print(json.dumps({"raw_name_type_pairs": len(records), **dict(sorted(counts.items()))}, indent=2))


if __name__ == "__main__":
    main()
