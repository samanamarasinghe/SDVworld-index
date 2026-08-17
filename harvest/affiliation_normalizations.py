#!/usr/bin/env python3
"""Build an auditable canonical-affiliation map for GitHub profile strings.

The raw GitHub `company` field is free text.  This script preserves that input,
uses the public ROR affiliation matcher for research organizations, applies a
small curated alias/legal-name layer, and marks anything else as unconfirmed.

    python3 harvest/affiliation_normalizations.py --refresh-ror

Outputs:
  data/tail/affiliation-ror-matches.json  resumable ROR lookup cache
  data/affiliation-normalizations.json    complete offline normalization map
"""

import argparse
import concurrent.futures
import datetime
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDENTITIES = os.path.join(ROOT, "data", "tail", "github-identities.json")
ROR_CACHE = os.path.join(ROOT, "data", "tail", "affiliation-ror-matches.json")
OUT = os.path.join(ROOT, "data", "affiliation-normalizations.json")
ROR_API = "https://api.ror.org/v2/organizations"


def today():
    return datetime.date.today().isoformat()


def load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def atomic_write(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)


def entry(canonical_name, status="normalized_unconfirmed", country=None,
          evidence_urls=None, organization_type=None, note=None):
    return {
        "canonical_name": canonical_name,
        "status": status,
        "country": country,
        "organization_type": organization_type,
        "ror_id": None,
        "evidence_urls": evidence_urls or [],
        "note": note,
    }


