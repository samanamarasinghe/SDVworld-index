#!/usr/bin/env python3
"""Build publication-scoped author and affiliation rows for SDVworld.

The output deliberately keeps affiliations on the publication-author
relationship.  A person may therefore have different affiliations in different
SDVworld records.  Raw source values, canonical display values, persistent IDs,
download links, evidence, and confidence/status fields are kept separately.

No credentials are required.  OPENALEX_API_KEY or OPENALEX_EMAIL may be set for
polite-pool/rate-limit purposes.  Network responses are checkpointed so the run
is resumable.

Outputs:
  data/tail/publication-identities.json
  data/publication-author-affiliations.json
  data/publication-author-affiliations.csv
"""

import argparse
import csv
import datetime
import html
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "data", "sdv-index.json")
OPENALEX_POOL = os.path.join(ROOT, "data", "tail", "openalex-citations.json")
GITHUB_AUTHORS = os.path.join(ROOT, "data", "github-repo-authors.json")
AFFILIATION_NORMALIZATIONS = os.path.join(ROOT, "data", "affiliation-normalizations.json")
CURATED_OVERRIDES = os.path.join(
    ROOT, "data", "publication-author-affiliation-overrides.json")
CACHE = os.path.join(ROOT, "data", "tail", "publication-identities.json")
OUT = os.path.join(ROOT, "data", "publication-author-affiliations.json")
OUT_CSV = os.path.join(ROOT, "data", "publication-author-affiliations.csv")

SCHOLARLY_KINDS = {"paper", "preprint", "thesis"}
ARTICLE_TYPES = {
    "Article", "BlogPosting", "CreativeWork", "Dataset", "LearningResource",
    "NewsArticle", "Report", "ScholarlyArticle", "TechArticle", "WebPage",
}
LIST_FIELDS = {
    "affiliation_evidence_urls", "download_evidence_urls", "duplicate_sdv_ids",
    "name_evidence_urls", "raw_affiliation_strings", "roles",
    "unmapped_publication_affiliations",
}
CSV_FIELDS = [
    "sdv_id", "duplicate_sdv_ids", "kind", "title", "year", "source_channel",
    "github_repo_id", "github_repo", "github_repo_url",
    "author_position", "author_role", "account_type", "author_identity_key",
    "identity_status", "public_name_raw", "public_name", "name_source_status",
    "name_normalization_status", "name_normalization_note", "author_orcid",
    "author_openalex_id", "github_user_id", "github_login", "author_profile_url",
    "affiliation_position", "affiliation_raw", "affiliation", "affiliation_unit",
    "affiliation_source_status", "affiliation_normalization_status",
    "affiliation_country", "affiliation_country_code", "affiliation_type",
    "affiliation_ror_id", "raw_affiliation_strings",
    "unmapped_publication_affiliations", "landing_page_url", "full_text_url",
    "download_url", "download_format", "download_status", "metadata_source",
    "metadata_match_status", "name_evidence_urls", "affiliation_evidence_urls",
    "download_evidence_urls", "evidence_locator", "checked_at",
]


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


def atomic_write_csv(path, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=CSV_FIELDS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            item = dict(row)
            for field, value in item.items():
                if isinstance(value, str):
                    item[field] = " ".join(value.split())
            for field in LIST_FIELDS:
                item[field] = json.dumps(item.get(field) or [], ensure_ascii=False)
            writer.writerow(item)
    os.replace(tmp, path)


def collapse_space(value):
    return " ".join((value or "").replace("\u200b", "").split())


def canonical_text(value):
    if not value:
        return None
    value = unicodedata.normalize("NFC", collapse_space(value))
    return value.translate(str.maketrans({
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    }))


def comparison_key(value):
    if not value:
        return None
    value = unicodedata.normalize("NFKD", value)
    value = "".join(character for character in value
                    if not unicodedata.combining(character))
    value = value.casefold().replace("‐", "-").replace("–", "-").replace("—", "-")
    return collapse_space(re.sub(r"[^\w]+", " ", value, flags=re.UNICODE))


def normalized_doi(value):
    value = collapse_space(value).casefold()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value)
    return value.rstrip("./") or None


def normalized_title(value):
    return comparison_key(value)


def normalize_name(raw, preferred=None):
    value = canonical_text(raw)
    if not value:
        return None, "unresolved", None
    notes = []
    if value != raw:
        notes.append("normalized whitespace and Unicode")
    if value.count(",") == 1:
        family, given = [collapse_space(part) for part in value.split(",", 1)]
        if family and given and all(any(character.isalpha() for character in part)
                                    for part in (family, given)):
            value = f"{given} {family}"
            notes.append("changed comma-order name to given-name-first display")
    if preferred and comparison_key(preferred) == comparison_key(value):
        preferred = canonical_text(preferred)
        if preferred != value:
            value = preferred
            notes.append("selected the persistent-metadata display variant")
    letters = "".join(character for character in value if character.isalpha())
    if (len(value.split()) > 1 and letters and
            (letters.isupper() or letters.islower()) and
            not any("CJK" in unicodedata.name(character, "") or
                    "HIRAGANA" in unicodedata.name(character, "") or
                    "KATAKANA" in unicodedata.name(character, "") or
                    "HANGUL" in unicodedata.name(character, "") for character in value)):
        value = value.title()
        notes.append("normalized all-upper/all-lower casing")
    return value, ("format_normalized" if notes else "unchanged"), "; ".join(notes) or None


def github_repo_from_url(url):
    match = re.match(r"^https?://(?:www\.)?github\.com/([^/]+)/([^/#?]+)", url or "", re.I)
    if not match:
        return None
    owner, name = match.groups()
    return f"{owner}/{name.removesuffix('.git')}"


def canonical_scope(index):
    duplicates = defaultdict(list)
    for record in index:
        if record.get("duplicate_of"):
            duplicates[record["duplicate_of"]].append(record["id"])
    records = []
    for record in index:
        if record.get("kind") == "code_repo" or record.get("duplicate_of"):
            continue
        item = dict(record)
        item["duplicate_sdv_ids"] = sorted(duplicates.get(record["id"], []))
        records.append(item)
    return records


