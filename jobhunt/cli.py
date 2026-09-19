"""jobhunt command line interface."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from . import config, jobs, ledger, roles, services, settings
from .db import JOB_STATUSES, LEDGER_KINDS, SKILL_LEVELS, connect

app = typer.Typer(help="Job-hunt ledger, application prep and skill roadmap.", no_args_is_help=True)
ledger_app = typer.Typer(help="Your experience, skills, certs and projects.", no_args_is_help=True)
role_app = typer.Typer(help="Target roles you are aiming for.", no_args_is_help=True)
job_app = typer.Typer(help="Job postings, fit analysis, tailored materials, status.", no_args_is_help=True)
roadmap_app = typer.Typer(help="Skill-up plan per target role.", no_args_is_help=True)
settings_app = typer.Typer(help="AI provider, model and API keys.", no_args_is_help=True)
discover_app = typer.Typer(help="Find openings on job boards that match your ledger.", no_args_is_help=True)
app.add_typer(discover_app, name="discover")
app.add_typer(ledger_app, name="ledger")
app.add_typer(role_app, name="role")
app.add_typer(job_app, name="job")
app.add_typer(roadmap_app, name="roadmap")
app.add_typer(settings_app, name="settings")

console = Console()
err = Console(stderr=True)


def _fail(msg: str, code: int = 1):
    err.print(f"[red]error:[/red] {msg}")
    raise typer.Exit(code)


def _split(csv: Optional[str]) -> Optional[list[str]]:
    if csv is None:
        return None
    return [s.strip() for s in csv.split(",") if s.strip()]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _run_ai(fn, *args, **kwargs):
    from .providers import AIError

    try:
        with console.status("Asking the model..."):
            return fn(*args, **kwargs)
    except (AIError, services.ServiceError) as e:
        _fail(str(e))


def _read_text_arg(path: Optional[Path], inline: Optional[str], use_stdin: bool) -> Optional[str]:
    if path is not None:
        from .resume_text import read_resume

        return read_resume(path)
    if inline:
        return inline
    if use_stdin:
        return sys.stdin.read().strip()
    return None


# --- top level ---------------------------------------------------------------


@app.command()
def init():
    """Create the database and data folder."""
    conn = connect()
    conn.close()
    console.print(f"Ready. Database at [bold]{config.db_path()}[/bold]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port", "-p"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (development)"),
):
    """Start the web UI and JSON API."""
    import uvicorn

    connect().close()
    console.print(f"jobhunt web UI on [bold]http://{host}:{port}[/bold]  (API docs at /api/docs)")
    uvicorn.run("jobhunt.web.api:app", host=host, port=port, reload=reload, log_level="info")


@app.command()
def status():
    """Dashboard: ledger size, pipeline funnel, open roadmap items."""
    conn = connect()
    entries = ledger.list_entries(conn)
    counts = {k: sum(1 for e in entries if e["kind"] == k) for k in LEDGER_KINDS}
    skills = ledger.skill_map(conn)

    t = Table(title="Ledger", box=box.SIMPLE)
    t.add_column("Kind")
    t.add_column("Count", justify="right")
    for k, n in counts.items():
        t.add_row(k, str(n))
    t.add_row("distinct skills", str(len(skills)))
    console.print(t)

    f = jobs.funnel(conn)
    t = Table(title="Pipeline", box=box.SIMPLE)
    for s in JOB_STATUSES:
        t.add_column(s, justify="right")
    t.add_row(*[str(f[s]) for s in JOB_STATUSES])
    console.print(t)

    all_roles = roles.list_roles(conn)
    if all_roles:
        t = Table(title="Roadmaps", box=box.SIMPLE)
        t.add_column("Role")
        t.add_column("Open", justify="right")
        t.add_column("Done", justify="right")
        for r in all_roles:
            items = roles.list_roadmap(conn, r["id"], include_closed=True)
            open_n = sum(1 for i in items if i["status"] in ("todo", "in_progress"))
            done_n = sum(1 for i in items if i["status"] == "done")
            t.add_row(r["title"], str(open_n), str(done_n))
        console.print(t)


# --- ledger ------------------------------------------------------------------


@ledger_app.command("add")
def ledger_add(
    kind: str = typer.Argument(..., help="|".join(LEDGER_KINDS)),
    title: str = typer.Argument(...),
    org: Optional[str] = typer.Option(None, "--org", "-o"),
    start: Optional[str] = typer.Option(None, "--start", "-s", help="YYYY-MM"),
    end: Optional[str] = typer.Option(None, "--end", "-e", help="YYYY-MM, omit if ongoing"),
    desc: Optional[str] = typer.Option(None, "--desc", "-d"),
    skills: Optional[str] = typer.Option(None, "--skills", help="Comma separated"),
    level: Optional[str] = typer.Option(None, "--level", "-l", help="|".join(SKILL_LEVELS)),
    url: Optional[str] = typer.Option(None, "--url"),
):
    """Add one ledger entry."""
    conn = connect()
    try:
        eid = ledger.add_entry(
            conn, kind, title, org=org, start_date=start, end_date=end,
            description=desc, skills=_split(skills), level=level, url=url,
        )
    except ValueError as e:
        _fail(str(e))
    console.print(f"Added {kind} #{eid}: [bold]{title}[/bold]")


@ledger_app.command("list")
def ledger_list(
    kind: Optional[str] = typer.Option(None, "--kind", "-k"),
    show_all: bool = typer.Option(False, "--all", "-a", help="Include retired entries"),
):
    """List ledger entries."""
    conn = connect()
    entries = ledger.list_entries(conn, kind=kind, include_inactive=show_all)
    if not entries:
        console.print("Ledger is empty. Try [bold]jobhunt ledger import resume.pdf[/bold] or [bold]ledger add[/bold].")
        return
    t = Table(box=box.SIMPLE_HEAD)
    t.add_column("#", justify="right")
    t.add_column("Kind")
    t.add_column("Title")
    t.add_column("Org")
    t.add_column("Dates")
    t.add_column("Skills")
    for e in entries:
        dates = " - ".join(x for x in (e["start_date"], e["end_date"] or ("now" if e["start_date"] else None)) if x)
        title = e["title"] if e["active"] else f"[dim strike]{e['title']}[/dim strike]"
        if e["kind"] == "skill" and e["level"]:
            title += f" [dim]({e['level']})[/dim]"
        t.add_row(str(e["id"]), e["kind"], title, e["org"] or "", dates, ", ".join(e["skills"][:6]))
    console.print(t)


@ledger_app.command("show")
def ledger_show(entry_id: int):
    """Show one entry in full, with its change history."""
    conn = connect()
    try:
        e = ledger.get_entry(conn, entry_id)
    except KeyError as ex:
        _fail(str(ex))
    body = []
    for k in ("kind", "title", "org", "start_date", "end_date", "level", "url"):
        if e.get(k):
            body.append(f"[bold]{k}[/bold]: {e[k]}")
    if e["skills"]:
        body.append(f"[bold]skills[/bold]: {', '.join(e['skills'])}")
    if e["description"]:
        body.append("")
        body.append(e["description"])
    if not e["active"]:
        body.append("\n[red]retired[/red]")
    console.print(Panel("\n".join(body), title=f"Ledger #{e['id']}"))
    hist = ledger.history(conn, entry_id)
    t = Table(title="History", box=box.SIMPLE)
    t.add_column("When")
    t.add_column("Action")
    t.add_column("Source")
    for h in hist:
        t.add_row(h["at"], h["action"], h["source"] or "")
    console.print(t)


@ledger_app.command("edit")
def ledger_edit(
    entry_id: int,
    title: Optional[str] = typer.Option(None, "--title", "-t"),
    kind: Optional[str] = typer.Option(None, "--kind", "-k"),
    org: Optional[str] = typer.Option(None, "--org", "-o"),
    start: Optional[str] = typer.Option(None, "--start", "-s"),
    end: Optional[str] = typer.Option(None, "--end", "-e"),
    desc: Optional[str] = typer.Option(None, "--desc", "-d"),
    skills: Optional[str] = typer.Option(None, "--skills", help="Comma separated, replaces the list"),
    add_skills: Optional[str] = typer.Option(None, "--add-skills", help="Comma separated, appends"),
    level: Optional[str] = typer.Option(None, "--level", "-l"),
    url: Optional[str] = typer.Option(None, "--url"),
):
    """Update fields on an entry. Every edit is recorded in the history."""
    conn = connect()
    try:
        current = ledger.get_entry(conn, entry_id)
        new_skills = _split(skills)
        if add_skills:
            new_skills = (new_skills if new_skills is not None else current["skills"]) + _split(add_skills)
        ledger.update_entry(
            conn, entry_id, title=title, kind=kind, org=org, start_date=start, end_date=end,
            description=desc, skills=new_skills, level=level, url=url,
        )
    except (KeyError, ValueError) as e:
        _fail(str(e))
    console.print(f"Updated #{entry_id}")


@ledger_app.command("retire")
def ledger_retire(entry_id: int):
    """Hide an entry from the active profile. History is kept."""
    conn = connect()
    try:
        ledger.retire_entry(conn, entry_id)
    except KeyError as e:
        _fail(str(e))
    console.print(f"Retired #{entry_id}")


@ledger_app.command("history")
def ledger_history(limit: int = typer.Option(30, "--limit", "-n")):
    """Recent changes across the whole ledger."""
    conn = connect()
    t = Table(box=box.SIMPLE_HEAD)
    t.add_column("When")
    t.add_column("Entry", justify="right")
    t.add_column("Action")
    t.add_column("Source")
    t.add_column("Title")
    for h in ledger.history(conn, None, limit):
        t.add_row(h["at"], str(h["entry_id"]), h["action"], h["source"] or "", h["snapshot"].get("title", ""))
    console.print(t)


@ledger_app.command("skills")
def ledger_skills():
    """Every skill in the ledger, with level and where it was used."""
    conn = connect()
    skills = ledger.skill_map(conn)
    if not skills:
        console.print("No skills recorded yet.")
        return
    t = Table(box=box.SIMPLE_HEAD)
    t.add_column("Skill")
    t.add_column("Level")
    t.add_column("Evidence")
    for s in skills.values():
        t.add_row(s["name"], s["level"] or "", "; ".join(s["evidence"][:3]))
    console.print(t)


@ledger_app.command("export")
def ledger_export(out: Optional[Path] = typer.Option(None, "--out", "-o", help="Write Markdown here")):
    """Render the active ledger as a Markdown profile."""
    conn = connect()
    md = ledger.profile_markdown(conn)
    if out:
        out.write_text(md, encoding="utf-8")
        console.print(f"Wrote {out}")
    else:
        console.print(Markdown(md))


@ledger_app.command("import")
def ledger_import(
    path: Path = typer.Argument(..., help="Resume as .pdf, .md or .txt"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Extract ledger entries from a resume with Claude, review, then save."""
    from .resume_text import read_resume

    try:
        text = read_resume(path)
    except (FileNotFoundError, ValueError) as e:
        _fail(str(e))
    conn = connect()
    extracted = _run_ai(services.extract_resume_entries, conn, text)
    entries = extracted["entries"]

    t = Table(title=f"Proposed entries from {path.name}", box=box.SIMPLE_HEAD)
    t.add_column("#", justify="right")
    t.add_column("Kind")
    t.add_column("Title")
    t.add_column("Org")
    t.add_column("Dates")
    t.add_column("Skills")
    for i, e in enumerate(entries, 1):
        dates = " - ".join(x for x in (e["start_date"], e["end_date"] or ("now" if e["start_date"] else None)) if x)
        t.add_row(str(i), e["kind"], e["title"], e["org"] or "", dates, ", ".join(e["skills"][:5]))
    console.print(t)
    if extracted["notes"]:
        console.print(Panel(extracted["notes"], title="Check these", border_style="yellow"))

    if not yes and not typer.confirm(f"Save {len(entries)} entries to the ledger?"):
        console.print("Nothing saved.")
        raise typer.Exit(0)

    saved, skipped = services.commit_entries(conn, entries, source=f"import:{path.name}")
    console.print(f"Saved {saved} entries.")
    for s in skipped:
        console.print(f"[yellow]skipped[/yellow] {s}")
    console.print("Review with [bold]jobhunt ledger list[/bold] and fix anything with [bold]ledger edit[/bold].")