# Confirmed entries cite an official source. Other entries are deliberately
# labelled normalized_unconfirmed even when the expansion is very likely.
EXPLICIT = {
    "@google": entry("Google, LLC", "official_source_confirmed", "United States",
                     ["https://www.about.google/policies/terms/"], "company"),
    "google": entry("Google, LLC", "official_source_confirmed", "United States",
                    ["https://www.about.google/policies/terms/"], "company"),
    "@googlecloudplatform | @google": entry(
        "Google, LLC", "official_source_confirmed", "United States",
        ["https://www.about.google/policies/terms/"], "company"),
    "github": entry("GitHub, Inc.", "official_source_confirmed", "United States",
                    ["https://docs.github.com/en/site-policy/github-terms/github-terms-of-service"],
                    "company"),
    "@github": entry("GitHub, Inc.", "official_source_confirmed", "United States",
                     ["https://docs.github.com/en/site-policy/github-terms/github-terms-of-service"],
                     "company"),
    "meta": entry("Meta Platforms, Inc.", "official_source_confirmed", "United States",
                  ["https://investor.atmeta.com/files/doc_downloads/2024/05/2024-anti-slavery-and-human-trafficking-statement.pdf"],
                  "company"),
    "meta inc": entry("Meta Platforms, Inc.", "official_source_confirmed", "United States",
                      ["https://investor.atmeta.com/files/doc_downloads/2024/05/2024-anti-slavery-and-human-trafficking-statement.pdf"],
                      "company"),
    "@meta-llama": entry("Meta Platforms, Inc.", "official_source_confirmed", "United States",
                         ["https://investor.atmeta.com/files/doc_downloads/2024/05/2024-anti-slavery-and-human-trafficking-statement.pdf"],
                         "company"),
    "stanford cs": entry("Leland Stanford Junior University", "official_source_confirmed",
                         "United States", ["https://www.stanford.edu/about/history"],
                         "education"),
    "stanford university": entry(
        "Leland Stanford Junior University", "official_source_confirmed", "United States",
        ["https://www.stanford.edu/about/history"], "education"),
    "@yaleuniversity": entry("Yale University", "official_source_confirmed",
                             "United States",
                             ["https://www.yale.edu/board-trustees/governance-history/miscellaneous-regulations"],
                             "education",
                             "Yale College is the undergraduate college; the profile handle identifies Yale University."),
    "yaleuni": entry("Yale University", "official_source_confirmed", "United States",
                     ["https://www.yale.edu/board-trustees/governance-history/miscellaneous-regulations"],
                     "education"),
    "anthropic": entry("Anthropic, PBC", "official_source_confirmed", "United States",
                       ["https://www.anthropic.com/startup-program-official-terms"], "company"),
    "anthropic ai": entry("Anthropic, PBC", "official_source_confirmed", "United States",
                          ["https://www.anthropic.com/startup-program-official-terms"], "company"),
    "@anthropics": entry("Anthropic, PBC", "official_source_confirmed", "United States",
                         ["https://www.anthropic.com/startup-program-official-terms"], "company"),
    "datacebo": entry("DataCebo, Inc.", "official_source_confirmed", "United States",
                      ["https://datacebo.com/privacy-policy/"], "company"),
    "@datacebo": entry("DataCebo, Inc.", "official_source_confirmed", "United States",
                       ["https://datacebo.com/privacy-policy/"], "company"),
    "@sdv-dev": entry("DataCebo, Inc.", "official_source_confirmed", "United States",
                      ["https://datacebo.com/privacy-policy/"], "company"),

    "mit": entry("Massachusetts Institute of Technology", country="United States",
                 organization_type="education"),
    "cmu ece": entry("Carnegie Mellon University", country="United States",
                     organization_type="education"),
    "ncsu": entry("North Carolina State University", country="United States",
                  organization_type="education"),
    "north carolina state university, raleigh": entry(
        "North Carolina State University", country="United States", organization_type="education"),
    "ucla": entry("University of California, Los Angeles", country="United States",
                  organization_type="education"),
    "university of california, los angeles": entry(
        "University of California, Los Angeles", country="United States", organization_type="education"),
    "ucl": entry("University College London", country="United Kingdom",
                 organization_type="education"),
    "ut austin": entry("The University of Texas at Austin", country="United States",
                       organization_type="education"),
    "university of  texas at dallas": entry("The University of Texas at Dallas",
                                            country="United States", organization_type="education"),
    "unc chapel hill": entry("University of North Carolina at Chapel Hill",
                             country="United States", organization_type="education"),
    "university of st.gallen": entry("University of St.Gallen", country="Switzerland",
                                     organization_type="education"),
    "rice uniersity": entry("Rice University", country="United States",
                            organization_type="education"),
    "fudan univsersity": entry("Fudan University", country="China",
                               organization_type="education"),
    "universty of antwerp": entry("University of Antwerp", country="Belgium",
                                  organization_type="education"),
    "univeristy of california san diego @ucsd": entry(
        "University of California, San Diego", country="United States", organization_type="education"),
    "queen's univeristy": entry("Queen's University", country="Canada",
                                organization_type="education"),
    "southwestern university of finance and econemics": entry(
        "Southwestern University of Finance and Economics", country="China",
        organization_type="education"),
    "sapienza univesity of rome": entry("Sapienza University of Rome", country="Italy",
                                        organization_type="education"),
    "soongsil univ.": entry("Soongsil University", country="South Korea",
                            organization_type="education"),
    "soongsil unv.": entry("Soongsil University", country="South Korea",
                           organization_type="education"),
    "yonsei univ.": entry("Yonsei University", country="South Korea",
                          organization_type="education"),
    "zju": entry("Zhejiang University", country="China", organization_type="education"),
    "itmo": entry("ITMO University", country="Russia", organization_type="education"),
    "iiitb": entry("International Institute of Information Technology Bangalore",
                   country="India", organization_type="education"),
    "international institute of information technology, bangalore": entry(
        "International Institute of Information Technology Bangalore", country="India",
        organization_type="education"),
    "international institute of information and technology bangalore": entry(
        "International Institute of Information Technology Bangalore", country="India",
        organization_type="education"),
    "kaust": entry("King Abdullah University of Science and Technology",
                   country="Saudi Arabia", organization_type="education"),
    "kaist": entry("Korea Advanced Institute of Science and Technology",
                   country="South Korea", organization_type="education"),
    "hse": entry("HSE University", country="Russia", organization_type="education"),
    "lmu": entry("Ludwig Maximilian University of Munich", country="Germany",
                 organization_type="education"),
    "università degli studi di trieste": entry("University of Trieste", country="Italy",
                                               organization_type="education"),
    "the university of tokyo": entry("The University of Tokyo", country="Japan",
                                     organization_type="education"),
    "university of adelaide": entry("The University of Adelaide", country="Australia",
                                    organization_type="education"),
    "gachon university": entry("Gachon University", country="South Korea",
                               organization_type="education"),
    "iiit delhi": entry("Indraprastha Institute of Information Technology Delhi",
                        country="India", organization_type="education"),
    "birla institute of technology and sciences": entry(
        "Birla Institute of Technology and Science, Pilani", country="India",
        organization_type="education"),
    "heinrich heine university": entry("Heinrich Heine University Düsseldorf",
                                      country="Germany", organization_type="education"),
    "hhu düsseldorf": entry("Heinrich Heine University Düsseldorf", country="Germany",
                            organization_type="education"),
    "hpi posdam": entry("Hasso Plattner Institute", country="Germany",
                        organization_type="education"),
    "bgu": entry("Ben-Gurion University of the Negev", country="Israel",
                 organization_type="education"),
    "boun": entry("Boğaziçi University", country="Türkiye", organization_type="education"),
    "ecnu": entry("East China Normal University", country="China",
                  organization_type="education"),
    "feup": entry("Faculty of Engineering of the University of Porto", country="Portugal",
                  organization_type="education"),
    "fcup": entry("Faculty of Sciences of the University of Porto", country="Portugal",
                  organization_type="education"),
    "fhnw": entry("University of Applied Sciences and Arts Northwestern Switzerland",
                  country="Switzerland", organization_type="education"),
    "forth": entry("Foundation for Research and Technology – Hellas", country="Greece",
                   organization_type="facility"),
    "hkust": entry("The Hong Kong University of Science and Technology", country="Hong Kong",
                   organization_type="education"),
    "ista": entry("Institute of Science and Technology Austria", country="Austria",
                  organization_type="education"),
    "itesm": entry("Instituto Tecnológico y de Estudios Superiores de Monterrey",
                   country="Mexico", organization_type="education"),
    "nus school of computing": entry("National University of Singapore", country="Singapore",
                                     organization_type="education"),
    "nyu courant": entry("New York University", country="United States",
                         organization_type="education"),
    "nyu courant (student)": entry("New York University", country="United States",
                                   organization_type="education"),
    "postech ai": entry("Pohang University of Science and Technology", country="South Korea",
                        organization_type="education"),
    "purdue": entry("Purdue University", country="United States",
                    organization_type="education"),
    "qut": entry("Queensland University of Technology", country="Australia",
                 organization_type="education"),
    "sjtu": entry("Shanghai Jiao Tong University", country="China",
                  organization_type="education"),
    "spbu": entry("Saint Petersburg State University", country="Russia",
                  organization_type="education"),
    "sungkyunkwan univ.": entry("Sungkyunkwan University", country="South Korea",
                               organization_type="education"),
    "thapar": entry("Thapar Institute of Engineering and Technology", country="India",
                    organization_type="education"),
    "ucu": entry("Ukrainian Catholic University", country="Ukraine",
                 organization_type="education"),
    "uni bayreuth (ubt)": entry("University of Bayreuth", country="Germany",
                                organization_type="education"),
    "unipisa": entry("University of Pisa", country="Italy", organization_type="education"),
    "university rostock": entry("University of Rostock", country="Germany",
                                organization_type="education"),
    "vit": entry("Vellore Institute of Technology", country="India",
                 organization_type="education"),
    "spring lab @epfl": entry("École Polytechnique Fédérale de Lausanne",
                              country="Switzerland", organization_type="education"),
    "teachers college, columbia university": entry(
        "Teachers College, Columbia University", country="United States",
        organization_type="education"),

    "nvidia": entry("NVIDIA Corporation", country="United States", organization_type="company"),
    "microsoft": entry("Microsoft Corporation", country="United States", organization_type="company"),
    "amazon": entry("Amazon.com, Inc.", country="United States", organization_type="company"),
    "oracle": entry("Oracle Corporation", country="United States", organization_type="company"),
    "red hat": entry("Red Hat, Inc.", country="United States", organization_type="company"),
    "databricks": entry("Databricks, Inc.", country="United States", organization_type="company"),
    "incoming @ databricks": entry("Databricks, Inc.", country="United States", organization_type="company"),
    "packt": entry("Packt Publishing Limited", country="United Kingdom", organization_type="company"),
    "packt publishing": entry("Packt Publishing Limited", country="United Kingdom", organization_type="company"),
    "@packtpublishing": entry("Packt Publishing Limited", country="United Kingdom", organization_type="company"),
    "sas": entry("SAS Institute Inc.", country="United States", organization_type="company"),
    "sas institute": entry("SAS Institute Inc.", country="United States", organization_type="company"),
    "sas institute, inc.": entry("SAS Institute Inc.", country="United States", organization_type="company"),
    "@sassoftware": entry("SAS Institute Inc.", country="United States", organization_type="company"),
    "hp inc": entry("HP Inc.", country="United States", organization_type="company"),
    "globalfoundries": entry("GlobalFoundries Inc.", country="United States", organization_type="company"),
    "digital ocean": entry("DigitalOcean, LLC", country="United States", organization_type="company"),
    "teradata": entry("Teradata Corporation", country="United States", organization_type="company"),
    "ibm": entry("International Business Machines Corporation", country="United States",
                 organization_type="company"),
    "ey": entry("Ernst & Young Global Limited", country="United Kingdom",
                organization_type="company"),
    "@capgemini": entry("Capgemini SE", country="France", organization_type="company"),
    "@bytedance": entry("ByteDance Ltd.", country="China", organization_type="company"),
    "bytedance - seed": entry("ByteDance Ltd.", country="China", organization_type="company"),
    "@anyscale": entry("Anyscale, Inc.", country="United States", organization_type="company"),
    "@mitre": entry("The MITRE Corporation", country="United States", organization_type="nonprofit"),
    "@nhsengland": entry("NHS England", country="United Kingdom", organization_type="government"),
    "nhs england": entry("NHS England", country="United Kingdom", organization_type="government"),
    "@sib-swiss": entry("SIB Swiss Institute of Bioinformatics", country="Switzerland",
                        organization_type="nonprofit"),
    "vector institute": entry("Vector Institute for Artificial Intelligence", country="Canada",
                              organization_type="nonprofit"),
    "@vectorinstitute": entry("Vector Institute for Artificial Intelligence", country="Canada",
                              organization_type="nonprofit"),
    "@cdacdelhi": entry("Centre for Development of Advanced Computing", country="India",
                        organization_type="government"),
    "etri": entry("Electronics and Telecommunications Research Institute", country="South Korea",
                  organization_type="government"),
    "mpi-sws": entry("Max Planck Institute for Software Systems", country="Germany",
                     organization_type="facility"),
    "ai innovation lab": entry("AI Innovation Lab",
                               note="Ambiguous organization name; ROR candidate rejected."),
    "anura innovations": entry("Anura Innovations",
                               note="ROR candidate was a different organization."),
    "kiet group of institutions": entry("KIET Group of Institutions", country="India",
                                        organization_type="education",
                                        note="ROR candidate was a different institution."),
    "manulife it delivery center asia inc.": entry(
        "Manulife IT Delivery Center Asia Inc.", country="Philippines",
        organization_type="company", note="ROR candidate was a different institution."),
    "synapse international": entry("Synapse International", organization_type="company",
                                  note="ROR candidate was a different organization."),
    "bifold & tu berlin": entry(
        "Berlin Institute for the Foundations of Learning and Data; Technische Universität Berlin",
        country="Germany", organization_type="research institute; education"),
    "dana-farber cancer institute / broad institute": entry(
        "Dana-Farber Cancer Institute; Broad Institute", country="United States",
        organization_type="healthcare; research institute"),
    "sapienza university / istituto superiore di sanità": entry(
        "Sapienza University of Rome; Istituto Superiore di Sanità", country="Italy",
        organization_type="education; government"),
    "cmu and feup": entry(
        "Carnegie Mellon University; Faculty of Engineering of the University of Porto",
        organization_type="education"),
    "nyu | sov.ai": entry("New York University; Sov.ai", organization_type="education; company"),
    "pinterest | cmu": entry("Pinterest, Inc.; Carnegie Mellon University",
                            country="United States", organization_type="company; education"),
    "institute of data science": entry(
        "Institute of Data Science, Maastricht University", country="The Netherlands",
        organization_type="education"),
    "lightningai ⚡️": entry("Lightning AI, Inc.", country="United States",
                            organization_type="company"),
    "@universityofcalifornia,irvine": entry("University of California, Irvine",
                                           country="United States", organization_type="education"),
    "@mrc-cso-sphsu": entry(
        "MRC/CSO Social and Public Health Sciences Unit, University of Glasgow",
        country="United Kingdom", organization_type="research institute"),
    "@pytorch": entry("PyTorch Foundation", country="United States",
                      organization_type="nonprofit"),
    "@sonarsource": entry("SonarSource SA", country="Switzerland",
                          organization_type="company"),
    "@dnv": entry("DNV AS", country="Norway", organization_type="company"),
    "@picnicsupermarket": entry("Picnic Technologies B.V.", country="The Netherlands",
                                organization_type="company"),
    "wise": entry("Wise plc", country="United Kingdom", organization_type="company"),
    "wpp": entry("WPP plc", country="United Kingdom", organization_type="company"),
    "astrazeneca": entry("AstraZeneca PLC", country="United Kingdom",
                         organization_type="company"),
    "barclays": entry("Barclays PLC", country="United Kingdom", organization_type="company"),
    "bmw group": entry("Bayerische Motoren Werke Aktiengesellschaft", country="Germany",
                       organization_type="company"),
    "cloudera": entry("Cloudera, Inc.", country="United States", organization_type="company"),
    "couchbase": entry("Couchbase, Inc.", country="United States", organization_type="company"),
    "epam systems": entry("EPAM Systems, Inc.", country="United States",
                          organization_type="company"),
    "intuit": entry("Intuit Inc.", country="United States", organization_type="company"),
    "pfizer inc.": entry("Pfizer Inc.", country="United States", organization_type="company"),
    "qualcomm": entry("Qualcomm Incorporated", country="United States",
                      organization_type="company"),
    "rbc": entry("Royal Bank of Canada", country="Canada", organization_type="company"),
    "swisscom": entry("Swisscom AG", country="Switzerland", organization_type="company"),
    "toptal": entry("Toptal, LLC", country="United States", organization_type="company"),
    "verily (alphabet)": entry("Verily Life Sciences LLC", country="United States",
                               organization_type="company"),
    "zs associates": entry("ZS Associates, Inc.", country="United States",
                           organization_type="company"),
}


