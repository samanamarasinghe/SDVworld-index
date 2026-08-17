#!/usr/bin/env python3
"""Build a provenance-bearing GitHub repository-author identity table.

The existing repository pool stores an owner plus up to five contributor strings.
Some strings are GitHub logins, some are anonymous Git author names, and the owner
is often repeated as a contributor.  This script preserves those distinctions,
deduplicates within a repository, and enriches resolvable logins with public GitHub
profile metadata.

The GitHub token is read only from GITHUB_TOKEN and is never written to disk.

    GITHUB_TOKEN=<read-only token> python3 harvest/github_identities.py

Outputs:
  data/tail/github-identities.json  resumable raw GitHub metadata cache
  data/github-repo-authors.json     generated flat repo-author table
  data/github-repo-authors.csv      reviewable/importable version of the table

Both outputs contain public professional metadata only.  Email addresses are not
requested or stored.  A GitHub profile name/company is labelled profile_stated,
not treated as a verified legal identity or employment claim.
"""

import argparse
import csv
import datetime
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "data", "sdv-index.json")
REPO_POOL = os.path.join(ROOT, "data", "tail", "github-repos.json")
CACHE = os.path.join(ROOT, "data", "tail", "github-identities.json")
OUT = os.path.join(ROOT, "data", "github-repo-authors.json")
OUT_CSV = os.path.join(ROOT, "data", "github-repo-authors.csv")
AFFILIATION_NORMALIZATIONS = os.path.join(ROOT, "data", "affiliation-normalizations.json")
PUBLIC_NAME_NORMALIZATIONS = os.path.join(ROOT, "data", "public-name-normalizations.json")
GRAPHQL = "https://api.github.com/graphql"
LOGIN_RE = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?|[A-Za-z0-9-]+\[bot\])$")
GITHUB_URL_RE = re.compile(r"^https?://(?:www\.)?github\.com/([^/]+)/([^/#?]+)", re.I)
SERVICE_ACCOUNT_LOGINS = {
    "actions-user": "known automation-style account",
    "claude": "shared Anthropic automation account",
    "copybara-github": "Copybara synchronization service",
    "web-flow": "GitHub web-flow service",
}
SERVICE_ACCOUNT_RE = re.compile(r"(?:^|[-_])bot(?:[-_]|$)", re.I)


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
    fields = [
        "sdv_repo_ids", "github_repo_id", "github_repo", "github_repo_url",
        "repo_status", "raw_author", "roles", "contributions", "identity_source",
        "verified_github_link", "github_user_id", "github_login",
        "github_account_type", "account_type", "account_classification_status",
        "account_classification_reason", "public_name_raw", "public_name", "name_status",
        "name_normalization_status", "name_normalization_note", "canonical_name_key",
        "same_name_github_account_count", "public_name_variants", "affiliation_raw",
        "affiliation", "affiliation_status", "affiliation_source_status",
        "affiliation_country", "affiliation_type", "affiliation_ror_id",
        "affiliation_normalization_note", "profile_url", "name_evidence_urls",
        "affiliation_evidence_urls", "checked_at",
    ]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            item = dict(row)
            for field, value in item.items():
                if isinstance(value, str):
                    item[field] = " ".join(value.split())
            for field in ("sdv_repo_ids", "roles", "public_name_variants", "name_evidence_urls",
                          "affiliation_evidence_urls"):
                item[field] = json.dumps(item.get(field) or [], ensure_ascii=False)
            writer.writerow(item)
    os.replace(tmp, path)


def repo_from_url(url):
    match = GITHUB_URL_RE.match(url or "")
    if not match:
        return None
    owner, name = match.groups()
    if name.lower().endswith(".git"):
        name = name[:-4]
    return f"{owner}/{name}"


def identity_key(raw):
    return (raw or "").strip().casefold()