# --- roles -------------------------------------------------------------------


@role_app.command("add")
def role_add(
    title: str,
    desc: Optional[str] = typer.Option(None, "--desc", "-d"),
    skills: Optional[str] = typer.Option(None, "--skills", help="Comma separated required skills"),
    nice: Optional[str] = typer.Option(None, "--nice", help="Comma separated nice-to-have skills"),
    priority: int = typer.Option(1, "--priority", "-p", help="1 = top target"),
    use_ai: bool = typer.Option(False, "--ai", help="Let Claude fill description and skills"),
):
    """Add a target role. Use --ai to derive its typical skill requirements."""
    conn = connect()
    required, nice_list = _split(skills), _split(nice)
    if use_ai:
        rs = _run_ai(services.suggest_role_skills, conn, title, desc)
        desc = desc or rs["description"]
        required = required or rs["required_skills"]
        nice_list = nice_list or rs["nice_to_have"]
    try:
        rid = roles.add_role(conn, title, description=desc, required_skills=required, nice_to_have=nice_list, priority=priority)
    except Exception as e:  # sqlite IntegrityError on duplicate title
        _fail(f"could not add role: {e}")
    console.print(f"Added role #{rid}: [bold]{title}[/bold]")
    if required:
        console.print(f"Required: {', '.join(required)}")
    if nice_list:
        console.print(f"Nice to have: {', '.join(nice_list)}")


