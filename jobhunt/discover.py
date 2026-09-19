"""Job discovery: pull openings from job APIs, score them against the ledger, store for review.

Sources are official or public JSON APIs only. LinkedIn and Naukri do not
offer public job-search APIs and prohibit scraping, so their postings arrive
through JSearch (an aggregator that indexes LinkedIn, Indeed, Naukri, Glassdoor
and others) and through pre-filled search links the user opens directly.
"""

from __future__ import annotations

import html
import http.client
import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import jobs, ledger, roles, settings
from .db import dumps, loads, now

USER_AGENT = "jobhunt/0.2 (personal job tracker)"
DISCOVER_STATUSES = ("new", "saved", "dismissed")


# --- HTTP helpers ------------------------------------------------------------


class SourceError(RuntimeError):
    pass


def _get_json(url: str, params: dict | None = None, headers: dict | None = None, timeout: int = 25, retries: int = 1):
    if params:
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(clean)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except (ConnectionError, http.client.RemoteDisconnected) as e:
        # Some boards drop the first connection now and then; one retry is cheap.
        if retries > 0:
            time.sleep(1.0)
            return _get_json(url, None, headers, timeout, retries - 1)
        raise SourceError(f"connection dropped: {e}") from e
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode("utf-8", "replace")
        if e.code in (401, 403):
            raise SourceError(f"HTTP {e.code}: check the API key ({body.strip()[:120]})") from e
        if e.code == 429:
            raise SourceError("HTTP 429: rate limited, try again later") from e
        raise SourceError(f"HTTP {e.code}: {body.strip()[:160]}") from e
    except urllib.error.URLError as e:
        if retries > 0 and isinstance(e.reason, (ConnectionError, TimeoutError, OSError)):
            time.sleep(1.0)
            return _get_json(url, None, headers, timeout, retries - 1)
        raise SourceError(f"could not connect: {e.reason}") from e
    except (json.JSONDecodeError, TimeoutError) as e:
        raise SourceError(f"bad response: {e}") from e


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>|</h\d>", "\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _iso(value) -> str | None:
    """Normalise assorted timestamp formats to 'YYYY-MM-DDTHH:MM:SS'."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        s = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, OSError):
        return str(value)[:19]


def _salary(lo, hi, currency: str | None = None) -> str | None:
    if not lo and not hi:
        return None
    cur = f"{currency} " if currency else ""

    def fmt(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return str(v)
        return f"{v/1000:.0f}k" if v >= 1000 else f"{v:.0f}"

    if lo and hi:
        return f"{cur}{fmt(lo)}-{fmt(hi)}"
    return f"{cur}{fmt(lo or hi)}"


# --- postings and sources ----------------------------------------------------


@dataclass
class Posting:
    source: str
    external_id: str
    title: str
    url: str
    company: str | None = None
    location: str | None = None
    remote: bool = False
    description: str = ""
    tags: list[str] = field(default_factory=list)
    salary: str | None = None
    publisher: str | None = None
    posted_at: str | None = None


@dataclass(frozen=True)
class KeySpec:
    setting: str
    label: str
    env: str


class Source:
    id: str
    label: str
    kind: str  # "remote" (remote-only boards) | "aggregator" (location aware)
    notes: str
    keys: tuple[KeySpec, ...] = ()
    base_url: str = ""
    docs: str = ""

    def search(self, query: str, location: str, remote_only: bool, country: str, keys: dict[str, str]) -> list[Posting]:
        raise NotImplementedError


class Remotive(Source):
    id, label, kind = "remotive", "Remotive", "remote"
    notes = "Curated remote jobs worldwide. No key needed."
    base_url = "https://remotive.com/api/remote-jobs"
    docs = "https://remotive.com/api-documentation"

    def search(self, query, location, remote_only, country, keys):
        data = _get_json(self.base_url, {"search": query, "limit": 60})
        out = []
        for j in data.get("jobs", []):
            out.append(Posting(
                source=self.id, external_id=str(j.get("id")), title=j.get("title") or "", url=j.get("url") or "",
                company=j.get("company_name"), location=j.get("candidate_required_location") or "Remote", remote=True,
                description=strip_html(j.get("description"))[:8000], tags=list(j.get("tags") or []),
                salary=j.get("salary") or None, posted_at=_iso(j.get("publication_date")),
            ))
        return out


class RemoteOK(Source):
    id, label, kind = "remoteok", "RemoteOK", "remote"
    notes = "Remote tech jobs. No key needed; filtered locally by your query."
    base_url = "https://remoteok.com/api"
    docs = "https://remoteok.com/api"

    def search(self, query, location, remote_only, country, keys):
        data = _get_json(self.base_url)
        terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 1]
        out = []
        for j in data if isinstance(data, list) else []:
            if not isinstance(j, dict) or not j.get("position"):
                continue  # first element is a legal notice
            hay = " ".join([j.get("position", ""), " ".join(j.get("tags") or []), strip_html(j.get("description"))[:2000]]).lower()
            if terms and not any(t in hay for t in terms):
                continue
            out.append(Posting(
                source=self.id, external_id=str(j.get("id")), title=j.get("position") or "", url=j.get("url") or j.get("apply_url") or "",
                company=j.get("company"), location=j.get("location") or "Remote", remote=True,
                description=strip_html(j.get("description"))[:8000], tags=list(j.get("tags") or []),
                salary=_salary(j.get("salary_min"), j.get("salary_max"), "USD"), posted_at=_iso(j.get("date")),
            ))
        return out


class Arbeitnow(Source):
    id, label, kind = "arbeitnow", "Arbeitnow", "remote"
    notes = "Remote and European tech jobs. No key needed."
    base_url = "https://www.arbeitnow.com/api/job-board-api"
    docs = "https://www.arbeitnow.com/api"

    def search(self, query, location, remote_only, country, keys):
        data = _get_json(self.base_url, {"search": query})
        out = []
        for j in data.get("data", []):
            if remote_only and not j.get("remote"):
                continue
            out.append(Posting(
                source=self.id, external_id=str(j.get("slug")), title=j.get("title") or "", url=j.get("url") or "",
                company=j.get("company_name"), location=j.get("location") or ("Remote" if j.get("remote") else None),
                remote=bool(j.get("remote")), description=strip_html(j.get("description"))[:8000],
                tags=list(j.get("tags") or []) + list(j.get("job_types") or []), posted_at=_iso(j.get("created_at")),
            ))
        return out


class Adzuna(Source):
    id, label, kind = "adzuna", "Adzuna", "aggregator"
    notes = "Aggregates thousands of boards by country (India, US, UK and more). Free API key."
    keys = (KeySpec("adzuna_app_id", "App ID", "ADZUNA_APP_ID"), KeySpec("adzuna_app_key", "App key", "ADZUNA_APP_KEY"))
    base_url = "https://api.adzuna.com/v1/api/jobs"
    docs = "https://developer.adzuna.com/"

    def search(self, query, location, remote_only, country, keys):
        what = f"{query} remote" if remote_only else query
        data = _get_json(
            f"{self.base_url}/{country}/search/1",
            {"app_id": keys["adzuna_app_id"], "app_key": keys["adzuna_app_key"], "results_per_page": 50,
             "what": what, "where": location, "content-type": "application/json"},
        )
        out = []
        for j in data.get("results", []):
            loc = (j.get("location") or {}).get("display_name")
            text = f"{j.get('title','')} {j.get('description','')}".lower()
            out.append(Posting(
                source=self.id, external_id=str(j.get("id")), title=strip_html(j.get("title")), url=j.get("redirect_url") or "",
                company=(j.get("company") or {}).get("display_name"), location=loc, remote="remote" in text,
                description=strip_html(j.get("description"))[:8000], tags=[c for c in [(j.get("category") or {}).get("label")] if c],
                salary=_salary(j.get("salary_min"), j.get("salary_max")), posted_at=_iso(j.get("created")),
            ))
        return out


class JSearch(Source):
    id, label, kind = "jsearch", "JSearch (LinkedIn, Indeed, Naukri, Glassdoor via Google Jobs)", "aggregator"
    notes = "Indexes postings from LinkedIn, Indeed, Naukri, Glassdoor and company sites. Free tier on RapidAPI."
    keys = (KeySpec("rapidapi_key", "RapidAPI key", "RAPIDAPI_KEY"),)
    base_url = "https://jsearch.p.rapidapi.com/search"
    docs = "https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch"

    def search(self, query, location, remote_only, country, keys):
        q = f"{query} in {location}" if location else query
        data = _get_json(
            self.base_url,
            {"query": q, "page": 1, "num_pages": 1, "country": country, "date_posted": "month",
             "remote_jobs_only": "true" if remote_only else None},
            headers={"X-RapidAPI-Key": keys["rapidapi_key"], "X-RapidAPI-Host": "jsearch.p.rapidapi.com"},
        )
        out = []
        for j in data.get("data", []):
            loc = ", ".join(x for x in (j.get("job_city"), j.get("job_state"), j.get("job_country")) if x)
            highlights = j.get("job_highlights") or {}
            tags = [j.get("job_employment_type")] if j.get("job_employment_type") else []
            desc = strip_html(j.get("job_description"))
            quals = highlights.get("Qualifications") or []
            if quals:
                desc = "Qualifications:\n- " + "\n- ".join(quals) + "\n\n" + desc
            out.append(Posting(
                source=self.id, external_id=str(j.get("job_id")), title=j.get("job_title") or "", url=j.get("job_apply_link") or "",
                company=j.get("employer_name"), location=loc or None, remote=bool(j.get("job_is_remote")),
                description=desc[:8000], tags=tags, salary=_salary(j.get("job_min_salary"), j.get("job_max_salary"), j.get("job_salary_currency")),
                publisher=j.get("job_publisher"), posted_at=_iso(j.get("job_posted_at_datetime_utc")),
            ))
        return out


SOURCES: dict[str, Source] = {s.id: s for s in (JSearch(), Adzuna(), Remotive(), RemoteOK(), Arbeitnow())}


# --- external search links ---------------------------------------------------


def external_links(query: str, location: str = "", remote_only: bool = False) -> list[dict]:
    q = urllib.parse.quote_plus(query.strip())
    loc = urllib.parse.quote_plus(location.strip()) if location else ""
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
    india = "india" in location.lower() or not location
    links = [
        {"id": "linkedin", "label": "LinkedIn", "url": f"https://www.linkedin.com/jobs/search/?keywords={q}" + (f"&location={loc}" if loc else "") + ("&f_WT=2" if remote_only else "")},
        {"id": "naukri", "label": "Naukri", "url": f"https://www.naukri.com/{slug}-jobs" + (f"-in-{re.sub(r'[^a-z0-9]+', '-', location.lower()).strip('-')}" if location and not remote_only else "") + f"?k={q}" + ("&wfhType=2" if remote_only else "")},
        {"id": "indeed", "label": "Indeed", "url": f"https://{'in.' if india else 'www.'}indeed.com/jobs?q={q}" + (f"&l={loc}" if loc else "") + ("&sc=0kf%3Aattr%28DSQF7%29%3B" if remote_only else "")},
        {"id": "glassdoor", "label": "Glassdoor", "url": f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={q}" + (f"&locKeyword={loc}" if loc else "")},
        {"id": "foundit", "label": "Foundit", "url": f"https://www.foundit.in/srp/results?query={q}" + (f"&locations={loc}" if loc else "")},
        {"id": "wellfound", "label": "Wellfound", "url": f"https://wellfound.com/jobs?q={q}"},
        {"id": "google", "label": "Google Jobs", "url": f"https://www.google.com/search?q={q}+jobs" + (f"+{loc}" if loc else "") + ("+remote" if remote_only else "") + "&ibp=htl;jobs"},
    ]
    return links


# --- settings ----------------------------------------------------------------


def _source_keys(conn: sqlite3.Connection, src: Source) -> tuple[dict[str, str], list[dict]]:
    import os

    values, status = {}, []
    for k in src.keys:
        saved = settings.get_setting(conn, k.setting)
        env = os.environ.get(k.env)
        val = saved or env
        if val:
            values[k.setting] = val
        status.append({"setting": k.setting, "label": k.label, "env": k.env,
                       "status": "saved" if saved else ("env" if env else None), "hint": settings.mask(val)})
    return values, status


def discover_settings(conn: sqlite3.Connection) -> dict:
    enabled_raw = settings.get_setting(conn, "discover_sources")
    enabled = set(loads(enabled_raw, None) or [s.id for s in SOURCES.values() if not s.keys])
    sources = []
    for s in SOURCES.values():
        values, key_status = _source_keys(conn, s)
        configured = len(values) == len(s.keys)
        sources.append({
            "id": s.id, "label": s.label, "kind": s.kind, "notes": s.notes, "docs": s.docs,
            "keys": key_status, "configured": configured, "enabled": s.id in enabled,
        })
    last_run = loads(settings.get_setting(conn, "discover_last_run"), None)
    row = conn.execute("SELECT status, COUNT(*) AS n FROM discovered_jobs GROUP BY status").fetchall()
    counts = {s: 0 for s in DISCOVER_STATUSES}
    for r in row:
        counts[r["status"]] = r["n"]
    return {
        "location": settings.get_setting(conn, "discover_location", "") or "",
        "country": settings.get_setting(conn, "discover_country", "in") or "in",
        "remote_only": settings.get_setting(conn, "discover_remote_only", "0") == "1",
        "sources": sources,
        "last_run": last_run,
        "counts": counts,
    }


def update_discover_settings(conn: sqlite3.Connection, *, location: str | None = None, country: str | None = None,
                             remote_only: bool | None = None, sources_enabled: list[str] | None = None,
                             keys: dict[str, str] | None = None) -> None:
    if location is not None:
        settings.set_setting(conn, "discover_location", location.strip())
    if country is not None:
        c = country.strip().lower()
        if c and not re.fullmatch(r"[a-z]{2}", c):
            raise ValueError("country must be a two-letter code such as in, us or gb")
        settings.set_setting(conn, "discover_country", c or "in")
    if remote_only is not None:
        settings.set_setting(conn, "discover_remote_only", "1" if remote_only else "0")
    if sources_enabled is not None:
        bad = [s for s in sources_enabled if s not in SOURCES]
        if bad:
            raise ValueError(f"unknown sources: {', '.join(bad)}")
        settings.set_setting(conn, "discover_sources", dumps(sources_enabled))
    valid_keys = {k.setting for s in SOURCES.values() for k in s.keys}
    for name, value in (keys or {}).items():
        if name not in valid_keys:
            raise ValueError(f"unknown key {name!r}")
        settings.set_setting(conn, name, (value or "").strip())


# --- scoring -----------------------------------------------------------------

_STOP = {"and", "or", "the", "a", "an", "of", "for", "in", "at", "to", "with", "senior", "junior", "lead", "staff", "sr", "jr", "ii", "iii"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9+#.]+", text.lower()) if t and t not in _STOP}


def score_posting(p: Posting, skills: list[str], role_titles: list[str]) -> tuple[int, list[str]]:
    text = f"{p.title}\n{' '.join(p.tags)}\n{p.description}".lower()
    matched = []
    for s in skills:
        s_l = s.lower().strip()
        if len(s_l) < 2:
            continue
        pattern = r"(?<![a-z0-9+#])" + re.escape(s_l) + r"(?![a-z0-9+#])"
        if re.search(pattern, text):
            matched.append(s)
    skill_part = min(len(matched), 6) / 6 * 65
    title_tokens = _tokens(p.title)
    title_part = 0.0
    for rt in role_titles:
        rtoks = _tokens(rt)
        if rtoks:
            title_part = max(title_part, len(rtoks & title_tokens) / len(rtoks) * 25)
    recency = 0
    if p.posted_at:
        try:
            age = datetime.now(timezone.utc) - datetime.strptime(p.posted_at[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            recency = 10 if age <= timedelta(days=7) else 5 if age <= timedelta(days=30) else 0
        except ValueError:
            pass
    return int(round(min(100, skill_part + title_part + recency))), matched


# --- storage -----------------------------------------------------------------


def _upsert(conn: sqlite3.Connection, p: Posting, query: str, role_id: int | None, score: int, matched: list[str]) -> bool:
    ts = now()
    existing = conn.execute(
        "SELECT id, status FROM discovered_jobs WHERE source = ? AND external_id = ?", (p.source, p.external_id)
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE discovered_jobs SET title = ?, company = ?, location = ?, remote = ?, url = ?, description = ?, tags = ?,
               salary = ?, publisher = ?, posted_at = COALESCE(?, posted_at), query = ?, role_id = COALESCE(?, role_id),
               match_score = ?, matched_skills = ?, fetched_at = ? WHERE id = ?""",
            (p.title, p.company, p.location, int(p.remote), p.url, p.description, dumps(p.tags), p.salary, p.publisher,
             p.posted_at, query, role_id, score, dumps(matched), ts, existing["id"]),
        )
        return False
    conn.execute(
        """INSERT INTO discovered_jobs (source, external_id, title, company, location, remote, url, description, tags, salary,
           publisher, posted_at, query, role_id, match_score, matched_skills, status, first_seen_at, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)""",
        (p.source, p.external_id, p.title, p.company, p.location, int(p.remote), p.url, p.description, dumps(p.tags),
         p.salary, p.publisher, p.posted_at, query, role_id, score, dumps(matched), ts, ts),
    )
    return True