def classify_account(profile):
    """Separate GitHub's API type from a conservative semantic classification."""
    github_type = profile.get("github_account_type")
    if not github_type:
        github_type = {
            "person": "User",
            "organization": "Organization",
            "bot": "Bot",
        }.get(profile.get("account_type"))
        profile["github_account_type"] = github_type

    login = identity_key(profile.get("github_login") or profile.get("input"))
    if github_type == "Organization":
        profile["account_type"] = "organization"
        profile["account_classification_status"] = "github_api"
        profile["account_classification_reason"] = "GitHub account type is Organization"
    elif github_type == "Bot":
        profile["account_type"] = "bot"
        profile["account_classification_status"] = "github_api"
        profile["account_classification_reason"] = "GitHub account type is Bot"
    elif login in SERVICE_ACCOUNT_LOGINS:
        profile["account_type"] = "service_account"
        profile["account_classification_status"] = "heuristic"
        profile["account_classification_reason"] = SERVICE_ACCOUNT_LOGINS[login]
    elif SERVICE_ACCOUNT_RE.search(login):
        profile["account_type"] = "service_account"
        profile["account_classification_status"] = "heuristic"
        profile["account_classification_reason"] = "login contains a bot marker"
    elif github_type == "User":
        profile["account_type"] = "person"
        profile["account_classification_status"] = "github_api"
        profile["account_classification_reason"] = "GitHub account type is User"
    else:
        profile.setdefault("account_type", "unknown")
        profile.setdefault("account_classification_status", "unresolved")
        profile.setdefault("account_classification_reason", None)
    return profile


def add_author(repo, raw, role):
    raw = (raw or "").strip()
    if not raw:
        return
    key = identity_key(raw)
    author = repo["authors"].setdefault(key, {"raw": raw, "roles": []})
    if role not in author["roles"]:
        author["roles"].append(role)


def collect_repositories():
    index = load(INDEX, [])
    pool = load(REPO_POOL, {}).get("repos", [])
    repos = {}

    for record in pool:
        name = (record.get("repo") or "").strip()
        if "/" not in name:
            continue
        key = name.casefold()
        item = repos.setdefault(key, {
            "repo": name,
            "source_repo": name,
            "sdv_repo_ids": [],
            "authors": {},
        })
        add_author(item, record.get("owner") or name.split("/", 1)[0], "owner")
        for contributor in record.get("top_contributors") or []:
            add_author(item, contributor, "top_contributor")

    for record in index:
        name = repo_from_url(record.get("url"))
        if not name:
            continue
        key = name.casefold()
        item = repos.setdefault(key, {
            "repo": name,
            "source_repo": name,
            "sdv_repo_ids": [],
            "authors": {},
        })
        if record.get("id") and record["id"] not in item["sdv_repo_ids"]:
            item["sdv_repo_ids"].append(record["id"])
        # Curated index authors are canonical real names, not GitHub logins. Login
        # candidates come from the repository pool/API so a rerun does not mistake
        # names such as "Ada Lovelace" for account identifiers.
        if not item["authors"]:
            add_author(item, name.split("/", 1)[0], "owner")

    for item in repos.values():
        item["sdv_repo_ids"].sort()
        item["authors"] = list(item["authors"].values())
        for author in item["authors"]:
            author["roles"].sort()
    return dict(sorted(repos.items()))


def graphql(token, query):
    request = urllib.request.Request(
        GRAPHQL,
        data=json.dumps({"query": query}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
            "User-Agent": "sdvworld-index-identity-harvest",
        },
    )
    delay = 5
    for attempt in range(8):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.load(response)
            if payload.get("errors") and not payload.get("data"):
                raise RuntimeError(payload["errors"])
            return payload
        except urllib.error.HTTPError as exc:
            if exc.code not in (403, 429, 500, 502, 503, 504) or attempt == 7:
                raise
        except (TimeoutError, urllib.error.URLError):
            if attempt == 7:
                raise
        time.sleep(delay)
        delay = min(delay * 2, 60)
    raise RuntimeError("GitHub GraphQL retry loop exhausted")


def rest_json(token, url):
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "sdvworld-index-identity-harvest",
        },
    )
    delay = 5
    for attempt in range(8):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 409, 422):
                return []
            if exc.code not in (403, 429, 500, 502, 503, 504) or attempt == 7:
                raise
        except (TimeoutError, urllib.error.URLError):
            if attempt == 7:
                raise
        time.sleep(delay)
        delay = min(delay * 2, 60)
    raise RuntimeError("GitHub REST retry loop exhausted")


def quoted(value):
    return json.dumps(value, ensure_ascii=False)


def cache_payload(cache):
    return {
        "note": (
            "Resumable public GitHub metadata used to build github-repo-authors.json. "
            "Names and companies are self-published profile fields, not verified legal "
            "identity or employment. No email addresses are requested or stored."
        ),
        "generated": today(),
        "source": "GitHub GraphQL and REST APIs",
        "repositories": cache["repositories"],
        "identities": cache["identities"],
    }


def checkpoint(cache):
    atomic_write(CACHE, cache_payload(cache))