@role_app.command("list")
def role_list():
    """List target roles."""
    conn = connect()
    rs = roles.list_roles(conn)
    if not rs:
        console.print("No target roles yet. Add one with [bold]jobhunt role add \"Backend Engineer\" --ai[/bold].")
        return
    t = Table(box=box.SIMPLE_HEAD)
    t.add_column("#", justify="right")
    t.add_column("P", justify="right")
    t.add_column("Role")
    t.add_column("Required skills")
    for r in rs:
        t.add_row(str(r["id"]), str(r["priority"]), r["title"], ", ".join(r["required_skills"][:8]))
    console.print(t)


@role_app.command("show")
def role_show(role: str = typer.Argument(..., help="Role id or title")):
    """Show a role, its skill requirements and your coverage."""
    conn = connect()
    try:
        r = roles.get_role(conn, role)
    except KeyError as e:
        _fail(str(e))
    have = {k for k in ledger.skill_map(conn)}
    lines = [f"[bold]{r['title']}[/bold] (priority {r['priority']})"]
    if r["description"]:
        lines += ["", r["description"]]
    for label, items in (("Required", r["required_skills"]), ("Nice to have", r["nice_to_have"])):
        if items:
            lines += ["", f"[bold]{label}[/bold]"]
            for s in items:
                mark = "[green]have[/green]" if s.lower() in have else "[red]gap[/red] "
                lines.append(f"  {mark}  {s}")
    console.print(Panel("\n".join(lines), title=f"Role #{r['id']}"))


