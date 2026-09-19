"""AI features: resume extraction, job analysis, role skills, roadmaps.

Prompts and schemas live here. The provider that runs them is chosen in
settings; see providers.py for the Anthropic and OpenAI-compatible backends.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .providers import AIError, parse
from .settings import ProviderConfig

__all__ = ["AIError", "extract_resume", "analyze_job", "role_skills", "build_roadmap"]


# --- schemas -----------------------------------------------------------------


class ExtractedEntry(BaseModel):
    kind: str = Field(description="experience | education | skill | certification | project | achievement")
    title: str
    org: str | None = None
    start_date: str | None = Field(default=None, description="YYYY-MM or YYYY when known")
    end_date: str | None = Field(default=None, description="YYYY-MM, YYYY, or null if ongoing")
    description: str | None = Field(default=None, description="Concise bullet-style summary, 1-4 lines")
    skills: list[str] = Field(default_factory=list, description="Tools, languages, methods used")
    level: str | None = Field(
        default=None, description="For kind=skill only: beginner | intermediate | advanced | expert"
    )
    url: str | None = None


class ExtractedLedger(BaseModel):
    entries: list[ExtractedEntry]
    notes: str = Field(description="Anything ambiguous the user should double-check")


class TailoredBullet(BaseModel):
    ledger_ref: str = Field(description="Which ledger entry this bullet is grounded in")
    bullet: str


class JobAnalysis(BaseModel):
    required_skills: list[str]
    nice_to_have: list[str]
    matched_skills: list[str] = Field(description="Required or nice-to-have skills evidenced in the ledger")
    missing_skills: list[str] = Field(description="Required skills with no evidence in the ledger")
    fit_score: int = Field(ge=0, le=100)
    fit_summary: str = Field(description="2-4 sentences: why this score, biggest strengths and gaps")
    red_flags: list[str] = Field(description="Concerns about the posting itself, or empty")
    keywords_to_include: list[str] = Field(
        description="Exact phrases from the JD worth mirroring in the application"
    )
    tailored_bullets: list[TailoredBullet] = Field(
        description="5-8 resume bullets rewritten for this job, grounded only in ledger facts"
    )
    cover_letter: str = Field(description="A complete, specific cover letter under 300 words in Markdown")


class RoleSkills(BaseModel):
    description: str = Field(description="One paragraph on what this role typically does")
    required_skills: list[str]
    nice_to_have: list[str]


class RoadmapItem(BaseModel):
    skill: str
    priority: int = Field(ge=1, le=3, description="1 = do first, 3 = later")
    why: str = Field(description="Why this matters for the target role, referencing the gap")
    actions: list[str] = Field(description="3-6 concrete steps, each finishable in a sitting or a week")
    resources: list[str] = Field(description="Named courses, docs, books or projects. No invented URLs.")
    est_weeks: float = Field(description="Realistic weeks at the stated hours per week")
    proof: str = Field(description="What artifact will prove the skill: a repo, cert, demo, blog post")


class Roadmap(BaseModel):
    summary: str = Field(description="Where the person stands versus the role and the overall plan")
    items: list[RoadmapItem]
    leverage_existing: list[str] = Field(description="Ledger strengths to emphasise rather than learn")


# --- prompts -----------------------------------------------------------------


def _ledger_block(profile_md: str) -> str:
    return "The candidate's ledger (the only source of truth about them):\n\n" + profile_md


def extract_resume(cfg: ProviderConfig, resume_text: str) -> ExtractedLedger:
    system = [
        "You turn a resume into ledger entries. One entry per job, degree, certification, "
        "project or notable achievement. Add standalone `skill` entries only for skills the "
        "resume states explicitly with an evident proficiency; otherwise attach skills to the "
        "entry where they were used. Never invent dates, employers or accomplishments. "
        "Keep descriptions faithful to the resume's wording, trimmed to essentials."
    ]
    return parse(cfg, system, f"Resume:\n\n{resume_text}", ExtractedLedger, effort="medium")


def analyze_job(cfg: ProviderConfig, profile_md: str, company: str, title: str, jd_text: str) -> JobAnalysis:
    system = [
        "You are a rigorous career coach and resume writer. Compare a job description against "
        "the candidate's ledger. Be honest about gaps; a fit score above 80 means they clear "
        "every hard requirement. Tailored bullets and the cover letter must be grounded only in "
        "ledger facts, never fabricated. Prefer concrete outcomes and numbers already in the "
        "ledger. Write in the candidate's voice, first person, plain and direct, no cliches.",
        _ledger_block(profile_md),
    ]
    user = f"Job: {title} at {company}\n\nJob description:\n\n{jd_text}"
    return parse(cfg, system, user, JobAnalysis, effort="high")


def role_skills(cfg: ProviderConfig, title: str, hint: str | None = None) -> RoleSkills:
    system = [
        "You describe what hiring managers currently expect for a role. List skills as short "
        "canonical names (for example 'PostgreSQL', 'System design', 'Kubernetes'), "
        "8-15 required and 5-10 nice-to-have."
    ]
    user = f"Role: {title}" + (f"\nContext from the candidate: {hint}" if hint else "")
    return parse(cfg, system, user, RoleSkills, effort="medium")


def build_roadmap(
    cfg: ProviderConfig,
    profile_md: str,
    role: dict,
    jd_samples: list[str],
    hours_per_week: int,
    horizon_weeks: int,
) -> Roadmap:
    system = [
        "You design skill-up roadmaps. Compare the candidate's ledger with a target role and "
        "produce a prioritised, realistic plan. Focus on gaps that actually block hiring; do not "
        "pad with skills the ledger already evidences. Each item must end in a concrete proof "
        "artifact. Total estimated weeks across priority-1 items should fit the stated horizon. "
        "Name real, well-known resources; if unsure of a URL, give the name only.",
        _ledger_block(profile_md),
    ]
    required = ", ".join(role.get("required_skills") or []) or "(derive from role and job descriptions)"
    nice = ", ".join(role.get("nice_to_have") or []) or "(none given)"
    parts = [
        f"Target role: {role['title']}",
        f"Description: {role.get('description') or '(none given)'}",
        f"Required skills: {required}",
        f"Nice to have: {nice}",
        f"Available time: {hours_per_week} hours/week for about {horizon_weeks} weeks.",
    ]
    if jd_samples:
        parts.append("Representative job descriptions the candidate is targeting:")
        for i, jd in enumerate(jd_samples, 1):
            parts.append(f"--- JD {i} ---\n{jd[:6000]}")
    return parse(cfg, system, "\n\n".join(parts), Roadmap, effort="high")