NOT_AFFILIATION = {
    "ai and cloud developer", "analista de dados | python | power bi. | sql | rpa .",
    "anshuman", "b", "china", "data scientists", "freelance", "freelancer",
    "graduate student", "japan", "no", "none", "phd.", "program development",
    "student", "university", "vibe writer", "@actions", "@semantic-release",
    "imgbot", "lead ai engineer | upwork | jtech | ab {ark} | abacus",
    "七年級尾巴的一般人 / 工程師 / 貧民",
}


def raw_affiliations():
    profiles = load(IDENTITIES, {}).get("identities", {}).values()
    return sorted({profile.get("affiliation") for profile in profiles
                   if profile.get("affiliation")}, key=str.casefold)


def ror_display_name(organization):
    names = organization.get("names") or []
    for name in names:
        if "ror_display" in (name.get("types") or []):
            return name.get("value")
    return next((name.get("value") for name in names if name.get("value")), None)


def fetch_ror(raw):
    url = ROR_API + "?" + urllib.parse.urlencode({"affiliation": raw})
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "sdvworld-index-affiliation-normalizer/1.0",
    })
    delay = 2
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.load(response)
            chosen = next((item for item in payload.get("items") or []
                           if item.get("chosen") is True), None)
            if not chosen:
                return {"status": "unmatched", "checked_at": today()}
            organization = chosen.get("organization") or {}
            location = ((organization.get("locations") or [{}])[0]
                        .get("geonames_details") or {})
            return {
                "status": "matched",
                "canonical_name": ror_display_name(organization),
                "ror_id": organization.get("id"),
                "country": location.get("country_name"),
                "organization_types": organization.get("types") or [],
                "matching_type": chosen.get("matching_type"),
                "score": chosen.get("score"),
                "checked_at": today(),
            }
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 5:
                raise
        except (TimeoutError, urllib.error.URLError):
            if attempt == 5:
                raise
        time.sleep(delay)
        delay = min(delay * 2, 30)
    raise RuntimeError("ROR retry loop exhausted")