def fetch_repositories(token, repos, cache, batch_size, max_batches):
    missing = [key for key in repos if key not in cache["repositories"]]
    batches = 0
    for start in range(0, len(missing), batch_size):
        if max_batches is not None and batches >= max_batches:
            break
        keys = missing[start:start + batch_size]
        fields = []
        for index, key in enumerate(keys):
            owner, name = repos[key]["repo"].split("/", 1)
            fields.append(
                f'r{index}: repository(owner: {quoted(owner)}, name: {quoted(name)}) {{ '
                "databaseId id nameWithOwner url owner { login __typename } }"
            )
        payload = graphql(token, "query {\n" + "\n".join(fields) +
                          "\nrateLimit { cost remaining resetAt }\n}")
        data = payload.get("data") or {}
        for index, key in enumerate(keys):
            node = data.get(f"r{index}")
            if node:
                cache["repositories"][key] = {
                    "status": "ok",
                    "github_repo_id": node.get("databaseId"),
                    "github_repo_node_id": node.get("id"),
                    "repo": node.get("nameWithOwner") or repos[key]["repo"],
                    "url": node.get("url") or "https://github.com/" + repos[key]["repo"],
                    "owner_login": (node.get("owner") or {}).get("login"),
                    "owner_type": (node.get("owner") or {}).get("__typename"),
                    "fetched_at": today(),
                }
            else:
                cache["repositories"][key] = {
                    "status": "not_found",
                    "repo": repos[key]["repo"],
                    "url": "https://github.com/" + repos[key]["repo"],
                    "fetched_at": today(),
                }
        batches += 1
        checkpoint(cache)
        rate = data.get("rateLimit") or {}
        print(f"repos {min(start + len(keys), len(missing))}/{len(missing)} "
              f"remaining={rate.get('remaining')}")
    return batches


def fetch_structured_contributors(token, repos, cache, max_repos):
    """Recover the login-vs-anonymous distinction lost by github_metrics.py."""
    todo = [key for key in repos
            if not (cache["repositories"].get(key) or {}).get("contributors_checked_at")]
    if max_repos is not None:
        todo = todo[:max_repos]
    for number, key in enumerate(todo, 1):
        repo_meta = cache["repositories"].setdefault(key, {
            "status": "not_fetched",
            "repo": repos[key]["repo"],
            "url": "https://github.com/" + repos[key]["repo"],
        })
        repo_name = repo_meta.get("repo") or repos[key]["repo"]
        if repo_meta.get("status") == "ok":
            url = ("https://api.github.com/repos/" + repo_name + "/contributors?" +
                   urllib.parse.urlencode({"per_page": 100, "anon": 1}))
            payload = rest_json(token, url)
        else:
            payload = []
        structured = []
        for contributor in payload if isinstance(payload, list) else []:
            login = contributor.get("login")
            name = contributor.get("name") if not login else None
            structured.append({
                "github_login": login,
                "github_user_id": contributor.get("id") if login else None,
                "github_user_node_id": contributor.get("node_id") if login else None,
                "github_account_type": contributor.get("type") if login else None,
                "account_type": ({
                    "User": "person",
                    "Organization": "organization",
                    "Bot": "bot",
                }.get(contributor.get("type"), "unknown") if login else "anonymous"),
                "anonymous_name": name,
                "contributions": contributor.get("contributions"),
            })
        repo_meta["contributors_structured"] = structured
        repo_meta["contributors_returned"] = len(structured)
        repo_meta["contributors_checked_at"] = today()
        if number % 25 == 0 or number == len(todo):
            checkpoint(cache)
            print(f"structured contributors {number}/{len(todo)}")


def trim_structured_contributors(repos, cache):
    """Keep only contributor records that can explain an indexed author string."""
    for key, repo in repos.items():
        repo_meta = cache["repositories"].get(key) or {}
        contributors = repo_meta.get("contributors_structured") or []
        targets = {identity_key(author["raw"]) for author in repo["authors"]}
        canonical_targets = set(targets)
        for target in targets:
            profile = cache["identities"].get(target) or {}
            if profile.get("github_login"):
                canonical_targets.add(identity_key(profile["github_login"]))
        repo_meta["contributors_structured"] = [
            contributor for contributor in contributors
            if ((contributor.get("github_login") and
                 identity_key(contributor["github_login"]) in canonical_targets) or
                (contributor.get("anonymous_name") and
                 identity_key(contributor["anonymous_name"]) in targets))
        ]


