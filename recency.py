# recency.py
# Freshness filter: keep only recently-posted jobs so we apply while a listing
# is still new (first-mover advantage). Kept deliberately conservative — a job is
# only DROPPED when we can confidently read a post date that's too old. Jobs with
# no parseable date, or from sources that already filter by date server-side
# (LinkedIn's f_TPR window), are always KEPT so we never silently lose a good job.

from datetime import datetime, timezone, timedelta

# Sources that filter by post date on their side, so we trust them as-is.
TRUSTED_SOURCES = ("LinkedIn",)


def _parse_date(value) -> datetime | None:
    """Best-effort parse of the many date shapes our sources emit (ISO 8601,
    unix epoch, RSS pubDate). Returns a tz-aware UTC datetime or None."""
    if value is None or value == "":
        return None

    # Unix epoch (int/float or a bare numeric string).
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None

    s = str(value).strip()
    if not s:
        return None
    if s.isdigit():
        try:
            return datetime.fromtimestamp(int(s), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None

    # ISO 8601 (The Muse, RemoteOK, Remotive). Tolerate a trailing 'Z'.
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    # RSS pubDate and a plain date fallback (WeWorkRemotely etc.).
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def filter_recent(jobs: list, max_age_days: int,
                  trusted_sources=TRUSTED_SOURCES) -> list:
    """Return only jobs posted within `max_age_days`.

    Drops a job ONLY when it has a parseable `date_posted` older than the cutoff.
    Trusted sources and undated jobs pass through unchanged.
    """
    if not max_age_days:
        return jobs

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    kept, dropped, unchecked = [], 0, 0
    for job in jobs:
        if job.get("source") in trusted_sources:
            unchecked += 1
            kept.append(job)
            continue
        dt = _parse_date(job.get("date_posted"))
        if dt is None:
            unchecked += 1
            kept.append(job)
            continue
        if dt < cutoff:
            dropped += 1
            continue
        kept.append(job)

    print(f"🕒 Recency (<= {max_age_days}d): kept {len(kept)} "
          f"(incl. {unchecked} undated/trusted), dropped {dropped} stale")
    return kept