def refresh_ror(cache, values, workers):
    todo = [value for value in values if value not in cache]
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_ror, value): value for value in todo}
        for future in concurrent.futures.as_completed(futures):
            value = futures[future]
            cache[value] = future.result()
            completed += 1
            if completed % 25 == 0 or completed == len(todo):
                atomic_write(ROR_CACHE, {
                    "note": "Resumable responses from the public ROR affiliation matcher.",
                    "generated": today(),
                    "source": "https://api.ror.org/v2/organizations?affiliation=",
                    "matches": dict(sorted(cache.items(), key=lambda item: item[0].casefold())),
                })
                print(f"ROR {completed}/{len(todo)}")


def best_effort(raw):
    key = raw.casefold().strip()
    if key in NOT_AFFILIATION:
        return entry(None, "not_an_affiliation",
                     note="The GitHub profile value is not an organization name.")
    if key.startswith("lead software engineer at "):
        return entry(raw[len("Lead Software Engineer at "):].strip())
    if key.startswith("phd scholar @ "):
        return entry(raw[len("PhD Scholar @ "):].strip())
    if key.startswith("master's student in ai at the "):
        return entry(raw[len("Master's student in AI at the "):].strip().title())
    if " · open to " in raw:
        return entry(raw.split(" · open to ", 1)[0].strip())
    if raw.startswith("@") and raw.count("@") == 1:
        return entry(raw[1:].strip())
    if raw.startswith("https://") or raw.startswith("http://"):
        host = urllib.parse.urlparse(raw).netloc.removeprefix("www.")
        return entry(host)
    return entry(raw, "profile_stated_unconfirmed")