@role_app.command("set-skills")
def role_set_skills(
    role: str,
    skills: Optional[str] = typer.Option(None, "--skills"),
    nice: Optional[str] = typer.Option(None, "--nice"),
    desc: Optional[str] = typer.Option(None, "--desc"),
    priority: Optional[int] = typer.Option(None, "--priority", "-p"),
):
    """Replace a role's skill lists or description."""
    conn = connect()
    try:
        r = roles.get_role(conn, role)
    except KeyError as e:
        _fail(str(e))
    roles.update_role(conn, r["id"], description=desc, required_skills=_split(skills), nice_to_have=_split(nice), priority=priority)
    console.print(f"Updated role #{r['id']}")


# --- jobs --------------------------------------------------------------------


@job_app.command("add")
def job_add(
    company: str,
    title: str,
    url: Optional[str] = typer.Option(None, "--url", "-u"),
    location: Optional[str] = typer.Option(None, "--location", "-l"),
    role: Optional[str] = typer.Option(None, "--role", "-r", help="Target role id or title"),
    jd: Optional[Path] = typer.Option(None, "--jd", help="File with the job description (.txt/.md/.pdf)"),
    jd_text: Optional[str] = typer.Option(None, "--jd-text", help="Job description inline"),
    stdin: bool = typer.Option(False, "--stdin", help="Read the job description from stdin"),
    analyze: bool = typer.Option(False, "--analyze", "-A", help="Run fit analysis right away"),
):
    """Save a job posting. Add the description now or later with `job jd`."""
    conn = connect()
    role_id = None
    if role:
        try:
            role_id = roles.get_role(conn, role)["id"]
        except KeyError as e:
            _fail(str(e))
    try:
        text = _read_text_arg(jd, jd_text, stdin)
    except (FileNotFoundError, ValueError) as e:
        _fail(str(e))
    jid = jobs.add_job(conn, company, title, url=url, location=location, role_id=role_id, jd_text=text)
    console.print(f"Saved job #{jid}: [bold]{title}[/bold] at {company}")
    if analyze:
        if not text:
            _fail("cannot analyze without a job description; add one with --jd, --jd-text or --stdin")
        job_analyze(jid)


@job_app.command("jd")
def job_jd(
    job_id: int,
    jd: Optional[Path] = typer.Option(None, "--jd", help="File with the job description"),
    jd_text: Optional[str] = typer.Option(None, "--jd-text"),
    stdin: bool = typer.Option(False, "--stdin"),
):
    """Attach or replace the job description."""
    conn = connect()
    try:
        jobs.get_job(conn, job_id)
        text = _read_text_arg(jd, jd_text, stdin)
    except (KeyError, FileNotFoundError, ValueError) as e:
        _fail(str(e))
    if not text:
        _fail("provide --jd, --jd-text or --stdin")
    jobs.set_jd(conn, job_id, text)
    console.print(f"Updated description for job #{job_id} ({len(text)} chars)")


@job_app.command("list")
def job_list(
    status: Optional[str] = typer.Option(None, "--status", "-s"),
    open_only: bool = typer.Option(False, "--open", help="Hide rejected and withdrawn"),
):
    """List saved jobs."""
    conn = connect()
    js = jobs.list_jobs(conn, status=status, include_closed=not open_only)
    if not js:
        console.print("No jobs yet. Save one with [bold]jobhunt job add \"Company\" \"Title\" --jd posting.txt[/bold].")
        return
    t = Table(box=box.SIMPLE_HEAD)
    t.add_column("#", justify="right")
    t.add_column("Company")
    t.add_column("Title")
    t.add_column("Status")
    t.add_column("Fit", justify="right")
    t.add_column("Role")
    t.add_column("Updated")
    for j in js:
        fit = "" if j["fit_score"] is None else str(j["fit_score"])
        t.add_row(str(j["id"]), j["company"], j["title"], j["status"], fit, j["role_title"] or "", j["updated_at"][:10])
    console.print(t)