def candidate_logins(repos):
    values = {}
    for repo in repos.values():
        for author in repo["authors"]:
            raw = author["raw"]
            key = identity_key(raw)
            if LOGIN_RE.fullmatch(raw):
                values.setdefault(key, raw)
    return dict(sorted(values.items()))


def fetch_identities(token, candidates, cache, batch_size, max_batches):
    missing = [key for key in candidates if key not in cache["identities"]]
    batches = 0
    for start in range(0, len(missing), batch_size):
        if max_batches is not None and batches >= max_batches:
            break
        keys = missing[start:start + batch_size]
        fields = []
        for index, key in enumerate(keys):
            login = candidates[key]
            fields.append(
                f'u{index}: repositoryOwner(login: {quoted(login)}) {{ '
                "__typename id login "
                "... on User { databaseId name company websiteUrl location bio } "
                "... on Organization { databaseId name websiteUrl location description } }"
            )
        payload = graphql(token, "query {\n" + "\n".join(fields) +
                          "\nrateLimit { cost remaining resetAt }\n}")
        data = payload.get("data") or {}
        for index, key in enumerate(keys):
            raw = candidates[key]
            node = data.get(f"u{index}")
            if node:
                kind = node.get("__typename")
                name = (node.get("name") or "").strip() or None
                company = (node.get("company") or "").strip() or None
                cache["identities"][key] = {
                    "status": "ok",
                    "input": raw,
                    "github_login": node.get("login") or raw,
                    "github_user_id": node.get("databaseId"),
                    "github_user_node_id": node.get("id"),
                    "github_account_type": kind,
                    "account_type": "person" if kind == "User" else "organization",
                    "public_name": name,
                    "name_status": "profile_stated" if name else "unresolved",
                    "name_evidence_urls": (["https://api.github.com/users/" +
                                             (node.get("login") or raw)] if name else []),
                    "affiliation": company,
                    "affiliation_status": "profile_stated" if company else "unresolved",
                    "affiliation_evidence_urls": (["https://api.github.com/users/" +
                                                    (node.get("login") or raw)]
                                                   if company else []),
                    "website": node.get("websiteUrl") or None,
                    "location": node.get("location") or None,
                    "profile_url": "https://github.com/" + (node.get("login") or raw),
                    "evidence_url": "https://api.github.com/users/" + (node.get("login") or raw),
                    "fetched_at": today(),
                }
            else:
                is_bot = raw.casefold().endswith("[bot]")
                cache["identities"][key] = {
                    "status": "not_found",
                    "input": raw,
                    "github_login": raw if is_bot else None,
                    "github_user_id": None,
                    "github_user_node_id": None,
                    "github_account_type": "Bot" if is_bot else None,
                    "account_type": "bot" if is_bot else "unknown",
                    "public_name": raw[:-5] if is_bot else None,
                    "name_status": "system_label" if is_bot else "unresolved",
                    "name_evidence_urls": [],
                    "affiliation": None,
                    "affiliation_status": "unresolved",
                    "affiliation_evidence_urls": [],
                    "profile_url": "https://github.com/" + raw,
                    "evidence_url": None,
                    "fetched_at": today(),
                }
        batches += 1
        checkpoint(cache)
        rate = data.get("rateLimit") or {}
        print(f"identities {min(start + len(keys), len(missing))}/{len(missing)} "
              f"remaining={rate.get('remaining')}")
    return batches


def fetch_rest_identity_fallbacks(token, cache):
    """Resolve actors GraphQL repositoryOwner cannot represent, notably bots."""
    todo = [key for key, profile in cache["identities"].items()
            if profile.get("status") == "not_found" and profile.get("input")]
    for number, key in enumerate(todo, 1):
        old = cache["identities"][key]
        raw = old["input"]
        url = "https://api.github.com/users/" + urllib.parse.quote(raw, safe="")
        node = rest_json(token, url)
        if isinstance(node, dict) and node.get("login"):
            github_type = node.get("type")
            account_type = {
                "User": "person",
                "Organization": "organization",
                "Bot": "bot",
            }.get(github_type, "unknown")
            name = (node.get("name") or "").strip() or None
            company = (node.get("company") or "").strip() or None
            if account_type == "bot" and not name:
                name = (node.get("login") or raw).removesuffix("[bot]")
            cache["identities"][key] = {
                **old,
                "status": "ok",
                "github_login": node.get("login"),
                "github_user_id": node.get("id"),
                "github_user_node_id": node.get("node_id"),
                "github_account_type": github_type,
                "account_type": account_type,
                "public_name": name,
                "name_status": ("profile_stated" if node.get("name") else
                                "system_label" if account_type == "bot" else "unresolved"),
                "name_evidence_urls": [url] if name else [],
                "affiliation": company,
                "affiliation_status": "profile_stated" if company else "unresolved",
                "affiliation_evidence_urls": [url] if company else [],
                "website": node.get("blog") or None,
                "location": node.get("location") or None,
                "profile_url": node.get("html_url") or "https://github.com/" + raw,
                "evidence_url": url,
                "fetched_at": today(),
            }
        if number % 25 == 0 or number == len(todo):
            checkpoint(cache)
            resolved = sum(cache["identities"][item].get("status") == "ok"
                           for item in todo[:number])
            print(f"REST identity fallbacks {number}/{len(todo)} resolved={resolved}")