def run_search(conn: sqlite3.Connection, query: str, *, location: str | None = None, remote_only: bool | None = None,
               country: str | None = None, role_id: int | None = None, sources: list[str] | None = None) -> dict:
    """Query every enabled source, score and store results. Never raises for a single failing source."""
    cfg = discover_settings(conn)
    query = (query or "").strip()
    if not query:
        raise ValueError("Give a search query, for example a target role title.")
    location = cfg["location"] if location is None else location
    remote_only = cfg["remote_only"] if remote_only is None else remote_only
    country = cfg["country"] if country is None else country
    chosen = sources or [s["id"] for s in cfg["sources"] if s["enabled"]]

    skills = [s["name"] for s in ledger.skill_map(conn).values()]
    all_roles = roles.list_roles(conn)
    if role_id is None:  # searching for a role by its exact title links results to it
        role_id = next((r["id"] for r in all_roles if r["title"].lower() == query.lower()), None)
    role_titles = [r["title"] for r in all_roles] or [query]
    if role_id:
        role_titles = [roles.get_role(conn, role_id)["title"]] + role_titles

    per_source: dict[str, dict] = {}
    total_new = total = 0
    for sid in chosen:
        src = SOURCES.get(sid)
        if src is None:
            per_source[sid] = {"error": "unknown source"}
            continue
        keys, _ = _source_keys(conn, src)
        if len(keys) < len(src.keys):
            per_source[sid] = {"error": "API key not configured", "count": 0}
            continue
        try:
            postings = src.search(query, location, remote_only, country, keys)
        except SourceError as e:
            per_source[sid] = {"error": str(e), "count": 0}
            continue
        except Exception as e:  # noqa: BLE001 - one bad source must not sink the run
            per_source[sid] = {"error": f"{type(e).__name__}: {e}", "count": 0}
            continue
        new = 0
        for p in postings:
            if not p.url or not p.title:
                continue
            if remote_only and not p.remote and src.kind == "aggregator":
                continue
            score, matched = score_posting(p, skills, role_titles)
            if _upsert(conn, p, query, role_id, score, matched):
                new += 1
        conn.commit()
        per_source[sid] = {"count": len(postings), "new": new}
        total += len(postings)
        total_new += new

    summary = {"at": now(), "query": query, "location": location, "remote_only": remote_only, "country": country,
               "total": total, "new": total_new, "per_source": per_source}
    settings.set_setting(conn, "discover_last_run", dumps(summary))
    return summary