@job_app.command("show")
def job_show(job_id: int):
    """Show a job, its analysis summary, notes and history."""
    conn = connect()
    try:
        j = jobs.get_job(conn, job_id)
    except KeyError as e:
        _fail(str(e))
    lines = [f"[bold]{j['title']}[/bold] at [bold]{j['company']}[/bold]", f"status: {j['status']}"]
    for k in ("location", "url", "role_title", "applied_at"):
        if j.get(k):
            lines.append(f"{k}: {j[k]}")
    a = j["analysis"]
    if a:
        lines += ["", f"[bold]Fit {j['fit_score']}/100[/bold]", a["fit_summary"], ""]
        lines.append(f"[green]matched[/green]: {', '.join(a['matched_skills']) or '-'}")
        lines.append(f"[red]missing[/red]: {', '.join(a['missing_skills']) or '-'}")
        if a.get("red_flags"):
            lines.append(f"[yellow]red flags[/yellow]: {'; '.join(a['red_flags'])}")
    elif j["jd_text"]:
        lines += ["", "Not analyzed yet. Run [bold]jobhunt job analyze " + str(job_id) + "[/bold]."]
    else:
        lines += ["", "No job description attached. Run [bold]jobhunt job jd " + str(job_id) + " --jd file.txt[/bold]."]
    if j["notes"]:
        lines += ["", "[bold]Notes[/bold]", j["notes"]]
    console.print(Panel("\n".join(lines), title=f"Job #{j['id']}"))
    t = Table(title="History", box=box.SIMPLE)
    t.add_column("When")
    t.add_column("Status")
    t.add_column("Note")
    for h in jobs.job_history(conn, job_id):
        t.add_row(h["at"], h["to_status"], h["note"] or "")
    console.print(t)


@job_app.command("analyze")
def job_analyze(job_id: int):
    """Score fit against your ledger and generate tailored bullets and a cover letter."""
    conn = connect()
    try:
        j = jobs.get_job(conn, job_id)
    except KeyError as e:
        _fail(str(e))
    if not j["jd_text"]:
        _fail(f"job #{job_id} has no description; add one with `jobhunt job jd {job_id} --jd file.txt`")

    result = _run_ai(services.analyze_job, conn, job_id)
    a = result["analysis"]
    bullets_md = result["bullets_md"]

    score = a["fit_score"]
    color = "green" if score >= 75 else "yellow" if score >= 50 else "red"
    console.print(Panel(
        f"[bold {color}]Fit {score}/100[/bold {color}]\n\n{a['fit_summary']}\n\n"
        f"[green]matched[/green]: {', '.join(a['matched_skills']) or '-'}\n"
        f"[red]missing[/red]: {', '.join(a['missing_skills']) or '-'}"
        + (f"\n[yellow]red flags[/yellow]: {'; '.join(a['red_flags'])}" if a["red_flags"] else ""),
        title=f"{j['title']} at {j['company']}",
    ))
    console.print(Markdown("## Tailored bullets\n\n" + bullets_md))
    console.print(Markdown("## Cover letter\n\n" + a["cover_letter"]))
    console.print(f"\nFiles written to [bold]{result['folder']}[/bold]")
    if a["missing_skills"]:
        console.print("Missing skills feed the roadmap: [bold]jobhunt roadmap generate <role> --include-jobs[/bold]")


@job_app.command("materials")
def job_materials(job_id: int):
    """Print the latest generated bullets and cover letter."""
    conn = connect()
    mats = jobs.get_materials(conn, job_id)
    if not mats:
        console.print(f"No materials for job #{job_id}. Run [bold]jobhunt job analyze {job_id}[/bold].")
        return
    latest: dict[str, dict] = {}
    for m in mats:
        latest[m["kind"]] = m
    for kind, m in latest.items():
        console.print(Markdown(f"## {kind.replace('_', ' ').title()}\n\n{m['content']}"))


@job_app.command("status")
def job_status(job_id: int, new_status: str = typer.Argument(..., help="|".join(JOB_STATUSES)), note: Optional[str] = typer.Option(None, "--note", "-n")):
    """Move a job through the pipeline: saved, applied, screening, interview, offer, rejected, withdrawn."""
    conn = connect()
    try:
        jobs.set_status(conn, job_id, new_status, note)
    except (KeyError, ValueError) as e:
        _fail(str(e))
    console.print(f"Job #{job_id} is now [bold]{new_status}[/bold]")


@job_app.command("note")
def job_note(job_id: int, text: str):
    """Append a dated note to a job."""
    conn = connect()
    try:
        jobs.add_note(conn, job_id, text)
    except KeyError as e:
        _fail(str(e))
    console.print(f"Noted on job #{job_id}")


@job_app.command("funnel")
def job_funnel():
    """Counts per pipeline stage."""
    conn = connect()
    f = jobs.funnel(conn)
    t = Table(box=box.SIMPLE_HEAD)
    t.add_column("Stage")
    t.add_column("Jobs", justify="right")
    for s in JOB_STATUSES:
        t.add_row(s, str(f[s]))
    console.print(t)