def relation_match(repo_key, repo, author, cache, profiles_by_login=None):
    raw = author["raw"]
    raw_key = identity_key(raw)
    repo_meta = cache["repositories"].get(repo_key) or {}
    profile = cache["identities"].get(raw_key)
    canonical = (profile or {}).get("github_login")
    owner_login = repo_meta.get("owner_login")
    if ("owner" in author["roles"] or
            (owner_login and raw_key == identity_key(owner_login)) or
            (owner_login and canonical and identity_key(canonical) == identity_key(owner_login))):
        return profile, None, "repository_owner", True

    for contributor in repo_meta.get("contributors_structured") or []:
        login = contributor.get("github_login")
        if login and (raw_key == identity_key(login) or
                      (canonical and identity_key(canonical) == identity_key(login))):
            matched = profile
            if matched is None and profiles_by_login:
                matched = profiles_by_login.get(identity_key(login))
            return matched, contributor.get("contributions"), "linked_contributor", True
        anonymous = contributor.get("anonymous_name")
        if anonymous and raw_key == identity_key(anonymous):
            return anonymous_identity(raw), contributor.get("contributions"), "anonymous_commit", False

    if not LOGIN_RE.fullmatch(raw):
        return anonymous_identity(raw), None, "unlinked_name", False
    return None, None, "unverified_contributor_string", False


def repos_by_identity(repos, cache):
    result = {}
    for repo_key, repo in repos.items():
        for author in repo["authors"]:
            raw = author["raw"]
            if not LOGIN_RE.fullmatch(raw):
                continue
            key = identity_key(raw)
            _, _, _, verified = relation_match(repo_key, repo, author, cache)
            if not verified:
                continue
            priority = (
                0 if repo["sdv_repo_ids"] else 1,
                0 if "owner" in author["roles"] else 1,
                repo_key,
            )
            result.setdefault(key, []).append((priority, repo_key))
    return {key: [repo_key for _, repo_key in sorted(values)]
            for key, values in result.items()}


def usable_commit_name(name, login):
    name = (name or "").strip()
    if not name or name.casefold() == login.casefold():
        return False
    generic = {
        "actions user", "actions-user", "administrator", "anonymous", "github",
        "github actions", "github-actions", "root", "unknown", "web-flow",
    }
    folded = name.casefold()
    if folded in generic or folded.endswith("[bot]"):
        return False
    return True


def person_like_commit_name(name):
    tokens = [token.strip(".,;:()[]{}<>\"'") for token in (name or "").split()]
    tokens = [token for token in tokens if token]
    if len(tokens) < 2:
        return False
    folded = " ".join(tokens).casefold()
    if folded in {"first last", "firstname lastname", "jane doe", "john doe",
                  "test user", "your name"}:
        return False
    generic = {"action", "actions", "admin", "administrator", "bot", "github",
               "service", "unknown", "user", "web-flow"}
    if any(token.casefold() in generic for token in tokens):
        return False
    if not all(any(character.isalpha() for character in token) for token in tokens):
        return False
    # A two-token name ending in one initial is useful evidence, but not the full
    # name this table promises to resolve.
    if len(tokens) == 2 and len(tokens[-1].rstrip(".")) == 1:
        return False
    return True


