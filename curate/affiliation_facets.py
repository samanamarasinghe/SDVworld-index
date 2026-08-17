#!/usr/bin/env python3
"""Add organization-aligned affiliation facets to numbered shards.

The authoritative author-to-affiliation relationship remains the two positionally
aligned ``authors`` and ``affiliations`` lists.  An affiliation may name multiple
organizations separated by semicolons.  The static page splits those strings, removes
duplicate organization names while preserving their first occurrence, and aligns these
two fields with that resulting organization sequence:

    affiliations: ["Harvard University; Korea University", "Harvard University"]
    affiliation_types: ["academic", "academic"]
    affiliation_countries: ["United States", "South Korea"]

Each organization receives one type and one country.  Hospitals are always nonprofit,
and multinational companies use one home country rather than every operating country.
Correction records are not touched: an empty field on an override would replace the
base record's populated value when build.py merges the shards.

Run without --write to report drift.  Run with --write to update every base record.
"""

import argparse
import collections
import glob
import json
import os
import re


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARDS = os.path.join(ROOT, "data", "shards", "*.json")

TYPE_ORDER = (
    "academic",
    "corporate",
    "government",
    "nonprofit",
    "other",
    "unknown",
)
TYPE_RANK = {value: index for index, value in enumerate(TYPE_ORDER)}

# ISO alpha-2 codes emitted by the OpenAlex/ROR attribution sources currently used by
# SDVworld.  Full names are stored in shards because the JSON is also read directly by
# people and pivot tables.
COUNTRY_BY_CODE = {
    "AE": "United Arab Emirates",
    "AL": "Albania",
    "AT": "Austria",
    "AU": "Australia",
    "BD": "Bangladesh",
    "BE": "Belgium",
    "BR": "Brazil",
    "CA": "Canada",
    "CH": "Switzerland",
    "CL": "Chile",
    "CN": "China",
    "CO": "Colombia",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DE": "Germany",
    "DK": "Denmark",
    "EG": "Egypt",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GB": "United Kingdom",
    "GR": "Greece",
    "HK": "Hong Kong",
    "HR": "Croatia",
    "HU": "Hungary",
    "ID": "Indonesia",
    "IE": "Ireland",
    "IN": "India",
    "IQ": "Iraq",
    "IR": "Iran",
    "IT": "Italy",
    "JO": "Jordan",
    "JP": "Japan",
    "KR": "South Korea",
    "KW": "Kuwait",
    "KZ": "Kazakhstan",
    "LK": "Sri Lanka",
    "MA": "Morocco",
    "MX": "Mexico",
    "MY": "Malaysia",
    "MK": "North Macedonia",
    "NL": "Netherlands",
    "NO": "Norway",
    "NZ": "New Zealand",
    "PK": "Pakistan",
    "PL": "Poland",
    "PT": "Portugal",
    "QA": "Qatar",
    "RO": "Romania",
    "RS": "Serbia",
    "RU": "Russia",
    "SA": "Saudi Arabia",
    "SE": "Sweden",
    "SG": "Singapore",
    "SI": "Slovenia",
    "SK": "Slovakia",
    "TH": "Thailand",
    "TN": "Tunisia",
    "TR": "Türkiye",
    "TW": "Taiwan",
    "TZ": "Tanzania",
    "US": "United States",
    "VN": "Vietnam",
    "XK": "Kosovo",
    "GH": "Ghana",
}

COUNTRY_ALIASES = {
    "The Netherlands": "Netherlands",
    "Turkey": "Türkiye",
    "United States of America": "United States",
}

# These six components were the only shard organizations without complete country/type
# evidence in the generated attribution tables.  The Peninsula Research entry is also
# corrected here because OpenAlex matched an unrelated Florida company; the publication
# itself names the UK NIHR South West Peninsula Applied Research Collaboration.
MANUAL_COUNTRIES = {
    "BC Cancer Agency": "Canada",
    "Centre d'Investigation Clinique Hôpital Européen Georges Pompidou": "France",
    "Changcheng Institute of Metrology & Measurement": "China",
    "China Electric Power Research Institute": "China",
    "Peninsula Research": "United Kingdom",
    "Samsung SDS (South Korea)": "South Korea",
    "University of British Columbia": "Canada",

    # Institutions whose source rows did not carry usable OpenAlex/ROR metadata.
    "Chang Gung University": "Taiwan",
    "Hohai University": "China",
    "National Central University": "Taiwan",
    "Shri Mata Vaishno Devi University": "India",
    "University of Danang, University of Science and Technology": "Vietnam",
    "University of Danang, Vietnam-Korea University of Information and Communication Technology": "Vietnam",

    # OpenAlex attached the US branch's country to this Taiwan-based foundation.
    "Buddhist Tzu Chi Medical Foundation": "Taiwan",

    # Curated country choices for explicitly labeled multinational branches.
    "Arup Group (Canada)": "United Kingdom",
    "BASF (United States)": "United States",
    "British American Tobacco (Germany)": "United Kingdom",
    "Google (United Kingdom)": "United States",
}

