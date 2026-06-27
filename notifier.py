# notifier.py

import os
import re
import smtplib
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from dotenv import load_dotenv

load_dotenv()

# How many jobs to show in full in the email. The rest stay in the sheet.
# Keeping this small is deliberate: a short list of clear actions converts
# far better than an exhaustive dump (the 70-unapplied problem).
MAX_EMAIL_JOBS = 5
# A "To Apply" row older than this many days is flagged as stale/aging.
STALE_AFTER_DAYS = 5

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def _get_gsheet():
    """Connect to Google Sheet."""
    creds = Credentials.from_service_account_file("google_credentials.json", scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(os.getenv("GOOGLE_SHEET_ID"))


def get_user_tab(user: dict):
    """Get or create a worksheet tab for this user."""
    sheet = _get_gsheet()
    tab_name = user["sheet_tab"]

    try:
        ws = sheet.worksheet(tab_name)
    except:
        ws = sheet.add_worksheet(title=tab_name, rows=1000, cols=20)
        headers = [
            "Date Found", "Score", "Verdict", "Title", "Company",
            "Location", "Source", "Apply Link", "CV Link",
            "Status", "Applied Date", "Response", "Stage", "Notes"
        ]
        ws.append_row(headers)
        ws.format("A1:N1", {"textFormat": {"bold": True}})

        # Status dropdown on column J (index 9)
        sheet.batch_update({
            "requests": [{
                "setDataValidation": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": 1,
                        "startColumnIndex": 9,
                        "endColumnIndex": 10
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [
                                {"userEnteredValue": "To Apply"},
                                {"userEnteredValue": "Applied"},
                                {"userEnteredValue": "No Response"},
                                {"userEnteredValue": "Phone Screen"},
                                {"userEnteredValue": "Interview"},
                                {"userEnteredValue": "Offer"},
                                {"userEnteredValue": "Rejected"}
                            ]
                        },
                        "showCustomUi": True
                    }
                }
            }]
        })

    return ws


def get_stats(ws) -> dict:
    """Pull live stats from a worksheet."""
    try:
        all_records = ws.get_all_values()
        if len(all_records) <= 1:
            return {"total": 0}

        rows = all_records[1:]
        # Status is now column J (index 9)
        statuses = [row[9] if len(row) > 9 else "" for row in rows]

        return {
            "total": len(rows),
            "to_apply": statuses.count("To Apply"),
            "applied": statuses.count("Applied"),
            "no_response": statuses.count("No Response"),
            "phone_screen": statuses.count("Phone Screen"),
            "interview": statuses.count("Interview"),
            "offer": statuses.count("Offer"),
            "rejected": statuses.count("Rejected"),
        }
    except Exception as e:
        print(f"⚠ Stats fetch failed: {e}")
        return {"total": 0}


def get_stale_info(ws) -> dict:
    """Find how many 'To Apply' rows are aging, and the oldest one.

    This is what powers the urgency line in the email — the backlog of jobs
    matched but never applied to.
    """
    try:
        rows = ws.get_all_values()[1:]
    except Exception as e:
        print(f"⚠ Stale-info fetch failed: {e}")
        return {"to_apply": 0, "stale": 0, "oldest_days": 0}

    today = datetime.now().date()
    to_apply = 0
    stale = 0
    oldest_days = 0

    for row in rows:
        status = row[9] if len(row) > 9 else ""
        if status != "To Apply":
            continue
        to_apply += 1
        date_str = row[0] if row else ""
        try:
            found = datetime.strptime(date_str, "%Y-%m-%d").date()
            age = (today - found).days
            oldest_days = max(oldest_days, age)
            if age >= STALE_AFTER_DAYS:
                stale += 1
        except (ValueError, TypeError):
            continue

    return {"to_apply": to_apply, "stale": stale, "oldest_days": oldest_days}


def _md_bold_to_html(text: str) -> str:
    """Convert markdown **bold** to <strong> for the email.

    Claude writes MATCH_REASONS as `**Label**: detail`. Must run BEFORE we
    strip bullet markers — otherwise the leading `**` gets eaten as a bullet
    char and the orphaned trailing `**` shows up literally in the email.
    """
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)