def fetch_commit_names(token, repos, cache, max_repos, max_accounts):
    by_identity = repos_by_identity(repos, cache)
    todo = []
    for key, profile in cache["identities"].items():
        if profile.get("account_type") != "person" or profile.get("public_name"):
            continue
        if profile.get("commit_name_checked_at"):
            continue
        if key in by_identity:
            todo.append(key)
    todo.sort(key=lambda key: (-len(by_identity[key]), key))
    if max_accounts is not None:
        todo = todo[:max_accounts]

    for number, key in enumerate(todo, 1):
        profile = cache["identities"][key]
        login = profile.get("github_login") or profile.get("input")
        names = {}
        urls = {}
        checked_repos = []
        for repo_key in by_identity[key][:max_repos]:
            repo_meta = cache["repositories"].get(repo_key) or {}
            repo_name = repo_meta.get("repo") or repos[repo_key]["repo"]
            url = ("https://api.github.com/repos/" + repo_name + "/commits?" +
                   urllib.parse.urlencode({"author": login, "per_page": 100}))
            commits = rest_json(token, url)
            checked_repos.append(repo_name)
            for commit in commits if isinstance(commits, list) else []:
                linked = (commit.get("author") or {}).get("login")
                if not linked or linked.casefold() != login.casefold():
                    continue
                name = (((commit.get("commit") or {}).get("author") or {}).get("name") or "").strip()
                if not usable_commit_name(name, login):
                    continue
                names[name] = names.get(name, 0) + 1
                urls.setdefault(name, []).append(commit.get("html_url"))
            if names:
                break

        ranked = sorted(names.items(), key=lambda item: (-item[1], item[0].casefold()))
        profile["commit_name_candidates"] = [
            {"name": name, "commits": count,
             "evidence_urls": [value for value in urls.get(name, []) if value][:3]}
            for name, count in ranked[:5]
        ]
        profile["commit_name_repositories"] = checked_repos
        profile["commit_name_checked_at"] = today()
        if ranked:
            top_name, top_count = ranked[0]
            second_count = ranked[1][1] if len(ranked) > 1 else 0
            if (person_like_commit_name(top_name) and
                    (len(ranked) == 1 or (top_count >= 2 and top_count >= 2 * second_count))):
                profile["public_name"] = top_name
                profile["name_status"] = "commit_stated"
                profile["name_evidence_urls"] = [
                    value for value in urls.get(top_name, []) if value
                ][:3]
            else:
                profile["name_status"] = ("ambiguous_commit_names" if len(ranked) > 1
                                          else "commit_name_candidate_only")
        if number % 25 == 0 or number == len(todo):
            checkpoint(cache)
            resolved = sum(bool(cache["identities"][item].get("public_name")) for item in todo[:number])
            print(f"commit names {number}/{len(todo)} resolved={resolved}")


def anonymous_identity(raw):
    return {
        "input": raw,
        "status": "unlinked_name",
        "github_login": None,
        "github_user_id": None,
        "github_user_node_id": None,
        "github_account_type": None,
        "account_type": "anonymous",
        "account_classification_status": "not_applicable",
        "account_classification_reason": "unlinked anonymous Git author name",
        "public_name": raw,
        "name_status": "commit_stated",
        "name_evidence_urls": [],
        "affiliation": None,
        "affiliation_status": "unresolved",
        "affiliation_evidence_urls": [],
        "profile_url": None,
        "evidence_url": None,
        "fetched_at": None,
    }


def normalize_affiliation(profile, mappings):
    raw = profile.get("affiliation")
    if not raw:
        return {
            "affiliation_raw": None,
            "affiliation": None,
            "affiliation_status": "unresolved",
            "affiliation_source_status": profile.get("affiliation_status", "unresolved"),
            "affiliation_country": None,
            "affiliation_type": None,
            "affiliation_ror_id": None,
            "affiliation_normalization_note": None,
            "affiliation_evidence_urls": [],
        }
    mapping = mappings.get(raw) or {}
    evidence = []
    for url in ((mapping.get("evidence_urls") or []) +
                (profile.get("affiliation_evidence_urls") or [])):
        if url and url not in evidence:
            evidence.append(url)
    return {
        "affiliation_raw": raw,
        "affiliation": mapping.get("canonical_name", raw),
        "affiliation_status": mapping.get("status", "profile_stated_unconfirmed"),
        "affiliation_source_status": profile.get("affiliation_status", "profile_stated"),
        "affiliation_country": mapping.get("country"),
        "affiliation_type": mapping.get("organization_type"),
        "affiliation_ror_id": mapping.get("ror_id"),
        "affiliation_normalization_note": mapping.get("note"),
        "affiliation_evidence_urls": evidence,
    }