MANUAL_TYPES = {
    "BC Cancer Agency": "nonprofit",
    "Centre d'Investigation Clinique Hôpital Européen Georges Pompidou": "nonprofit",
    "Changcheng Institute of Metrology & Measurement": "government",
    "China Electric Power Research Institute": "corporate",
    "University of British Columbia": "academic",
    "Chang Gung University": "academic",
    "Hohai University": "academic",
    "National Central University": "academic",
    "Shri Mata Vaishno Devi University": "academic",
    "University of Danang, University of Science and Technology": "academic",
    "University of Danang, Vietnam-Korea University of Information and Communication Technology": "academic",

    # ROR calls these facilities/other.  The UI vocabulary needs one broad sector.
    "Bank of Canada": "government",
    "Barcelona Supercomputing Center": "government",
    "Center for Child and Adolescent Mental Health, Eastern and Southern Norway": "nonprofit",
    "Centro de Investigación y de Estudios Avanzados del Instituto Politécnico Nacional": "academic",
    "CSIRO Manufacturing": "government",
    "Culham Science Centre": "government",
    "FORTH Institute of Computer Science": "nonprofit",
    "FORTH Institute of Electronic Structure and Laser": "nonprofit",
    "FORTH Institute of Molecular Biology and Biotechnology": "nonprofit",
    "German Research Centre for Artificial Intelligence": "nonprofit",
    "IBM Research - Thomas J. Watson Research Center": "corporate",
    "Massachusetts Institute of Technology": "academic",
    "Institut de Mathématiques de Toulouse": "academic",
    "Institute of Geology and Geophysics": "government",
    "Peninsula Research": "government",
    "SLAC National Accelerator Laboratory": "government",
    "Torino e-district": "nonprofit",
}

HOSPITAL = re.compile(
    r"(?i)(hospital|hôpital|hospitalier|klinikum|kliniken|clinic(?:al)?|"
    r"medical cent(?:er|re)|health cent(?:er|re)|michigan medicine|ucla health|"
    r"cancer agency)"
)

GOVERNMENT_FACILITY = re.compile(
    r"(?i)(national (?:\w+ )*laboratory|national institute|national research|"
    r"atomic energy authority|academy of sciences|public health agency|"
    r"research and innovation agency|ministry of |government of |"
    r"institute of water resources|peng cheng laboratory|"
    r"shenzhen institutes of advanced technology|"
    r"ningbo institute of industrial technology|"
    r"northwest institute of nuclear technology|"
    r"ural branch of the russian academy|"
    r"toyama industrial technology center)"
)

ACADEMIC_FACILITY = re.compile(
    r"(?i)(laboratoire |institute of mathematics|observatoire de |"
    r"singapore-eth centre)"
)

CORPORATE_OTHER = re.compile(
    r"(?i)(bank$| bank |holdings$|ibm research|china electric power research)"
)


def load(relative, default):
    path = os.path.join(ROOT, relative)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def canonical_country(value):
    if not value:
        return None
    value = str(value).strip()
    if value in COUNTRY_BY_CODE:
        return COUNTRY_BY_CODE[value]
    return COUNTRY_ALIASES.get(value, value)


def add_evidence(evidence, name, organization_type=None, country=None,
                 country_code=None):
    if not name:
        return
    row = evidence[name]
    if organization_type:
        row["types"].add(organization_type)
    resolved_country = canonical_country(country_code) or canonical_country(country)
    if resolved_country:
        row["countries"].add(resolved_country)


def build_evidence():
    evidence = collections.defaultdict(
        lambda: {"types": set(), "countries": set()}
    )

    for relative in (
        "data/publication-author-affiliations.json",
        "data/github-repo-authors.json",
    ):
        for row in load(relative, {}).get("rows", []):
            add_evidence(
                evidence,
                row.get("affiliation"),
                row.get("affiliation_type"),
                row.get("affiliation_country"),
                row.get("affiliation_country_code"),
            )

    for mapping in load("data/affiliation-normalizations.json", {}).get(
        "mappings", {}
    ).values():
        for name in (mapping.get("raw"), mapping.get("canonical_name")):
            add_evidence(
                evidence,
                name,
                mapping.get("organization_type"),
                mapping.get("country"),
            )

    return evidence