def openalex_pool_indexes(pool):
    by_doi = {}
    by_title = {}
    for work in pool:
        if normalized_doi(work.get("doi")):
            by_doi.setdefault(normalized_doi(work.get("doi")), work)
        if normalized_title(work.get("title")):
            by_title.setdefault(normalized_title(work.get("title")), work)
    return by_doi, by_title


def openalex_id(value):
    match = re.search(r"W\d+", value or "", re.I)
    return match.group(0).upper() if match else None


def locate_openalex_seed(record, by_doi, by_title):
    work = None
    doi = normalized_doi(record.get("doi"))
    if doi:
        work = by_doi.get(doi)
    if work is None:
        work = by_title.get(normalized_title(record.get("title")))
    if work is None and "openalex.org/" in (record.get("url") or ""):
        return {"id": record["url"], "match_status": "index_openalex_url"}
    if work is None:
        return None
    return {"id": work.get("id"), "match_status": "offline_pool_match"}


def api_parameters():
    result = {}
    if os.environ.get("OPENALEX_API_KEY"):
        result["api_key"] = os.environ["OPENALEX_API_KEY"]
    elif os.environ.get("OPENALEX_EMAIL"):
        result["mailto"] = os.environ["OPENALEX_EMAIL"]
    return result


def get_json(url, headers=None, not_found=None):
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "sdvworld-publication-identity-harvest",
        **(headers or {}),
    })
    delay = 2
    for attempt in range(7):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410, 422):
                return not_found
            if exc.code not in (403, 429, 500, 502, 503, 504) or attempt == 6:
                raise
        except (TimeoutError, urllib.error.URLError):
            if attempt == 6:
                raise
        time.sleep(delay)
        delay = min(delay * 2, 30)
    return not_found


def get_html(url):
    request = urllib.request.Request(url, headers={
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "Mozilla/5.0 (compatible; SDVworld metadata harvester)",
    })
    delay = 2
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                content_type = response.headers.get_content_type()
                charset = response.headers.get_content_charset() or "utf-8"
                body = response.read(5_000_000)
                return {
                    "status": "ok",
                    "final_url": response.geturl(),
                    "content_type": content_type,
                    "text": body.decode(charset, errors="replace"),
                }
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                return {"status": "not_found", "http_status": exc.code}
            if exc.code not in (403, 429, 500, 502, 503, 504) or attempt == 5:
                return {"status": "http_error", "http_status": exc.code}
        except (TimeoutError, urllib.error.URLError) as exc:
            if attempt == 5:
                return {"status": "network_error", "error": str(exc)}
        time.sleep(delay)
        delay = min(delay * 2, 20)
    return {"status": "network_error"}


def selected_location(location):
    if not location:
        return None
    source = location.get("source") or {}
    return {
        "landing_page_url": location.get("landing_page_url"),
        "pdf_url": location.get("pdf_url"),
        "is_oa": location.get("is_oa"),
        "version": location.get("version"),
        "license": location.get("license"),
        "source_name": source.get("display_name"),
        "source_type": source.get("type"),
    }


def selected_openalex_work(work, match_status):
    return {
        "status": "ok",
        "match_status": match_status,
        "id": work.get("id"),
        "doi": work.get("doi"),
        "display_name": work.get("display_name") or work.get("title"),
        "publication_year": work.get("publication_year"),
        "type": work.get("type"),
        "open_access": work.get("open_access") or {},
        "primary_location": selected_location(work.get("primary_location")),
        "best_oa_location": selected_location(work.get("best_oa_location")),
        "locations": [selected_location(item) for item in work.get("locations") or []
                      if item.get("landing_page_url") or item.get("pdf_url")],
        "authorships": [
            {
                "author_position": item.get("author_position"),
                "is_corresponding": item.get("is_corresponding"),
                "raw_author_name": item.get("raw_author_name"),
                "raw_affiliation_strings": item.get("raw_affiliation_strings") or [],
                "author": {
                    "id": (item.get("author") or {}).get("id"),
                    "display_name": (item.get("author") or {}).get("display_name"),
                    "orcid": (item.get("author") or {}).get("orcid"),
                },
                "institutions": [
                    {
                        "id": institution.get("id"),
                        "display_name": institution.get("display_name"),
                        "ror": institution.get("ror"),
                        "country_code": institution.get("country_code"),
                        "type": institution.get("type"),
                    }
                    for institution in item.get("institutions") or []
                ],
            }
            for item in work.get("authorships") or []
        ],
        "fetched_at": today(),
    }


def fetch_openalex_batches(records, cache, pool):
    by_doi, by_title = openalex_pool_indexes(pool)
    seeds = {}
    for record in records:
        if record.get("kind") not in SCHOLARLY_KINDS:
            continue
        seed = locate_openalex_seed(record, by_doi, by_title)
        if seed and openalex_id(seed.get("id")):
            seeds[record["id"]] = seed

    missing = [(sdv_id, seed) for sdv_id, seed in seeds.items()
               if sdv_id not in cache["openalex_works"]]
    for start in range(0, len(missing), 40):
        batch = missing[start:start + 40]
        identifiers = [openalex_id(seed["id"]) for _, seed in batch]
        params = {
            "filter": "openalex_id:" + "|".join(identifiers),
            "per-page": 50,
            **api_parameters(),
        }
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
        payload = get_json(url, not_found={}) or {}
        returned = {openalex_id(work.get("id")): work
                    for work in payload.get("results") or []}
        for sdv_id, seed in batch:
            identifier = openalex_id(seed["id"])
            work = returned.get(identifier)
            if work:
                cache["openalex_works"][sdv_id] = selected_openalex_work(
                    work, seed["match_status"])
            else:
                cache["openalex_works"][sdv_id] = {
                    "status": "not_found", "seed_id": seed["id"],
                    "match_status": seed["match_status"], "fetched_at": today(),
                }
        checkpoint(cache)
        print(f"OpenAlex known works {min(start + len(batch), len(missing))}/{len(missing)}")

    unresolved = [record for record in records
                  if record.get("kind") in SCHOLARLY_KINDS and
                  record["id"] not in cache["openalex_works"]]
    for number, record in enumerate(unresolved, 1):
        params = {"search": record["title"], "per-page": 5, **api_parameters()}
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
        payload = get_json(url, not_found={}) or {}
        candidates = payload.get("results") or []
        record_doi = normalized_doi(record.get("doi"))
        work = next((item for item in candidates
                     if record_doi and normalized_doi(item.get("doi")) == record_doi), None)
        match_status = "online_doi_match"
        if work is None:
            work = next((item for item in candidates
                         if normalized_title(item.get("display_name")) ==
                         normalized_title(record.get("title"))), None)
            match_status = "online_exact_title_match"
        if work:
            cache["openalex_works"][record["id"]] = selected_openalex_work(
                work, match_status)
        else:
            cache["openalex_works"][record["id"]] = {
                "status": "not_found", "match_status": "online_search_no_exact_match",
                "fetched_at": today(),
            }
        if number % 10 == 0 or number == len(unresolved):
            checkpoint(cache)
            print(f"OpenAlex unresolved searches {number}/{len(unresolved)}")