def normalize_public_name(profile, mappings):
    raw = profile.get("public_name")
    source_status = profile.get("name_status", "unresolved")
    if not raw:
        return {
            "public_name_raw": None,
            "public_name": None,
            "name_status": source_status,
            "name_normalization_status": "unresolved",
            "name_normalization_note": None,
            "canonical_name_key": None,
            "same_name_github_account_count": None,
            "public_name_variants": [],
            "name_evidence_urls": profile.get("name_evidence_urls") or [],
        }
    mapping = mappings.get((profile.get("account_type") or "unknown", raw)) or {}
    notes = mapping.get("normalization_notes") or []
    return {
        "public_name_raw": raw,
        "public_name": mapping.get("canonical_name", raw),
        "name_status": source_status,
        "name_normalization_status": mapping.get("normalization_status", "unchanged"),
        "name_normalization_note": "; ".join(notes) or None,
        "canonical_name_key": mapping.get("canonical_name_key"),
        "same_name_github_account_count": mapping.get("same_name_github_account_count"),
        "public_name_variants": mapping.get("equivalent_name_variants") or [raw],
        "name_evidence_urls": profile.get("name_evidence_urls") or [],
    }


def build_table(repos, cache):
    rows = []
    affiliation_mappings = load(AFFILIATION_NORMALIZATIONS, {}).get("mappings", {})
    public_name_mappings = {
        (item.get("account_type"), item.get("raw")): item
        for item in load(PUBLIC_NAME_NORMALIZATIONS, {}).get("mappings", [])
    }
    profiles_by_login = {
        identity_key(profile.get("github_login")): profile
        for profile in cache["identities"].values() if profile.get("github_login")
    }
    for repo_key, repo in repos.items():
        repo_meta = cache["repositories"].get(repo_key, {})
        for author in repo["authors"]:
            raw = author["raw"]
            profile, contributions, identity_source, verified = relation_match(
                repo_key, repo, author, cache, profiles_by_login)
            if profile is None:
                profile = {
                    "input": raw,
                    "status": "unverified_string",
                    "github_login": None,
                    "github_user_id": None,
                    "github_user_node_id": None,
                    "github_account_type": None,
                    "account_type": "unknown",
                    "account_classification_status": "unresolved",
                    "account_classification_reason": None,
                    "public_name": None,
                    "name_status": "unresolved",
                    "name_evidence_urls": [],
                    "affiliation": None,
                    "affiliation_status": "unresolved",
                    "affiliation_evidence_urls": [],
                    "profile_url": "https://github.com/" + raw,
                    "evidence_url": None,
                    "fetched_at": None,
                }
            normalized_name = normalize_public_name(profile, public_name_mappings)
            normalized_affiliation = normalize_affiliation(profile, affiliation_mappings)
            rows.append({
                "sdv_repo_ids": repo["sdv_repo_ids"],
                "github_repo_id": repo_meta.get("github_repo_id"),
                "github_repo_node_id": repo_meta.get("github_repo_node_id"),
                "github_repo": repo_meta.get("repo") or repo["repo"],
                "github_repo_url": repo_meta.get("url") or "https://github.com/" + repo["repo"],
                "repo_status": repo_meta.get("status", "not_fetched"),
                "raw_author": raw,
                "roles": author["roles"],
                "contributions": contributions,
                "identity_source": identity_source,
                "verified_github_link": verified,
                "github_user_id": profile.get("github_user_id"),
                "github_user_node_id": profile.get("github_user_node_id"),
                "github_login": profile.get("github_login"),
                "github_account_type": profile.get("github_account_type"),
                "account_type": profile.get("account_type"),
                "account_classification_status": profile.get("account_classification_status"),
                "account_classification_reason": profile.get("account_classification_reason"),
                **normalized_name,
                **normalized_affiliation,
                "profile_url": profile.get("profile_url"),
                "evidence_url": profile.get("evidence_url"),
                "checked_at": profile.get("fetched_at"),
            })
    rows.sort(key=lambda row: (
        (row["github_repo"] or "").casefold(),
        (row["github_login"] or row["raw_author"] or "").casefold(),
    ))
    unique_accounts = {
        row["github_user_id"]: row for row in rows if row.get("github_user_id") is not None
    }
    counts = {
        "repositories": len(repos),
        "rows": len(rows),
        "verified_github_links": sum(bool(row.get("verified_github_link")) for row in rows),
        "unique_resolved_github_accounts": len(unique_accounts),
        "unique_accounts_with_public_name": sum(
            bool(row.get("public_name")) for row in unique_accounts.values()),
        "unique_accounts_with_affiliation": sum(
            bool(row.get("affiliation")) for row in unique_accounts.values()),
        "with_public_name": sum(bool(row.get("public_name")) for row in rows),
        "with_affiliation": sum(bool(row.get("affiliation")) for row in rows),
        "people": sum(row.get("account_type") == "person" for row in rows),
        "organizations": sum(row.get("account_type") == "organization" for row in rows),
        "bots": sum(row.get("account_type") == "bot" for row in rows),
        "service_accounts": sum(row.get("account_type") == "service_account" for row in rows),
        "anonymous_names": sum(row.get("account_type") == "anonymous" for row in rows),
        "unknown": sum(row.get("account_type") == "unknown" for row in rows),
    }
    payload = {
        "note": (
            "Generated flat repository-author identity table. One row represents one "
            "deduplicated author-like identity per GitHub repository. public_name_raw and "
            "affiliation_raw preserve public source claims; public_name and affiliation "
            "contain conservative canonical display values with explicit status fields. "
            "Equivalent name variants are grouped for display, but distinct GitHub numeric "
            "IDs are never merged solely by name. Unresolved values remain null."
        ),
        "generated": today(),
        "counts": counts,
        "rows": rows,
    }
    atomic_write(OUT, payload)
    atomic_write_csv(OUT_CSV, rows)
    return counts