def extract_match_reasons(analysis: str, limit: int = 2) -> list:
    """Pull the MATCH_REASONS bullets out of the stored Claude analysis.

    The matcher already generates *why this is a good fit* — we were throwing
    it away in the old email. This surfaces it as the core selling point.
    """
    if not analysis:
        return []

    # Grab the text between MATCH_REASONS: and the next section header.
    m = re.search(
        r"MATCH_REASONS:\s*(.*?)(?:\n\s*(?:GAPS|VERDICT|SCORE):|$)",
        analysis,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return []

    # Convert bold markers first (while the `**` pairs are still balanced),
    # then split into bullets. Strip set excludes `*` so it can't orphan one.
    block = _md_bold_to_html(m.group(1).strip())
    reasons = []
    for raw in re.split(r"\n|(?:^|\s)[-•▪]\s+", block):
        clean = raw.strip(" -•▪[]\t")
        if len(clean) > 8:
            reasons.append(clean)
    return reasons[:limit]


def build_contact_html(job: dict) -> str:
    """Render a 'who to reach out to' line when the source gave us a contact."""
    name = job.get("contact_name", "")
    url = job.get("contact_url", "")
    title = job.get("contact_title", "")

    if not name and not url:
        return ""

    label = name or "View who posted this"
    if title:
        label = f"{label} — {title}"

    if url:
        inner = f'<a href="{url}" style="color:#0a66c2;">{label}</a>'
    else:
        inner = label
    return (
        f'<p style="margin:6px 0 0 0; font-size:13px; color:#444;">'
        f'Reach out: {inner}</p>'
    )


def _dup_keys(title: str, company: str, url: str) -> set:
    """Identity keys for a job, used to catch the same role posted twice."""
    keys = set()
    u = (url or "").strip().lower().rstrip("/")
    if u and u != "n/a":
        keys.add(u)
    t = (title or "").strip().lower()
    c = (company or "").strip().lower()
    if t and c:
        keys.add(f"{t}|{c}")
    return keys


def _recent_keys(ws, within_days: int = 7) -> set:
    """Build the set of dup-keys already in the sheet within the last week."""
    try:
        rows = ws.get_all_values()[1:]
    except Exception:
        return set()

    cutoff = datetime.now().date()
    keys = set()
    for row in rows:
        date_str = row[0] if row else ""
        try:
            found = datetime.strptime(date_str, "%Y-%m-%d").date()
            if (cutoff - found).days > within_days:
                continue
        except (ValueError, TypeError):
            continue
        # cols: Date(0) ... Title(3) Company(4) ... Apply Link(7)
        title = row[3] if len(row) > 3 else ""
        company = row[4] if len(row) > 4 else ""
        url = row[7] if len(row) > 7 else ""
        keys |= _dup_keys(title, company, url)
    return keys


def save_to_sheet(jobs: list, user: dict) -> str:
    """Append matched jobs to the user's tab, skipping same-week duplicates."""
    ws = get_user_tab(user)
    today = datetime.now().strftime("%Y-%m-%d")

    # Guardrail: don't add a job that's already in the sheet this week, even
    # if it slipped past the URL tracker (e.g. same role via LinkedIn + RSS).
    seen_keys = _recent_keys(ws)

    rows_added = 0
    skipped = 0
    for job in jobs:
        job_keys = _dup_keys(job.get("title", ""), job.get("company", ""), job.get("url", ""))
        if job_keys & seen_keys:
            skipped += 1
            continue
        seen_keys |= job_keys  # also dedupe within this same batch
        analysis = job.get("ai_analysis", "")
        verdict = ""
        for line in analysis.split("\n"):
            if line.startswith("VERDICT:"):
                verdict = line.replace("VERDICT:", "").strip()

        # CV cell: tailored/variant CVs are attached to the daily email (the
        # repo is private, so raw GitHub links 404 — no usable hyperlink). For a
        # strong/weak PM fit there's no file; the user uses his master CV.
        cv_label = job.get("cv_label", "") or "CV"
        if job.get("cv_path"):
            cv_cell = f"{cv_label} (emailed)"
        else:
            cv_cell = "Use master CV"

        ws.append_row([
            today,
            job.get("relevance_score", 0),
            verdict,
            job.get("title", ""),
            job.get("company", ""),
            job.get("location", ""),
            job.get("source", ""),
            job.get("url", ""),
            cv_cell,
            "To Apply",
            "", "", "", ""
        ], value_input_option="USER_ENTERED")
        rows_added += 1

    sheet_url = f"https://docs.google.com/spreadsheets/d/{os.getenv('GOOGLE_SHEET_ID')}/edit"
    print(f"📊 Added {rows_added} jobs to '{user['sheet_tab']}' tab (skipped {skipped} same-week duplicates)")
    return sheet_url


def render_email_body(jobs: list, user: dict, sheet_url: str,
                      stats: dict, stale: dict) -> tuple:
    """Build the (subject, html_body) for the daily action email.

    Design goals (vs the old report-style email):
      - Lead with a single clear action and an urgency hook, not stats.
      - Show only the top few jobs in full; the rest live in the sheet.
      - Surface *why you're a fit* for each (we already compute it).
      - Surface a recruiter/contact to reach out to when we have one.
      - Minimal emoji, scannable, mobile-friendly.

    Pure function (no network) so it can be previewed/tested offline.
    """
    today = datetime.now().strftime("%b %d")
    name = user["name"].split()[0]

    # Rank today's matches and show only the strongest few in full.
    jobs_sorted = sorted(jobs, key=lambda j: j.get("relevance_score", 0), reverse=True)
    top_jobs = jobs_sorted[:MAX_EMAIL_JOBS]
    overflow = len(jobs_sorted) - len(top_jobs)

    # How many we're asking them to apply to today (don't overwhelm).
    apply_target = min(3, len(top_jobs))
    subject = f"Apply to {apply_target} today - {len(jobs)} new matches for {name} ({today})"

    # --- Urgency banner: the unapplied backlog is the real bottleneck ---
    backlog = stats.get("to_apply", 0)
    banner = ""
    if stale.get("stale", 0) > 0:
        banner = (
            f'<div style="background:#fff4e5; border-left:4px solid #f59e0b; '
            f'padding:12px 16px; margin:0 0 20px 0; border-radius:4px; font-size:14px;">'
            f'<strong>{stale["stale"]} jobs have been waiting {STALE_AFTER_DAYS}+ days '
            f'without an application</strong> (oldest: {stale["oldest_days"]} days). '
            f'These go stale fast — clear a few before they expire.</div>'
        )
    elif backlog > 0:
        banner = (
            f'<div style="background:#eef4ff; border-left:4px solid #2563eb; '
            f'padding:12px 16px; margin:0 0 20px 0; border-radius:4px; font-size:14px;">'
            f'You have <strong>{backlog} jobs in "To Apply"</strong>. '
            f'Pick {apply_target} and apply today.</div>'
        )

    body = f"""
    <div style="font-family: -apple-system, Segoe UI, Arial, sans-serif; max-width: 640px; margin: 0 auto; color:#1a1a1a;">

    <h2 style="margin:0 0 4px 0;">Your move, {name}: apply to {apply_target} today</h2>
    <p style="margin:0 0 20px 0; color:#555; font-size:14px;">
        {len(jobs)} new matches found {today}. Top {len(top_jobs)} below — strongest fit first.
    </p>

    {banner}

    <a href="{sheet_url}" style="display:inline-block; background:#1a73e8; color:#fff;
        padding:11px 22px; text-decoration:none; border-radius:6px; font-size:15px;
        font-weight:600; margin-bottom:8px;">Open tracker &amp; mark applied &rarr;</a>
    """

    for job in top_jobs:
        score = job.get("relevance_score", 0)
        color = "#16a34a" if score >= 8 else "#d97706"
        cv_label = job.get("cv_label", "CV") or "CV"
        if job.get("cv_path"):
            cv_html = f' &nbsp;&middot;&nbsp; <span style="color:#555;">&#128206; {cv_label} attached</span>'
        elif cv_label.startswith("Master"):
            cv_html = ' &nbsp;&middot;&nbsp; <span style="color:#888;">Use your master CV</span>'
        else:
            cv_html = ""

        reasons = extract_match_reasons(job.get("ai_analysis", ""))
        reasons_html = ""
        if reasons:
            items = "".join(
                f'<li style="margin:2px 0;">{r}</li>' for r in reasons
            )
            reasons_html = (
                f'<ul style="margin:8px 0 0 0; padding-left:18px; font-size:13px; '
                f'color:#333;">{items}</ul>'
            )

        contact_html = build_contact_html(job)
        apply_link = job.get("apply_url") or job.get("url", "")

        body += f"""
        <div style="margin:18px 0; padding:16px; border:1px solid #e5e7eb; border-radius:8px;">
            <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="border-collapse:collapse;">
                <tr>
                    <td style="font-size:16px; font-weight:700; vertical-align:baseline; padding:0;">{job.get('title')}</td>
                    <td align="right" style="white-space:nowrap; vertical-align:baseline; padding:0 0 0 14px; color:{color}; font-weight:700; font-size:14px;">{score}/10</td>
                </tr>
            </table>
            <p style="margin:4px 0 0 0; color:#555; font-size:13px;">
                {job.get('company')} &middot; {job.get('location')} &middot; {job.get('source')}
            </p>
            {reasons_html}
            {contact_html}
            <p style="margin:12px 0 0 0;">
                <a href="{apply_link}" style="display:inline-block; background:#111827; color:#fff;
                    padding:8px 18px; text-decoration:none; border-radius:5px; font-size:14px;
                    font-weight:600;">Apply now</a>{cv_html}
            </p>
        </div>
        """

    if overflow > 0:
        body += (
            f'<p style="font-size:13px; color:#555; margin:16px 0;">'
            f'+ {overflow} more match{"es" if overflow != 1 else ""} in your '
            f'<a href="{sheet_url}" style="color:#1a73e8;">tracker</a>.</p>'
        )

    # Map each attached CV to its role, so a PDF that belongs to a job below the
    # top-5 cutoff still has context. Master-CV roles have no attachment.
    attached = [j for j in jobs_sorted if j.get("cv_path")]
    if attached:
        rows = "".join(
            f'<li style="margin:2px 0;">{j.get("cv_label", "CV")} — '
            f'{j.get("title")} @ {j.get("company")}</li>'
            for j in attached
        )
        body += (
            f'<div style="margin:16px 0; padding:12px 16px; background:#f6f8fa; '
            f'border-radius:6px; font-size:13px; color:#333;">'
            f'<strong>&#128206; {len(attached)} tailored CV'
            f'{"s" if len(attached) != 1 else ""} attached</strong>'
            f'<ul style="margin:6px 0 0 0; padding-left:18px;">{rows}</ul></div>'
        )

    # Compact progress line instead of the old 8-row vanity table.
    body += f"""
    <hr style="border:none; border-top:1px solid #eee; margin:20px 0;">
    <p style="font-size:12px; color:#888; margin:0;">
        Pipeline: {stats.get('applied', 0)} applied &middot;
        {stats.get('to_apply', 0)} to apply &middot;
        {stats.get('phone_screen', 0) + stats.get('interview', 0)} in process &middot;
        {stats.get('offer', 0)} offers
    </p>
    <p style="font-size:12px; color:#aaa; margin:6px 0 0 0;">
        Track everything in the '{user['sheet_tab']}' tab of your
        <a href="{sheet_url}" style="color:#888;">Job Tracker Sheet</a>.
    </p>
    </div>
    """

    return subject, body


def send_email(jobs: list, user: dict, sheet_url: str):
    """Fetch live stats and send the daily action email for a user."""
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    # Multi-user: send to the user's own address; fall back to EMAIL_RECEIVER
    # (the primary user) — useful for a friend demo the user wants to receive and show them.
    receiver = user.get("email") or os.getenv("EMAIL_RECEIVER")

    if not all([sender, password, receiver]):
        print("⚠ Email skipped — sender/password missing or no recipient (user 'email' / EMAIL_RECEIVER)")
        return

    ws = get_user_tab(user)
    stats = get_stats(ws)
    stale = get_stale_info(ws)

    subject, body = render_email_body(jobs, user, sheet_url, stats, stale)

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html"))

    # Attach tailored/variant CV PDFs (repo is private, so links don't work).
    attached = set()
    for job in jobs:
        path = job.get("cv_path", "")
        if not path or path in attached or not os.path.exists(path):
            continue
        attached.add(path)
        try:
            with open(path, "rb") as f:
                part = MIMEApplication(f.read(), _subtype="pdf")
            part.add_header(
                "Content-Disposition", "attachment",
                filename=os.path.basename(path),
            )
            msg.attach(part)
        except Exception as e:
            print(f"⚠ Could not attach CV {os.path.basename(path)}: {e}")
    if attached:
        print(f"📎 Attached {len(attached)} tailored CV(s) to the email")

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())
        print(f"📧 Email sent for {user['name']}")
    except Exception as e:
        print(f"⚠ Email failed for {user['name']}: {e}")