def choose_country(name, evidence):
    if name in MANUAL_COUNTRIES:
        return MANUAL_COUNTRIES[name]
    countries = evidence[name]["countries"]
    if len(countries) == 1:
        return next(iter(countries))
    if not countries:
        return "unknown"
    raise ValueError(f"{name!r} has conflicting countries: {sorted(countries)}")


def choose_type(name, evidence):
    # Saman's rule is categorical: a hospital is nonprofit even when its ROR record
    # also calls it educational, governmental, a healthcare provider, or a funder.
    if HOSPITAL.search(name):
        return "nonprofit"
    if name in MANUAL_TYPES:
        return MANUAL_TYPES[name]

    types = "; ".join(sorted(evidence[name]["types"])).casefold()
    tokens = {token.strip() for token in types.split(";") if token.strip()}
    if "company" in tokens:
        return "corporate"
    if "education" in tokens:
        return "academic"
    if "government" in tokens:
        return "government"
    if "nonprofit" in tokens or "healthcare" in tokens:
        return "nonprofit"

    if "facility" in tokens or "funder" in tokens:
        if GOVERNMENT_FACILITY.search(name):
            return "government"
        if ACADEMIC_FACILITY.search(name):
            return "academic"
        if CORPORATE_OTHER.search(name):
            return "corporate"
        return "nonprofit"

    if "other" in tokens:
        if name == "Bank of Canada":
            return "government"
        if CORPORATE_OTHER.search(name):
            return "corporate"
        return "other"
    return "unknown"


def split_affiliation(value):
    return [part.strip() for part in value.split(";") if part.strip()]


def organizations_for(record):
    """Return the UI's organization sequence for an author-aligned record."""
    organizations = []
    seen = set()
    for affiliation in record.get("affiliations") or []:
        if not affiliation:
            continue
        for organization in split_affiliation(affiliation):
            if organization not in seen:
                seen.add(organization)
                organizations.append(organization)
    return organizations


def classify_record(record, evidence):
    organizations = organizations_for(record)
    types = [choose_type(organization, evidence) for organization in organizations]
    countries = [choose_country(organization, evidence) for organization in organizations]
    return types, countries


def insert_facets(record, affiliation_types, affiliation_countries):
    out = {}
    inserted = False
    for key, value in record.items():
        if key in ("affiliation_types", "affiliation_countries"):
            continue
        out[key] = value
        if key == "affiliations":
            out["affiliation_types"] = affiliation_types
            out["affiliation_countries"] = affiliation_countries
            inserted = True
    if not inserted:
        out["affiliation_types"] = affiliation_types
        out["affiliation_countries"] = affiliation_countries
    return out


def file_indent(path):
    """Preserve each shard's existing one- or two-space JSON convention."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read(256)
    match = re.search(r"\n( +)\{", text)
    return len(match.group(1)) if match else 1


def write_json(path, payload, indent):
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=indent, ensure_ascii=False)
        fh.write("\n")
    os.replace(temporary, path)


def main(write=False):
    evidence = build_evidence()
    changed_files = changed_records = base_records = overrides = 0
    type_counts = collections.Counter()
    country_counts = collections.Counter()

    for path in sorted(glob.glob(SHARDS)):
        indent = file_indent(path)
        records = load(os.path.relpath(path, ROOT), [])
        updated = []
        file_changed = False
        for record in records:
            if record.get("override"):
                overrides += 1
                updated.append(record)
                continue
            base_records += 1
            affiliation_types, affiliation_countries = classify_record(record, evidence)
            type_counts.update(affiliation_types)
            country_counts.update(affiliation_countries)
            revised = insert_facets(record, affiliation_types, affiliation_countries)
            if revised != record:
                changed_records += 1
                file_changed = True
            updated.append(revised)
        if file_changed:
            changed_files += 1
            if write:
                write_json(path, updated, indent)

    action = "updated" if write else "would update"
    print(f"{action} {changed_records} base records in {changed_files} shard files")
    print(f"checked {base_records} base records; left {overrides} overrides untouched")
    print("affiliation types: " + ", ".join(
        f"{value}={type_counts[value]}" for value in TYPE_ORDER if type_counts[value]
    ))
    print("top countries: " + ", ".join(
        f"{value}={count}" for value, count in country_counts.most_common(15)
    ))
    return 1 if changed_records and not write else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    raise SystemExit(main(**vars(args)))