def normalize_cache(raw):
    cache = {
        "repositories": dict(raw.get("repositories") or {}),
        "identities": dict(raw.get("identities") or {}),
    }
    for profile in cache["identities"].values():
        evidence = profile.get("evidence_url")
        if "name_evidence_urls" not in profile:
            profile["name_evidence_urls"] = ([evidence] if evidence and profile.get("public_name") else [])
        if "affiliation_evidence_urls" not in profile:
            profile["affiliation_evidence_urls"] = ([evidence] if evidence and profile.get("affiliation") else [])
        classify_account(profile)
        if (profile.get("name_status") == "commit_stated" and
                (profile.get("account_type") != "person" or
                 not person_like_commit_name(profile.get("public_name")))):
            profile["public_name"] = None
            profile["name_status"] = "commit_name_candidate_only"
            profile["name_evidence_urls"] = []
    return cache


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true",
                        help="build an unresolved table without making API calls")
    parser.add_argument("--refresh", action="store_true",
                        help="discard cached GitHub metadata and fetch it again")
    parser.add_argument("--batch-size", type=int, default=35)
    parser.add_argument("--max-batches", type=int,
                        help="process at most this many repo and identity batches")
    parser.add_argument("--skip-commit-names", action="store_true",
                        help="do not recover missing names from GitHub-linked commits")
    parser.add_argument("--commit-repos", type=int, default=3,
                        help="maximum associated repositories checked per unnamed account")
    parser.add_argument("--max-commit-accounts", type=int,
                        help="limit commit-name fallback to this many accounts")
    parser.add_argument("--skip-contributors", action="store_true",
                        help="do not recover structured contributor records")
    parser.add_argument("--max-contributor-repos", type=int,
                        help="limit structured-contributor recovery to this many repositories")
    args = parser.parse_args()

    repos = collect_repositories()
    candidates = candidate_logins(repos)
    raw_cache = {} if args.refresh else load(CACHE, {})
    cache = normalize_cache(raw_cache)
    print(f"prepared {len(repos)} repositories and {len(candidates)} login candidates")

    if not args.prepare_only:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise SystemExit("GITHUB_TOKEN is required unless --prepare-only is used")
        fetch_repositories(token, repos, cache, args.batch_size, args.max_batches)
        if not args.skip_contributors:
            fetch_structured_contributors(token, repos, cache, args.max_contributor_repos)
        fetch_identities(token, candidates, cache, args.batch_size, args.max_batches)
        fetch_rest_identity_fallbacks(token, cache)
        for profile in cache["identities"].values():
            classify_account(profile)
        trim_structured_contributors(repos, cache)
        if not args.skip_commit_names:
            fetch_commit_names(token, repos, cache, args.commit_repos,
                               args.max_commit_accounts)
        checkpoint(cache)

    trim_structured_contributors(repos, cache)
    if cache["repositories"] or cache["identities"]:
        checkpoint(cache)

    counts = build_table(repos, cache)
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