# --- roadmap -----------------------------------------------------------------


@roadmap_app.command("generate")
def roadmap_generate(
    role: str = typer.Argument(..., help="Role id or title"),
    hours: int = typer.Option(8, "--hours", "-h", help="Hours per week you can invest"),
    weeks: int = typer.Option(12, "--weeks", "-w", help="Planning horizon in weeks"),
    include_jobs: bool = typer.Option(True, "--include-jobs/--no-jobs", help="Feed saved JDs linked to this role"),
):
    """Build a prioritised skill-up plan for a role from your ledger gaps."""
    conn = connect()
    try:
        r = roles.get_role(conn, role)
    except KeyError as e:
        _fail(str(e))
    result = _run_ai(services.generate_roadmap, conn, r, hours, weeks, include_jobs)

    console.print(Panel(result["summary"], title=f"Roadmap for {r['title']}"))
    if result["leverage_existing"]:
        console.print("[bold]Lean on:[/bold] " + "; ".join(result["leverage_existing"]))
    _print_roadmap(conn, r, include_closed=False)
    console.print(
        f"\nSaved {len(result['item_ids'])} items. Mark progress with [bold]jobhunt roadmap start/done <id>[/bold]."
    )


def _print_roadmap(conn, r: dict, include_closed: bool):
    items = roles.list_roadmap(conn, r["id"], include_closed=include_closed)
    if not items:
        console.print(f"No roadmap for {r['title']} yet. Run [bold]jobhunt roadmap generate \"{r['title']}\"[/bold].")
        return
    total = sum((i["est_weeks"] or 0) for i in items if i["status"] in ("todo", "in_progress"))
    t = Table(title=f"{r['title']} roadmap  (~{total:g} weeks open)", box=box.SIMPLE_HEAD)
    t.add_column("#", justify="right")
    t.add_column("P", justify="right")
    t.add_column("Skill")
    t.add_column("Weeks", justify="right")
    t.add_column("Status")
    t.add_column("Why")
    for i in items:
        t.add_row(str(i["id"]), str(i["priority"]), i["skill"], f"{i['est_weeks'] or 0:g}", i["status"], (i["why"] or "")[:80])
    console.print(t)


@roadmap_app.command("show")
def roadmap_show(role: str, show_all: bool = typer.Option(False, "--all", "-a", help="Include done and skipped")):
    """Show the roadmap for a role."""
    conn = connect()
    try:
        r = roles.get_role(conn, role)
    except KeyError as e:
        _fail(str(e))
    _print_roadmap(conn, r, include_closed=show_all)


@roadmap_app.command("item")
def roadmap_item(item_id: int):
    """Show one roadmap item with its steps and resources."""
    conn = connect()
    try:
        i = roles.get_item(conn, item_id)
    except KeyError as e:
        _fail(str(e))
    body = [f"[bold]{i['skill']}[/bold]  priority {i['priority']}  ~{i['est_weeks'] or 0:g} weeks  [{i['status']}]", "", i["why"] or ""]
    if i["actions"]:
        body += ["", "[bold]Steps[/bold]"] + [f"  {n}. {a}" for n, a in enumerate(i["actions"], 1)]
    if i["resources"]:
        body += ["", "[bold]Resources[/bold]"] + [f"  - {res}" for res in i["resources"]]
    console.print(Panel("\n".join(body), title=f"Roadmap item #{item_id}"))


@roadmap_app.command("start")
def roadmap_start(item_id: int):
    """Mark an item in progress."""
    conn = connect()
    try:
        roles.set_item_status(conn, item_id, "in_progress")
    except (KeyError, ValueError) as e:
        _fail(str(e))
    console.print(f"Item #{item_id} in progress")


@roadmap_app.command("skip")
def roadmap_skip(item_id: int):
    """Skip an item you do not intend to pursue."""
    conn = connect()
    try:
        roles.set_item_status(conn, item_id, "skipped")
    except (KeyError, ValueError) as e:
        _fail(str(e))
    console.print(f"Item #{item_id} skipped")


@roadmap_app.command("done")
def roadmap_done(
    item_id: int,
    level: Optional[str] = typer.Option("intermediate", "--level", "-l", help="Skill level to record in the ledger"),
    proof: Optional[str] = typer.Option(None, "--proof", help="URL or note for the proof artifact"),
    no_ledger: bool = typer.Option(False, "--no-ledger", help="Do not add the skill to the ledger"),
):
    """Complete an item and record the new skill in your ledger."""
    conn = connect()
    try:
        i = roles.get_item(conn, item_id)
        eid = services.complete_roadmap_item(conn, item_id, level=level, proof=proof, add_to_ledger=not no_ledger)
    except (KeyError, ValueError) as e:
        _fail(str(e))
    if eid is not None:
        console.print(f"Item #{item_id} done. Added skill #{eid} [bold]{i['skill']}[/bold] ({level}) to the ledger.")
    else:
        console.print(f"Item #{item_id} done")