def build_map(values, ror):
    mappings = {}
    counts = {}
    for raw in values:
        key = raw.casefold().strip()
        if key in EXPLICIT:
            result = dict(EXPLICIT[key])
        elif key in NOT_AFFILIATION:
            result = best_effort(raw)
        else:
            match = ror.get(raw) or {}
            if match.get("status") == "matched" and match.get("canonical_name"):
                result = entry(
                    match["canonical_name"], "ror_confirmed", match.get("country"),
                    [match.get("ror_id")],
                    "; ".join(match.get("organization_types") or []) or None,
                )
                result["ror_id"] = match.get("ror_id")
                result["note"] = "Automatically selected by the ROR affiliation matcher (chosen=true)."
            else:
                result = best_effort(raw)
        result["raw"] = raw
        mappings[raw] = result
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    return mappings, dict(sorted(counts.items()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-ror", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    values = raw_affiliations()
    ror_payload = load(ROR_CACHE, {})
    ror = dict(ror_payload.get("matches") or {})
    if args.refresh_ror:
        refresh_ror(ror, values, args.workers)
    mappings, counts = build_map(values, ror)
    atomic_write(OUT, {
        "note": (
            "Canonical names for public GitHub profile affiliation strings. Raw values are "
            "preserved in each mapping. ror_confirmed means the ROR matcher returned "
            "chosen=true; official_source_confirmed cites an official source; other statuses "
            "must not be treated as verified legal names."
        ),
        "generated": today(),
        "counts": counts,
        "mappings": mappings,
    })
    print(json.dumps({"affiliations": len(values), **counts}, indent=2))


if __name__ == "__main__":
    main()
