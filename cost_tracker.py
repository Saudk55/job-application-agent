# cost_tracker.py
# Lightweight per-run cost estimator. Modules call record() as they make API
# calls; run_all prints a summary at the end so we always know what a run costs.
#
# Prices are rough averages, not exact billing. Claude Sonnet 4.5 is
# $3 / 1M input tokens and $15 / 1M output tokens; the per-call figures below
# bake in typical prompt/response sizes for each call type in this app.

# Estimated USD cost per call type.
UNIT_COST = {
    "prefilter": 0.005,   # batch title pre-filter (matcher)
    "score": 0.007,       # per-job relevance scoring (matcher)
    "tailor": 0.055,      # ATS CV tailoring on Opus 4.8 ($5/$25 per M) — every matched job, capped
    "cover": 0.008,       # cover letter generation (cv_tailor, rare)
}

# Apify LinkedIn actor: ~$1 per 1,000 results scraped.
LINKEDIN_PER_JOB = 0.001

_counts = {k: 0 for k in UNIT_COST}
_linkedin_jobs = 0


def reset():
    global _counts, _linkedin_jobs
    _counts = {k: 0 for k in UNIT_COST}
    _linkedin_jobs = 0


def record(kind: str, n: int = 1):
    """Record n API calls of a given kind (prefilter/score/tailor/cover)."""
    if kind in _counts:
        _counts[kind] += n


def record_linkedin(n_jobs: int):
    """Record LinkedIn jobs scraped (drives Apify cost)."""
    global _linkedin_jobs
    _linkedin_jobs += n_jobs


def estimate() -> dict:
    claude = sum(_counts[k] * UNIT_COST[k] for k in _counts)
    linkedin = _linkedin_jobs * LINKEDIN_PER_JOB
    return {
        "counts": dict(_counts),
        "linkedin_jobs": _linkedin_jobs,
        "claude_usd": round(claude, 3),
        "linkedin_usd": round(linkedin, 3),
        "total_usd": round(claude + linkedin, 3),
    }


def summary_line() -> str:
    e = estimate()
    c = e["counts"]
    return (
        f"💰 Est. run cost: ${e['total_usd']:.2f} "
        f"(Claude ${e['claude_usd']:.2f} | LinkedIn ${e['linkedin_usd']:.2f})\n"
        f"   Calls: {c['score']} scored, {c['tailor']} CVs tailored (LLM), "
        f"{c['cover']} cover letters, {c['prefilter']} prefilters | "
        f"{e['linkedin_jobs']} LinkedIn jobs scraped"
    )