# --- discover ----------------------------------------------------------------


@discover_app.command("run")
def discover_run(
    query: Optional[str] = typer.Argument(None, help="Search text; defaults to your top target role"),
    location: Optional[str] = typer.Option(None, "--location", "-l"),
    remote: Optional[bool] = typer.Option(None, "--remote/--any-location"),
    country: Optional[str] = typer.Option(None, "--country", help="Two-letter code for Adzuna/JSearch, e.g. in, us"),
    role: Optional[str] = typer.Option(None, "--role", "-r", help="Target role id or title to link results to"),
):
    """Search all enabled sources and store matching openings."""
    from . import discover

    conn = connect()
    role_id = None
    if role:
        try:
            role_id = roles.get_role(conn, role)["id"]
        except KeyError as e:
            _fail(str(e))
    if not query:
        rs = roles.list_roles(conn)
        if not rs:
            _fail("give a query or add a target role first")
        query = rs[0]["title"]
        role_id = role_id or rs[0]["id"]
    try:
        with console.status(f"Searching for '{query}'..."):
            res = discover.run_search(conn, query, location=location, remote_only=remote, country=country, role_id=role_id)
    except ValueError as e:
        _fail(str(e))
    t = Table(title=f"{res['total']} results, {res['new']} new", box=box.SIMPLE_HEAD)
    t.add_column("Source")
    t.add_column("Found", justify="right")
    t.add_column("New", justify="right")
    t.add_column("Note")
    for sid, r in res["per_source"].items():
        t.add_row(sid, str(r.get("count", 0)), str(r.get("new", "")), f"[red]{r['error']}[/red]" if r.get("error") else "")
    console.print(t)
    discover_list(min_score=0, source=None, status="new", limit=15)


@discover_app.command("list")
def discover_list(
    min_score: int = typer.Option(0, "--min-score"),
    source: Optional[str] = typer.Option(None, "--source"),
    status: str = typer.Option("new", "--status", help="new | saved | dismissed"),
    limit: int = typer.Option(30, "--limit", "-n"),
):
    """Show discovered openings ranked by match with your ledger."""
    from . import discover

    conn = connect()
    items = discover.list_discovered(conn, status=status, source=source, min_score=min_score, limit=limit)
    if not items:
        console.print("Nothing found yet. Run [bold]jobhunt discover run \"Your Role\"[/bold].")
        return
    t = Table(box=box.SIMPLE_HEAD)
    t.add_column("#", justify="right")
    t.add_column("Match", justify="right")
    t.add_column("Title", overflow="fold")
    t.add_column("Company", overflow="fold")
    t.add_column("Where", overflow="fold")
    t.add_column("Source")
    t.add_column("Posted")
    for d in items:
        where = ("Remote" if d["remote"] else "") + (f" {d['location']}" if d["location"] and d["location"] != "Remote" else "")
        src = d["source"] + (f" ({d['publisher']})" if d.get("publisher") else "")
        t.add_row(str(d["id"]), str(d["match_score"]), d["title"], d["company"] or "", where.strip(), src, (d["posted_at"] or "")[:10])
    console.print(t)
    console.print("Open one: [bold]jobhunt discover show <id>[/bold]   Save to tracker: [bold]jobhunt discover save <id>[/bold]")


@discover_app.command("show")
def discover_show(did: int):
    """Details and apply link for one discovered opening."""
    from . import discover

    conn = connect()
    try:
        d = discover.get_discovered(conn, did)
    except KeyError as e:
        _fail(str(e))
    body = [f"[bold]{d['title']}[/bold] at [bold]{d['company'] or '?'}[/bold]", f"{d['location'] or ''} {'(remote)' if d['remote'] else ''}".strip(),
            f"Match {d['match_score']}/100  matched: {', '.join(d['matched_skills']) or 'none'}",
            f"Source: {d['source']}{' via ' + d['publisher'] if d.get('publisher') else ''}   Posted: {(d['posted_at'] or '?')[:10]}",
            f"Apply: {d['url']}", ""]
    body.append((d["description"] or "")[:1500])
    console.print(Panel("\n".join(body), title=f"Discovered #{did}"))


@discover_app.command("save")
def discover_save(did: int, role: Optional[str] = typer.Option(None, "--role", "-r")):
    """Copy a discovered opening into your applications tracker."""
    from . import discover

    conn = connect()
    role_id = None
    if role:
        try:
            role_id = roles.get_role(conn, role)["id"]
        except KeyError as e:
            _fail(str(e))
    try:
        d = discover.save_to_tracker(conn, did, role_id=role_id)
    except KeyError as e:
        _fail(str(e))
    console.print(f"Saved as job #{d['saved_job_id']}. Analyze it with [bold]jobhunt job analyze {d['saved_job_id']}[/bold].")