def _hydrate(row) -> dict:
    d = dict(row)
    d["tags"] = loads(d["tags"], [])
    d["matched_skills"] = loads(d["matched_skills"], [])
    d["remote"] = bool(d["remote"])
    return d


def list_discovered(conn: sqlite3.Connection, *, status: str | None = "new", source: str | None = None,
                    min_score: int = 0, q: str | None = None, remote_only: bool = False, limit: int = 200) -> list[dict]:
    clauses, params = ["match_score >= ?"], [min_score]
    if status:
        clauses.append("status = ?")
        params.append(status)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if remote_only:
        clauses.append("remote = 1")
    if q:
        clauses.append("(lower(title) LIKE ? OR lower(company) LIKE ? OR lower(description) LIKE ?)")
        like = f"%{q.lower()}%"
        params += [like, like, like]
    rows = conn.execute(
        f"SELECT * FROM discovered_jobs WHERE {' AND '.join(clauses)} "
        "ORDER BY match_score DESC, COALESCE(posted_at, first_seen_at) DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [_hydrate(r) for r in rows]


def get_discovered(conn: sqlite3.Connection, did: int) -> dict:
    row = conn.execute("SELECT * FROM discovered_jobs WHERE id = ?", (did,)).fetchone()
    if row is None:
        raise KeyError(f"no discovered job with id {did}")
    return _hydrate(row)


def set_status(conn: sqlite3.Connection, did: int, status: str) -> dict:
    if status not in DISCOVER_STATUSES:
        raise ValueError(f"status must be one of {', '.join(DISCOVER_STATUSES)}")
    get_discovered(conn, did)
    conn.execute("UPDATE discovered_jobs SET status = ? WHERE id = ?", (status, did))
    conn.commit()
    return get_discovered(conn, did)


def save_to_tracker(conn: sqlite3.Connection, did: int, role_id: int | None = None) -> dict:
    """Copy a discovered posting into the applications tracker (idempotent)."""
    d = get_discovered(conn, did)
    if d["saved_job_id"]:
        try:
            jobs.get_job(conn, d["saved_job_id"])
            return d
        except KeyError:
            pass  # tracker job was deleted; save again
    src = SOURCES.get(d["source"])
    via = f"{src.label if src else d['source']}" + (f" ({d['publisher']})" if d.get("publisher") else "")
    job_id = jobs.add_job(
        conn, d["company"] or "Unknown company", d["title"], url=d["url"], location=d["location"],
        role_id=role_id or d["role_id"], jd_text=d["description"] or None,
        notes=f"[{now()[:10]}] Found via {via}. Match {d['match_score']}/100; matched: {', '.join(d['matched_skills']) or 'none'}.",
    )
    conn.execute("UPDATE discovered_jobs SET status = 'saved', saved_job_id = ? WHERE id = ?", (job_id, did))
    conn.commit()
    return get_discovered(conn, did)


def suggested_queries(conn: sqlite3.Connection) -> list[str]:
    """Role titles first, then the most-evidenced skills, for the search box."""
    out = [r["title"] for r in roles.list_roles(conn)]
    skills = sorted(ledger.skill_map(conn).values(), key=lambda s: -len(s["evidence"]))
    out += [s["name"] for s in skills[:5] if s["name"] not in out]
    return out