def meta_content(document, key):
    patterns = [
        rf'<meta[^>]+(?:name|property)=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']*)',
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:name|property)=["\']{re.escape(key)}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, document, re.I)
        if match:
            return canonical_text(html.unescape(match.group(1)))
    return None


def json_ld_nodes(document):
    nodes = []
    pattern = r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
    for raw in re.findall(pattern, document, re.I | re.S):
        try:
            payload = json.loads(html.unescape(raw).strip())
        except (json.JSONDecodeError, TypeError):
            continue
        values = payload if isinstance(payload, list) else [payload]
        for value in values:
            if not isinstance(value, dict):
                continue
            graph = value.get("@graph")
            if isinstance(graph, list):
                nodes.extend(item for item in graph if isinstance(item, dict))
            else:
                nodes.append(value)
    return nodes


def type_names(node):
    value = node.get("@type")
    return set(value if isinstance(value, list) else [value])


def person_items(value):
    if not value:
        return []
    values = value if isinstance(value, list) else [value]
    result = []
    for item in values:
        if isinstance(item, str):
            result.append({"name": canonical_text(item), "type": "Person"})
        elif isinstance(item, dict):
            types = type_names(item)
            result.append({
                "name": canonical_text(item.get("name")),
                "type": "Organization" if "Organization" in types else "Person",
                "url": item.get("url") or item.get("@id"),
                "description": canonical_text(item.get("description")),
                "same_as": item.get("sameAs") or [],
            })
    return [item for item in result if item.get("name")]


def extract_web_metadata(url, document, final_url):
    nodes = json_ld_nodes(document)
    organizations = [node for node in nodes if "Organization" in type_names(node)]
    articles = [node for node in nodes if type_names(node) & ARTICLE_TYPES]
    article = next((node for node in articles if node.get("author")), None)
    if article is None and articles:
        article = articles[0]
    article = article or {}
    authors = person_items(article.get("author") or article.get("creator"))
    if not authors:
        meta_author = meta_content(document, "author") or meta_content(document, "article:author")
        if meta_author:
            authors = [{"name": meta_author, "type": "Person"}]

    publisher = article.get("publisher")
    if isinstance(publisher, dict) and publisher.get("@id"):
        publisher = next((node for node in organizations
                          if node.get("@id") == publisher.get("@id")), publisher)
    elif not isinstance(publisher, dict):
        publisher = organizations[0] if organizations else None
    publisher = publisher or {}

    download = (article.get("contentUrl") or meta_content(document, "citation_pdf_url") or
                meta_content(document, "wkhealth_pdf_url"))
    if download:
        download = urllib.parse.urljoin(final_url or url, download)
    title = canonical_text(article.get("headline") or article.get("name") or
                           meta_content(document, "og:title"))
    return {
        "status": "ok",
        "final_url": final_url or url,
        "title": title,
        "date_published": article.get("datePublished") or meta_content(document, "article:published_time"),
        "date_modified": article.get("dateModified") or meta_content(document, "article:modified_time"),
        "authors": authors,
        "publisher": {
            "name": canonical_text(publisher.get("name")),
            "legal_name": canonical_text(publisher.get("legalName")),
            "url": publisher.get("url") or publisher.get("@id"),
        },
        "download_url": download,
        "fetched_at": today(),
    }


def fetch_web_pages(records, cache, max_web=None):
    todo = [record for record in records
            if record.get("kind") not in SCHOLARLY_KINDS and
            not github_repo_from_url(record.get("url")) and
            record["id"] not in cache["web_pages"]]
    if max_web is not None:
        todo = todo[:max_web]
    for number, record in enumerate(todo, 1):
        response = get_html(record["url"])
        if response.get("status") == "ok" and response.get("content_type") in {
                "text/html", "application/xhtml+xml"}:
            cache["web_pages"][record["id"]] = extract_web_metadata(
                record["url"], response["text"], response.get("final_url"))
        else:
            cache["web_pages"][record["id"]] = {
                key: value for key, value in response.items() if key != "text"
            }
            cache["web_pages"][record["id"]]["fetched_at"] = today()
        if number % 10 == 0 or number == len(todo):
            checkpoint(cache)
            print(f"web publications {number}/{len(todo)}")

    profile_urls = {}
    for page in cache["web_pages"].values():
        publisher = page.get("publisher") or {}
        for author in page.get("authors") or []:
            url = author.get("url")
            if url and url.startswith("http"):
                profile_urls.setdefault(url, publisher)
    profile_todo = [item for item in sorted(profile_urls) if item not in cache["web_profiles"]]
    for number, url in enumerate(profile_todo, 1):
        response = get_html(url)
        if response.get("status") == "ok" and response.get("content_type") in {
                "text/html", "application/xhtml+xml"}:
            nodes = json_ld_nodes(response["text"])
            person = next((node for node in nodes if "Person" in type_names(node)), {})
            cache["web_profiles"][url] = {
                "status": "ok",
                "final_url": response.get("final_url") or url,
                "name": canonical_text(person.get("name") or meta_content(response["text"], "og:title")),
                "description": canonical_text(person.get("description") or
                                              meta_content(response["text"], "description") or
                                              meta_content(response["text"], "og:description")),
                "fetched_at": today(),
            }
        else:
            cache["web_profiles"][url] = {
                key: value for key, value in response.items() if key != "text"
            }
            cache["web_profiles"][url]["fetched_at"] = today()
        if number % 10 == 0 or number == len(profile_todo):
            checkpoint(cache)
            print(f"web author profiles {number}/{len(profile_todo)}")


def cache_payload(cache):
    return {
        "note": (
            "Resumable public metadata for publication-scoped author and affiliation rows. "
            "OpenAlex institutions and web-page JSON-LD are metadata claims; status fields "
            "distinguish them from affiliations checked directly in full text."
        ),
        "generated": today(),
        "openalex_works": cache["openalex_works"],
        "web_pages": cache["web_pages"],
        "web_profiles": cache["web_profiles"],
    }


def checkpoint(cache):
    atomic_write(CACHE, cache_payload(cache))


def normalize_cache(raw):
    return {
        "openalex_works": dict(raw.get("openalex_works") or {}),
        "web_pages": dict(raw.get("web_pages") or {}),
        "web_profiles": dict(raw.get("web_profiles") or {}),
    }


def unique_urls(values):
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def location_urls(record, work):
    locations = [work.get("best_oa_location"), work.get("primary_location")]
    locations.extend(work.get("locations") or [])
    landing = None
    download = None
    for location in locations:
        if not location:
            continue
        if not landing and location.get("landing_page_url"):
            landing = location["landing_page_url"]
        if not download and location.get("pdf_url"):
            download = location["pdf_url"]
    index_url = record.get("url")
    if index_url and ("/pdf/" in index_url.casefold() or index_url.casefold().endswith(".pdf")):
        download = index_url
    if not landing:
        landing = index_url
    arxiv_match = re.search(r"(?:arxiv[.:/])([0-9]{4}\.[0-9]{4,5})(?:v\d+)?", (
        record.get("doi") or record.get("url") or ""), re.I)
    if not download and arxiv_match:
        download = "https://arxiv.org/pdf/" + arxiv_match.group(1)
        landing = landing or "https://arxiv.org/abs/" + arxiv_match.group(1)
    return {
        "landing_page_url": landing,
        "full_text_url": download or landing,
        "download_url": download,
        "download_format": "pdf" if download else None,
        "download_status": ("direct_open_access_metadata" if download else
                            "landing_page_only" if landing else "unresolved"),
        "download_evidence_urls": unique_urls([
            work.get("id"), download, landing,
        ]),
    }


def base_row(record):
    return {
        "sdv_id": record["id"],
        "duplicate_sdv_ids": record.get("duplicate_sdv_ids") or [],
        "kind": record.get("kind"),
        "title": record.get("title"),
        "year": record.get("year"),
        "source_channel": record.get("source_channel"),
    }


def identity_key(orcid=None, openalex=None, github_id=None, profile=None,
                 sdv_id=None, position=None, name=None, account_type="person"):
    if orcid:
        return orcid, "persistent_id"
    if openalex:
        return openalex, "persistent_id"
    if github_id is not None:
        return f"github:{github_id}", "persistent_id"
    if profile:
        return f"profile:{profile}", "source_profile"
    if account_type == "organization" and name:
        return f"organization:{comparison_key(name)}", "organization_byline"
    if name:
        return f"publication:{sdv_id}:{position}:{comparison_key(name)}", "publication_scoped_name"
    return f"publication:{sdv_id}:unattributed", "unattributed"


def normalize_affiliation(raw, affiliation_mappings, institution=None,
                          source_status="metadata_stated"):
    institution = institution or {}
    mapping = affiliation_mappings.get(raw) or next((
        value for key, value in affiliation_mappings.items()
        if raw and comparison_key(key) == comparison_key(raw)
    ), {})
    ror_id = institution.get("ror") or mapping.get("ror_id")
    canonical = mapping.get("canonical_name") or institution.get("display_name") or raw
    if not raw and not canonical:
        return {
            "affiliation_raw": None,
            "affiliation": None,
            "affiliation_source_status": "unresolved",
            "affiliation_normalization_status": "unresolved",
            "affiliation_country": None,
            "affiliation_country_code": None,
            "affiliation_type": None,
            "affiliation_ror_id": None,
            "affiliation_evidence_urls": [],
        }
    status = mapping.get("status")
    if not status:
        status = "ror_confirmed" if ror_id else "metadata_canonical_name"
    evidence = list(mapping.get("evidence_urls") or [])
    if ror_id and ror_id not in evidence:
        evidence.append(ror_id)
    return {
        "affiliation_raw": raw or canonical,
        "affiliation": canonical,
        "affiliation_source_status": source_status,
        "affiliation_normalization_status": status,
        "affiliation_country": mapping.get("country"),
        "affiliation_country_code": institution.get("country_code"),
        "affiliation_type": mapping.get("organization_type") or institution.get("type"),
        "affiliation_ror_id": ror_id,
        "affiliation_evidence_urls": evidence,
    }


def author_index_name(record, index, source_name):
    authors = record.get("authors") or []
    source_key = comparison_key(normalize_name(source_name)[0])
    if index < len(authors):
        indexed_name = authors[index]
        if comparison_key(normalize_name(indexed_name)[0]) == source_key:
            return indexed_name
    match = next((name for name in authors
                  if comparison_key(normalize_name(name)[0]) == source_key), None)
    return match or source_name or (authors[index] if index < len(authors) else None)


def build_scholarly_rows(record, work, affiliation_mappings, overrides,
                         openalex_to_orcid):
    rows = []
    work = work if work and work.get("status") == "ok" else {}
    urls = location_urls(record, work)
    authorships = work.get("authorships") or []
    indexed_authors = record.get("authors") or []
    if authorships and len(indexed_authors) > len(authorships):
        # OpenAlex occasionally exposes a truncated byline.  When every returned
        # name is also present in the curator-recorded byline, keep the richer
        # shard order and synthesize only the missing authorship shells.  Curated
        # overrides can then attach source-checked affiliations by position.
        by_name = defaultdict(list)
        for authorship in authorships:
            author = authorship.get("author") or {}
            source_name = author.get("display_name") or authorship.get("raw_author_name")
            by_name[comparison_key(normalize_name(source_name)[0])].append(authorship)
        indexed_keys = [comparison_key(normalize_name(name)[0]) for name in indexed_authors]
        source_keys = [key for key, values in by_name.items() for _ in values]
        if all(key in indexed_keys for key in source_keys):
            rebuilt = []
            for index, name in enumerate(indexed_authors):
                key = comparison_key(normalize_name(name)[0])
                if by_name.get(key):
                    rebuilt.append(by_name[key].pop(0))
                else:
                    rebuilt.append({
                        "author_position": ("first" if index == 0 else
                                            "last" if index == len(indexed_authors) - 1 else
                                            "middle"),
                        "raw_author_name": name,
                        "raw_affiliation_strings": [],
                        "author": {"display_name": name},
                        "institutions": [],
                    })
            authorships = rebuilt
    if not authorships:
        authorships = [
            {
                "author_position": ("first" if index == 0 else
                                    "last" if index == len(record.get("authors") or []) - 1 else
                                    "middle"),
                "raw_author_name": name,
                "raw_affiliation_strings": [],
                "author": {"display_name": name},
                "institutions": [],
            }
            for index, name in enumerate(indexed_authors)
        ]
    for index, authorship in enumerate(authorships):
        override = overrides.get(f"{record['id']}#{index + 1}") or {}
        if override.get("exclude"):
            continue
        author = authorship.get("author") or {}
        source_name = author.get("display_name") or authorship.get("raw_author_name")
        raw_name = override.get("public_name_raw") or author_index_name(
            record, index, source_name)
        public_name, name_norm_status, name_note = normalize_name(raw_name, source_name)
        public_name = override.get("public_name") or public_name
        name_norm_status = override.get("name_normalization_status") or name_norm_status
        name_note = override.get("name_normalization_note") or name_note
        author_orcid = (override.get("author_orcid") if "author_orcid" in override else
                        author.get("orcid") or openalex_to_orcid.get(author.get("id")))
        author_openalex_id = (override.get("author_openalex_id")
                              if "author_openalex_id" in override else author.get("id"))
        author_key, identity_status = identity_key(
            orcid=author_orcid, openalex=author_openalex_id,
            sdv_id=record["id"], position=index + 1, name=public_name)
        author_key = override.get("author_identity_key") or author_key
        identity_status = override.get("identity_status") or identity_status
        institutions = authorship.get("institutions") or [None]
        for aff_index, institution in enumerate(institutions, 1):
            institution = institution or {}
            raw_affiliations = authorship.get("raw_affiliation_strings") or []
            raw_affiliation = institution.get("display_name")
            if len(raw_affiliations) == 1:
                raw_affiliation = raw_affiliations[0]
            affiliation = normalize_affiliation(
                raw_affiliation, affiliation_mappings, institution,
                source_status=("openalex_authorship_metadata" if institution else "unresolved"))
            evidence_url = ("https://api.openalex.org/works/" + openalex_id(work.get("id"))
                            if openalex_id(work.get("id")) else None)
            affiliation["affiliation_evidence_urls"] = unique_urls(
                [evidence_url] + affiliation["affiliation_evidence_urls"])
            if override:
                affiliation.update({key: value for key, value in override.items()
                                    if key == "affiliation" or
                                    key.startswith("affiliation_")})
                affiliation["affiliation_evidence_urls"] = unique_urls(
                    (override.get("affiliation_evidence_urls") or []) +
                    affiliation.get("affiliation_evidence_urls", []))
            row_urls = dict(urls)
            for field in ("landing_page_url", "full_text_url", "download_url",
                          "download_format", "download_status"):
                if field in override:
                    row_urls[field] = override[field]
            row_urls["download_evidence_urls"] = unique_urls(
                (override.get("download_evidence_urls") or []) +
                row_urls.get("download_evidence_urls", []))
            rows.append({
                **base_row(record),
                "author_position": index + 1,
                "author_role": (override.get("author_role") or
                                authorship.get("author_position") or "author"),
                "account_type": "person",
                "author_identity_key": author_key,
                "identity_status": identity_status,
                "public_name_raw": raw_name,
                "public_name": public_name,
                "name_source_status": (override.get("name_source_status") or
                                       "publication_stated" if override else
                                       "openalex_authorship_metadata" if work else
                                       "index_stated"),
                "name_normalization_status": name_norm_status,
                "name_normalization_note": name_note,
                "author_orcid": author_orcid,
                "author_openalex_id": author_openalex_id,
                "github_user_id": None,
                "github_login": None,
                "author_profile_url": (override.get("author_profile_url") or
                                       author_openalex_id),
                "affiliation_position": aff_index if institution else None,
                **affiliation,
                "affiliation_unit": override.get("affiliation_unit"),
                "raw_affiliation_strings": raw_affiliations,
                "unmapped_publication_affiliations": (
                    (record.get("affiliations") or []) if not institution else []),
                **row_urls,
                "metadata_source": (override.get("metadata_source") or
                                    ("OpenAlex" if work else "SDVworld index")),
                "metadata_match_status": (override.get("metadata_match_status") or
                                          work.get("match_status") or "unresolved"),
                "name_evidence_urls": unique_urls(
                    (override.get("name_evidence_urls") or []) + [evidence_url]),
                "download_evidence_urls": row_urls["download_evidence_urls"],
                "evidence_locator": override.get("evidence_locator"),
                "checked_at": override.get("checked_at") or work.get("fetched_at") or today(),
            })
    return rows


def publisher_affiliation(author, page, profile, affiliation_mappings):
    publisher = page.get("publisher") or {}
    publisher_name = publisher.get("name")
    legal_name = publisher.get("legal_name")
    description = " ".join(filter(None, [author.get("description"),
                                          (profile or {}).get("description")]))
    author_name = author.get("name") or ""
    account_type = ("organization" if author.get("type") == "Organization" or
                    author_name.casefold().endswith(" team") else "person")
    if account_type == "organization":
        return account_type, normalize_affiliation(
            None, affiliation_mappings, source_status="not_applicable")
    publisher_tokens = [value for value in (publisher_name, legal_name) if value]
    mentions = any(value.casefold() in description.casefold() for value in publisher_tokens)
    team_byline = author_name.casefold().endswith(" team") and publisher_name
    if mentions or team_byline:
        normalized = normalize_affiliation(
            publisher_name or legal_name, affiliation_mappings,
            source_status="official_author_profile_stated")
        if legal_name:
            normalized["affiliation"] = legal_name
            normalized["affiliation_normalization_status"] = "official_source_confirmed"
        return account_type, normalized
    return account_type, normalize_affiliation(
        None, affiliation_mappings, source_status="unresolved")


def build_web_rows(record, page, profiles, affiliation_mappings):
    page = page if page and page.get("status") == "ok" else {}
    authors = [dict(author, _source="official_page")
               for author in page.get("authors") or []]
    seen_names = {comparison_key(author.get("name")) for author in authors}
    for name in record.get("authors") or []:
        if comparison_key(name) in seen_names:
            continue
        authors.append({
            "name": name,
            "type": "Organization" if name.casefold().endswith(" team") else "Person",
            "_source": "sdv_index",
        })
        seen_names.add(comparison_key(name))
    if not authors:
        authors = [{"name": None, "type": "Unknown", "_source": "unattributed"}]
    rows = []
    for index, author in enumerate(authors, 1):
        raw_name = author.get("name")
        public_name, name_norm_status, name_note = normalize_name(raw_name)
        source = author.get("_source")
        profile_url = author.get("url") if source == "official_page" else None
        profile = profiles.get(profile_url) if profile_url else None
        account_type, affiliation = publisher_affiliation(
            author, page, profile, affiliation_mappings)
        if account_type == "organization":
            publisher = page.get("publisher") or {}
            organization_name = publisher.get("legal_name") or publisher.get("name")
            if organization_name and raw_name and raw_name.casefold().endswith(" team"):
                normalized_organization = normalize_affiliation(
                    organization_name, affiliation_mappings,
                    source_status="official_page_publisher")
                public_name = (normalized_organization.get("affiliation") or
                               organization_name)
                name_norm_status = "organization_canonicalized"
                name_note = "replaced the team byline with the official publisher name"
        if not affiliation.get("affiliation") and len(record.get("affiliations") or []) == 1:
            affiliation = normalize_affiliation(
                record["affiliations"][0], affiliation_mappings,
                source_status="publication_level_shared_unconfirmed")
        author_key, identity_status = identity_key(
            profile=profile_url, sdv_id=record["id"], position=index,
            name=public_name, account_type=account_type)
        page_url = page.get("final_url") or record.get("url")
        download = page.get("download_url")
        if not download:
            download = page_url
        format_name = "pdf" if download and download.casefold().endswith(".pdf") else "html"
        rows.append({
            **base_row(record),
            "author_position": index if raw_name else None,
            "author_role": ("organization_byline" if account_type == "organization" else
                            "byline" if source == "official_page" else
                            "index_author" if raw_name else "unattributed"),
            "account_type": account_type if raw_name else "unknown",
            "author_identity_key": author_key,
            "identity_status": identity_status,
            "public_name_raw": raw_name,
            "public_name": public_name,
            "name_source_status": ("official_page_byline" if source == "official_page" else
                                   "index_stated" if raw_name else "unattributed"),
            "name_normalization_status": name_norm_status,
            "name_normalization_note": name_note,
            "author_orcid": None,
            "author_openalex_id": None,
            "github_user_id": None,
            "github_login": None,
            "author_profile_url": profile_url,
            "affiliation_position": 1 if affiliation.get("affiliation") else None,
            **affiliation,
            "affiliation_unit": None,
            "raw_affiliation_strings": [],
            "unmapped_publication_affiliations": (
                (record.get("affiliations") or [])
                if not affiliation.get("affiliation") else []),
            "landing_page_url": page_url,
            "full_text_url": download or page_url,
            "download_url": download,
            "download_format": format_name,
            "download_status": ("direct_pdf_metadata" if format_name == "pdf" else
                                "direct_html_confirmed" if page else "landing_page_only"),
            "metadata_source": ("official_page_json_ld" if source == "official_page" else
                                "SDVworld index + official page" if page and raw_name else
                                "SDVworld index"),
            "metadata_match_status": ("index_additional_author" if source == "sdv_index" else
                                      page.get("status") or "unresolved"),
            "name_evidence_urls": unique_urls([page_url, profile_url]),
            "affiliation_evidence_urls": unique_urls(
                [page_url, profile_url, (page.get("publisher") or {}).get("url")] +
                affiliation.get("affiliation_evidence_urls", [])),
            "download_evidence_urls": unique_urls([download, page_url]),
            "evidence_locator": ("page JSON-LD and official author profile"
                                 if source == "official_page"
                                 else None),
            "checked_at": page.get("fetched_at") or today(),
        })
    return rows


def build_github_rows(record, github_rows):
    rows = []
    order = {comparison_key(value): index + 1
             for index, value in enumerate(record.get("authors") or [])}
    for fallback_index, source in enumerate(github_rows, 1):
        public_name = source.get("public_name")
        raw_name = source.get("public_name_raw") or public_name or source.get("raw_author")
        position = (order.get(comparison_key(source.get("raw_author"))) or
                    order.get(comparison_key(source.get("github_login"))) or
                    order.get(comparison_key(public_name)) or fallback_index)
        author_key, identity_status = identity_key(
            github_id=source.get("github_user_id"), sdv_id=record["id"],
            position=position, name=public_name,
            account_type=source.get("account_type") or "unknown")
        rows.append({
            **base_row(record),
            "github_repo_id": source.get("github_repo_id"),
            "github_repo": source.get("github_repo"),
            "github_repo_url": source.get("github_repo_url"),
            "author_position": position,
            "author_role": "; ".join(source.get("roles") or []),
            "account_type": source.get("account_type"),
            "author_identity_key": author_key,
            "identity_status": identity_status,
            "public_name_raw": raw_name,
            "public_name": public_name,
            "name_source_status": source.get("name_status"),
            "name_normalization_status": source.get("name_normalization_status"),
            "name_normalization_note": source.get("name_normalization_note"),
            "author_orcid": None,
            "author_openalex_id": None,
            "github_user_id": source.get("github_user_id"),
            "github_login": source.get("github_login"),
            "author_profile_url": source.get("profile_url"),
            "affiliation_position": 1 if source.get("affiliation") else None,
            "affiliation_raw": source.get("affiliation_raw"),
            "affiliation": source.get("affiliation"),
            "affiliation_unit": None,
            "affiliation_source_status": source.get("affiliation_source_status"),
            "affiliation_normalization_status": source.get("affiliation_status"),
            "affiliation_country": source.get("affiliation_country"),
            "affiliation_country_code": None,
            "affiliation_type": source.get("affiliation_type"),
            "affiliation_ror_id": source.get("affiliation_ror_id"),
            "raw_affiliation_strings": [],
            "unmapped_publication_affiliations": [],
            "landing_page_url": record.get("url"),
            "full_text_url": record.get("url"),
            "download_url": record.get("url"),
            "download_format": "github_repository",
            "download_status": "repository_source_confirmed",
            "metadata_source": "github_identity_join",
            "metadata_match_status": source.get("identity_source"),
            "name_evidence_urls": source.get("name_evidence_urls") or [],
            "affiliation_evidence_urls": source.get("affiliation_evidence_urls") or [],
            "download_evidence_urls": [record.get("url")],
            "evidence_locator": None,
            "checked_at": source.get("checked_at"),
        })
    return rows


def publication_coverage(records, rows):
    """Return one audit row per canonical SDVworld publication ID."""
    rows_by_sdv = defaultdict(list)
    for row in rows:
        rows_by_sdv[row["sdv_id"]].append(row)
    coverage = []
    for record in records:
        publication_rows = rows_by_sdv[record["id"]]
        by_identity = defaultdict(list)
        for row in publication_rows:
            by_identity[row["author_identity_key"]].append(row)
        display_authors = []
        named_identities = 0
        affiliated_identities = 0
        unresolved_real_names = 0
        for identity_rows in by_identity.values():
            sample = identity_rows[0]
            display = (sample.get("public_name") or sample.get("github_login") or
                       sample.get("public_name_raw"))
            if display:
                named_identities += 1
                display_authors.append(display)
            if any(item.get("affiliation") for item in identity_rows):
                affiliated_identities += 1
            if sample.get("github_login") and not sample.get("public_name"):
                unresolved_real_names += 1

        direct_pdf_urls = unique_urls([
            row.get("download_url") for row in publication_rows
            if row.get("download_format") == "pdf"
        ])
        download_urls = unique_urls([
            row.get("download_url") for row in publication_rows
            if row.get("download_url")
        ])
        if direct_pdf_urls:
            download_status = "direct_pdf_metadata"
        elif any(row.get("download_format") == "html" for row in publication_rows):
            download_status = "direct_html_confirmed"
        elif any(row.get("download_format") == "github_repository"
                 for row in publication_rows):
            download_status = "repository_source_confirmed"
        elif download_urls:
            download_status = "landing_or_content_link"
        else:
            download_status = "unresolved"

        flags = []
        if not named_identities:
            flags.append("no_named_author_or_account")
        if unresolved_real_names:
            flags.append("github_real_name_unresolved")
        if not affiliated_identities:
            flags.append("no_author_affiliation")
        elif affiliated_identities < len(by_identity):
            flags.append("partial_author_affiliation")
        if record.get("kind") in SCHOLARLY_KINDS and not direct_pdf_urls:
            flags.append("no_direct_pdf_metadata")
        if any((row.get("metadata_match_status") or "unresolved") == "unresolved"
               for row in publication_rows):
            flags.append("metadata_match_unresolved")

        affiliations = []
        for row in publication_rows:
            value = row.get("affiliation")
            if value and value not in affiliations:
                affiliations.append(value)
        coverage.append({
            "sdv_id": record["id"],
            "duplicate_sdv_ids": record.get("duplicate_sdv_ids") or [],
            "kind": record.get("kind"),
            "title": record.get("title"),
            "year": record.get("year"),
            "source_channel": record.get("source_channel"),
            "index_url": record.get("url"),
            "author_relationships": len(by_identity),
            "authors_with_name_or_handle": named_identities,
            "authors_with_affiliation": affiliated_identities,
            "authors": display_authors,
            "affiliations": affiliations,
            "metadata_sources": sorted({
                row.get("metadata_source") or "unresolved" for row in publication_rows}),
            "metadata_match_statuses": sorted({
                row.get("metadata_match_status") or "unresolved"
                for row in publication_rows}),
            "landing_page_url": next((row.get("landing_page_url")
                                      for row in publication_rows
                                      if row.get("landing_page_url")), None),
            "direct_pdf_url": direct_pdf_urls[0] if direct_pdf_urls else None,
            "download_url": (direct_pdf_urls or download_urls or [None])[0],
            "download_status": download_status,
            "review_status": "needs_review" if flags else "complete_metadata",
            "review_flags": flags,
        })
    return coverage


def build_table(records, cache):
    affiliation_mappings = load(AFFILIATION_NORMALIZATIONS, {}).get("mappings", {})
    overrides = load(CURATED_OVERRIDES, {}).get("mappings", {})
    github_payload = load(GITHUB_AUTHORS, {})
    github_by_sdv = defaultdict(list)
    for row in github_payload.get("rows") or []:
        for sdv_id in row.get("sdv_repo_ids") or []:
            github_by_sdv[sdv_id].append(row)
    openalex_to_orcid = {}
    for work in cache["openalex_works"].values():
        for authorship in work.get("authorships") or []:
            author = authorship.get("author") or {}
            if author.get("id") and author.get("orcid"):
                openalex_to_orcid[author["id"]] = author["orcid"]

    rows = []
    for record in records:
        if record.get("kind") in SCHOLARLY_KINDS:
            work = cache["openalex_works"].get(record["id"])
            joined = github_by_sdv.get(record["id"])
            if (not work or work.get("status") != "ok") and joined:
                rows.extend(build_github_rows(record, joined))
            else:
                rows.extend(build_scholarly_rows(
                    record, work, affiliation_mappings, overrides,
                    openalex_to_orcid))
        elif github_repo_from_url(record.get("url")):
            joined = github_by_sdv.get(record["id"])
            if joined:
                rows.extend(build_github_rows(record, joined))
            else:
                rows.extend(build_web_rows(record, None, {}, affiliation_mappings))
        else:
            rows.extend(build_web_rows(
                record, cache["web_pages"].get(record["id"]),
                cache["web_profiles"], affiliation_mappings))

    rows.sort(key=lambda row: (
        (row.get("sdv_id") or "").casefold(),
        row.get("author_position") or 999999,
        row.get("affiliation_position") or 999999,
        (row.get("public_name") or "").casefold(),
    ))
    unique_publications = {row["sdv_id"] for row in rows}
    relationships = {(row["sdv_id"], row["author_identity_key"]) for row in rows}
    relationships_with_name = {
        (row["sdv_id"], row["author_identity_key"]) for row in rows
        if row.get("public_name") or row.get("github_login")
    }
    relationships_with_affiliation = {
        (row["sdv_id"], row["author_identity_key"]) for row in rows
        if row.get("affiliation")
    }
    counts = {
        "publications": len(unique_publications),
        "author_affiliation_rows": len(rows),
        "publication_author_relationships": len(relationships),
        "author_relationships_with_name_or_handle": len(relationships_with_name),
        "author_relationships_with_affiliation": len(relationships_with_affiliation),
        "unique_persistent_author_identities": len({
            row["author_identity_key"] for row in rows
            if row.get("identity_status") == "persistent_id"
        }),
        "rows_with_public_name": sum(bool(row.get("public_name")) for row in rows),
        "rows_with_affiliation": sum(bool(row.get("affiliation")) for row in rows),
        "rows_with_persistent_author_id": sum(
            row.get("identity_status") == "persistent_id" for row in rows),
        "publications_with_download_url": len({
            row["sdv_id"] for row in rows if row.get("download_url")}),
        "publications_with_direct_pdf": len({
            row["sdv_id"] for row in rows if row.get("download_format") == "pdf"}),
        "publications_with_name_or_handle": len({
            row["sdv_id"] for row in rows
            if row.get("public_name") or row.get("github_login")}),
        "publications_with_affiliation": len({
            row["sdv_id"] for row in rows if row.get("affiliation")}),
        "scholarly_publications": sum(record.get("kind") in SCHOLARLY_KINDS
                                       for record in records),
        "web_publications": sum(record.get("kind") not in SCHOLARLY_KINDS and
                                 not github_repo_from_url(record.get("url"))
                                 for record in records),
        "github_hosted_non_code_publications": sum(
            bool(github_repo_from_url(record.get("url"))) for record in records),
        "unattributed_publications": len({
            row["sdv_id"] for row in rows if row.get("name_source_status") == "unattributed"}),
    }
    for key, counter in (
        ("by_kind", Counter(row.get("kind") or "unknown" for row in rows)),
        ("by_name_source_status", Counter(row.get("name_source_status") or "unresolved"
                                          for row in rows)),
        ("by_affiliation_source_status", Counter(
            row.get("affiliation_source_status") or "unresolved" for row in rows)),
        ("by_download_status", Counter(row.get("download_status") or "unresolved"
                                       for row in rows)),
        ("by_metadata_source", Counter(row.get("metadata_source") or "unresolved"
                                       for row in rows)),
    ):
        counts[key] = dict(sorted(counter.items()))
    payload = {
        "note": (
            "Generated publication-scoped author and affiliation table. One row represents "
            "one SDVworld publication-author-affiliation relationship. Affiliations may "
            "therefore change for the same person across publications. Raw source values, "
            "canonical values, direct content/download links, persistent IDs, statuses, "
            "and evidence URLs are kept separately. Distinct people are never merged by "
            "name alone."
        ),
        "generated": today(),
        "counts": counts,
        "publication_coverage": publication_coverage(records, rows),
        "rows": rows,
    }
    atomic_write(OUT, payload)
    atomic_write_csv(OUT_CSV, rows)
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true",
                        help="build outputs from the current cache without network calls")
    parser.add_argument("--refresh", action="store_true",
                        help="discard the publication metadata cache before fetching")
    parser.add_argument("--max-web", type=int,
                        help="limit official web-page fetches for a test run")
    args = parser.parse_args()

    records = canonical_scope(load(INDEX, []))
    raw_cache = {} if args.refresh else load(CACHE, {})
    cache = normalize_cache(raw_cache)
    print(f"prepared {len(records)} canonical non-code SDVworld records")
    if not args.prepare_only:
        fetch_openalex_batches(records, cache, load(OPENALEX_POOL, []))
        fetch_web_pages(records, cache, args.max_web)
        checkpoint(cache)
    counts = build_table(records, cache)
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