@discover_app.command("dismiss")
def discover_dismiss(did: int):
    """Hide an opening you are not interested in."""
    from . import discover

    conn = connect()
    try:
        discover.set_status(conn, did, "dismissed")
    except KeyError as e:
        _fail(str(e))
    console.print(f"Dismissed #{did}")


@discover_app.command("links")
def discover_links(query: str, location: str = typer.Option("", "--location", "-l"), remote: bool = typer.Option(False, "--remote")):
    """Print pre-filled search links for LinkedIn, Naukri, Indeed and others."""
    from . import discover

    for link in discover.external_links(query, location, remote):
        console.print(f"[bold]{link['label']:12s}[/bold] {link['url']}")


@discover_app.command("sources")
def discover_sources(
    enable: Optional[str] = typer.Option(None, "--enable", help="Comma-separated source ids to enable (replaces the list)"),
    location: Optional[str] = typer.Option(None, "--location"),
    country: Optional[str] = typer.Option(None, "--country"),
    remote: Optional[bool] = typer.Option(None, "--remote/--any-location"),
    set_key: Optional[str] = typer.Option(None, "--set-key", help="name=value, e.g. rapidapi_key=abc or adzuna_app_id=..."),
):
    """Show or change job sources, default location and API keys."""
    from . import discover

    conn = connect()
    keys = None
    if set_key:
        if "=" not in set_key:
            _fail("--set-key expects name=value")
        name, _, value = set_key.partition("=")
        keys = {name.strip(): value.strip()}
    try:
        discover.update_discover_settings(conn, location=location, country=country, remote_only=remote,
                                          sources_enabled=_split(enable), keys=keys)
    except ValueError as e:
        _fail(str(e))
    info = discover.discover_settings(conn)
    console.print(f"Default location: [bold]{info['location'] or '(any)'}[/bold] | country: {info['country']} | remote only: {info['remote_only']}")
    t = Table(box=box.SIMPLE_HEAD)
    t.add_column("Source")
    t.add_column("Enabled")
    t.add_column("Keys", overflow="fold")
    t.add_column("Notes", overflow="fold")
    for s in info["sources"]:
        keys_txt = ", ".join(f"{k['setting']}={k['status'] or 'missing'}" for k in s["keys"]) or "none needed"
        t.add_row(s["id"], "yes" if s["enabled"] else "no", keys_txt, s["notes"])
    console.print(t)


# --- settings ----------------------------------------------------------------


@settings_app.command("show")
def settings_show():
    """Current provider, model and which providers have keys."""
    conn = connect()
    info = settings.describe(conn)
    console.print(f"Active: [bold]{info['provider']}[/bold] | model [bold]{info['model']}[/bold] | "
                  + ("[green]key configured[/green]" if info["ai_configured"] else "[red]no key[/red]"))
    t = Table(box=box.SIMPLE_HEAD)
    t.add_column("Provider", no_wrap=True)
    t.add_column("Model", overflow="fold")
    t.add_column("Key", no_wrap=True)
    t.add_column("Env var", overflow="fold")
    for p in info["providers"]:
        marker = "* " if p["id"] == info["provider"] else "  "
        key = f"{p['key_status']} {p['key_hint']}" if p["key_status"] else "[dim]none[/dim]"
        t.add_row(marker + p["label"], p["model"] or f"[dim]{p['default_model']}[/dim]", key, ", ".join(p["env_keys"]))
    console.print(t)


@settings_app.command("set")
def settings_set(
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="|".join(settings.PROVIDERS)),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model id for the provider"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="API key to save for the provider"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Override the API base URL"),
    for_provider: Optional[str] = typer.Option(None, "--for", help="Apply model/key/base-url to this provider instead of the active one"),
):
    """Choose the provider, set its model, or save an API key."""
    conn = connect()
    target = for_provider or provider or settings.current_provider_id(conn)
    try:
        settings.update(
            conn, provider=provider, model=model, base_url=base_url, model_provider=target,
            api_keys={target: key} if key is not None else None,
        )
    except ValueError as e:
        _fail(str(e))
    settings_show()


@settings_app.command("clear-key")
def settings_clear_key(provider: str):
    """Remove a saved API key (environment variables are unaffected)."""
    conn = connect()
    try:
        settings.update(conn, api_keys={provider: ""})
    except ValueError as e:
        _fail(str(e))
    console.print(f"Cleared saved key for {provider}")


@settings_app.command("test")
def settings_test():
    """Make a tiny call to the active provider and report latency."""
    conn = connect()
    res = _run_ai(services.test_ai, conn)
    console.print(f"[green]OK[/green] {res['provider']} | {res['model']} | {res['latency_ms']} ms | reply: {res['reply']}")


if __name__ == "__main__":
    app()
