# cv_tailor.py

import os
import json
import re
from anthropic import Anthropic
from dotenv import load_dotenv
import cost_tracker
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.colors import black, HexColor

load_dotenv()
client = Anthropic()

# --- Base CV Content ---
# SAMPLE base CV — replace every value with your own. No real personal data is
# committed to this repo; the agent tailors role-specific CVs from this template.
BASE_CV = {
    "name": "YOUR_NAME",
    "contact": "Phone: YOUR_PHONE | Email: YOUR_EMAIL | LinkedIn: YOUR_LINKEDIN | City: YOUR_CITY",
    "summary": "SAMPLE — replace with your own. <Role> with N+ years of experience in <domains>, focused on <core strengths and the kind of impact you deliver>.",
    "experience": [
        {
            "company": "MOST_RECENT_COMPANY",
            "title": "YOUR_TITLE",
            "dates": "YYYY - Present",
            "bullets": [
                "YOUR_ACHIEVEMENT_1 — quantify the impact, e.g. 'cut X by Y% via Z'.",
                "YOUR_ACHIEVEMENT_2.",
                "YOUR_ACHIEVEMENT_3."
            ]
        },
        {
            "company": "PREVIOUS_COMPANY",
            "title": "YOUR_TITLE",
            "dates": "YYYY - YYYY",
            "bullets": [
                "YOUR_ACHIEVEMENT_1.",
                "YOUR_ACHIEVEMENT_2."
            ]
        }
    ],
    "education": {
        "school": "YOUR_UNIVERSITY",
        "dates": "YYYY-YYYY",
        "degree": "YOUR_DEGREE"
    },
    "skills": [
        "Category 1: skill, skill, skill",
        "Category 2: skill, skill, skill",
        "Category 3: skill, skill, skill"
    ]
}


# --- CV variants by role track -------------------------------------------
# Same experience/education as the master CV, but the summary + skills are
# reframed for the role type. Deterministic (no LLM) -> consistent, free,
# and length-controlled. Used when a job is a different *kind* of role.

CV_VARIANTS = {
    "strategy": {
        "summary": (
            "SAMPLE — replace with your own. Strategy & operations professional "
            "driving data-backed planning, financial modeling, and business-operations "
            "improvements. Builds automated models, real-time analytics, and process "
            "redesigns that cut costs and sharpen decision-making, combining product "
            "rigor with hands-on AI/automation."
        ),
        "skills": [
            "Strategy & Planning: Financial Modeling, Cost Modeling, OKRs, Business Casing, Buy vs Build Eval.",
            "Business Operations: Process Redesign, Workflow Automation, Operational KPIs, Cross-functional Delivery",
            "Analytics & Data: SQL, Excel, Real-Time Dashboards, Google Analytics, Funnel & Drop-off Analysis",
            "AI & Automation: RAG Architecture, AI Agent Development, LLM Integration, Prompt Engineering",
            "Tools & Systems: Python, Figma, API Integrations, ERP/CRM (SAP, Dynamics 365)",
        ],
    },
    "consulting": {
        "summary": (
            "SAMPLE — replace with your own. Analytical problem-solver structuring "
            "ambiguous business problems and delivering quantified impact across finance, "
            "operations, and product. Track record of cost models, process redesigns, and "
            "automation, with strong stakeholder management and data-driven recommendations."
        ),
        "skills": [
            "Problem Solving: Issue Structuring, Hypothesis-Driven Analysis, Business Casing, Buy vs Build Eval.",
            "Quantitative Analysis: Financial Modeling, Cost Modeling, SQL, Excel, Forecasting",
            "Stakeholder Management: Cross-functional Delivery, Compliance Alignment, Executive Reporting",
            "Operations & Process: Workflow Automation, Process Efficiency, KPI Design",
            "Technical: Python, AI Agents, RAG Systems, API Integrations, Dashboards",
        ],
    },
}


def resolve_profile(user: dict = None):
    """Resolve (base_cv, variants, candidate_name) for a user.

    Multi-user support: a friend's profile carries its own `cv` dict (same shape
    as BASE_CV) and optional `cv_variants`. When absent we fall back to the user's
    BASE_CV / CV_VARIANTS, so the single-user path is unchanged.
    """
    if not user:
        return BASE_CV, CV_VARIANTS, BASE_CV["name"]
    base = user.get("cv") or BASE_CV
    # Only inherit the user's strategy/consulting variants when using the user's CV.
    variants = user.get("cv_variants") or (CV_VARIANTS if base is BASE_CV else {})
    name = user.get("name") or base.get("name") or "Candidate"
    return base, variants, name


def classify_role(job: dict) -> str:
    """Heuristic role-track classifier from the job title. No LLM (free).

    Returns 'consulting', 'strategy', or 'product' (the default).
    """
    title = (job.get("title", "") or "").lower()

    if any(k in title for k in ["consult", "advisory", "advisor"]):
        return "consulting"
    if any(k in title for k in [
        "strateg", "chief of staff", "business operation", "biz ops",
        "bizops", "operations manager", "corporate development", "bizops",
    ]):
        return "strategy"
    return "product"


def build_variant_cv(track: str, base_cv: dict = None, variants: dict = None) -> dict:
    """Return a CV dict for a role track, reusing master experience/education."""
    base_cv = base_cv or BASE_CV
    variants = variants if variants is not None else CV_VARIANTS
    variant = dict(base_cv)
    overrides = variants.get(track)
    if overrides:
        variant["summary"] = overrides["summary"]
        variant["skills"] = overrides["skills"]
    return variant


def tailor_cv(job: dict, base_cv: dict = None) -> dict:
    """Use Claude to decide which bullets/skills to adjust for a specific job."""

    base_cv = base_cv or BASE_CV
    cv_json = json.dumps(base_cv, indent=2)

    prompt = f"""You are a CV tailoring assistant. You will receive a base CV and a job description.

Your job is to make MINIMAL, TARGETED changes to the CV to better align with the job. Follow these strict rules:

1. KEEP the exact same structure, sections, and formatting
2. KEEP all company names, titles, and dates UNCHANGED
3. DO NOT invent new experience or achievements — only rephrase existing ones
4. You may:
   - Rephrase 2-4 bullet points to emphasize skills mentioned in the job description
   - Swap 2-3 skills in the skills section to match the job requirements
   - Slightly adjust the professional summary (1-2 phrases max) to align with the role
5. REMOVE bullets that are clearly irrelevant to this specific role (e.g. if applying for a fintech role, the school dismissal app bullet can be removed)
6. The CV MUST stay on one page — if you add anything, remove something of equal length
7. DO NOT add a cover letter unless I explicitly ask

BASE CV:
{cv_json}

JOB:
Title: {job.get('title', 'N/A')}
Company: {job.get('company', 'N/A')}
Location: {job.get('location', 'N/A')}
Description: {job.get('description', 'N/A')}

Return the modified CV as a JSON object with the EXACT same structure as the input. Only change the values that need adjusting. Return ONLY valid JSON, no explanation."""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    cost_tracker.record("tailor")

    response = message.content[0].text.strip()

    # Clean up markdown fences if present
    response = re.sub(r'^```json\s*', '', response)
    response = re.sub(r'\s*```$', '', response)

    try:
        return json.loads(response)
    except json.JSONDecodeError:
        print("⚠ Failed to parse tailored CV JSON, using base CV")
        return base_cv


def generate_cover_letter(job: dict, base_cv: dict = None) -> str:
    """Generate a cover letter only if the job explicitly requires one."""

    base_cv = base_cv or BASE_CV

    description = job.get("description", "").lower()
    needs_cover = any(phrase in description for phrase in [
        "cover letter required", "cover letter", "letter of motivation",
        "motivational letter", "submit a cover letter", "include a cover letter"
    ])

    if not needs_cover:
        return None

    # Candidate block derived from whichever CV we're using (multi-user safe).
    latest = (base_cv.get("experience") or [{}])[0]
    candidate_block = (
        f"Name: {base_cv.get('name', 'Candidate')}\n"
        f"Current Role: {latest.get('title', '')} at {latest.get('company', '')}\n"
        f"Summary: {base_cv.get('summary', '')}\n"
        f"Education: {base_cv.get('education', {}).get('degree', '')}"
    )

    prompt = f"""Write a concise, professional cover letter for this job application.

CANDIDATE:
{candidate_block}

JOB:
Title: {job.get('title', 'N/A')}
Company: {job.get('company', 'N/A')}
Location: {job.get('location', 'N/A')}
Description: {job.get('description', 'N/A')}

Rules:
- Maximum 250 words
- Professional but not generic
- Reference 2-3 specific achievements from the candidate's background that match the job
- Do not be overly flattering or use cliches
- End with a clear call to action"""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    cost_tracker.record("cover")

    return message.content[0].text.strip()


def _bold_numbers(text: str) -> str:
    """Make numbers, percentages, and dollar amounts bold in text."""
    import re
    # Bold patterns: $15K, 1,500+, 70%, 10-minute, FY'23, 3PL
    text = re.sub(
        r'(\$[\d,]+[KMB]?|\d[\d,]*\.?\d*\+?%?(?:-\w+)?)',
        r'<b>\1</b>',
        text
    )
    return text


def build_pdf(cv_data: dict, output_path: str):
    """Generate a clean one-page PDF matching the original CV format exactly."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
    from reportlab.lib.colors import black, HexColor

    TEAL = HexColor('#2E75B6')

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        topMargin=0.4 * inch,
        bottomMargin=0.25 * inch,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
    )

    content_width = letter[0] - 1.2 * inch

    # --- Styles ---
    name_style = ParagraphStyle(
        'Name', fontName='Times-Bold', fontSize=18,
        alignment=TA_CENTER, spaceAfter=6, textColor=TEAL
    )
    contact_style = ParagraphStyle(
        'Contact', fontName='Times-Roman', fontSize=8.5,
        alignment=TA_CENTER, spaceAfter=6
    )
    section_header_style = ParagraphStyle(
        'SectionHeader', fontName='Times-Bold', fontSize=11,
        spaceBefore=6, spaceAfter=1, textColor=TEAL
    )
    summary_style = ParagraphStyle(
        'Summary', fontName='Times-Roman', fontSize=9,
        spaceAfter=2, leading=11, leftIndent=6
    )
    bullet_style = ParagraphStyle(
        'Bullet', fontName='Times-Roman', fontSize=9,
        leftIndent=14, spaceAfter=1, leading=11,
        bulletIndent=2
    )
    skill_style = ParagraphStyle(
        'Skill', fontName='Times-Roman', fontSize=9,
        leftIndent=14, spaceAfter=1, leading=11,
        bulletIndent=2
    )
    job_left_style = ParagraphStyle(
        'JobLeft', fontName='Times-Bold', fontSize=9,
        spaceAfter=0
    )
    job_right_style = ParagraphStyle(
        'JobRight', fontName='Times-Roman', fontSize=9,
        alignment=TA_RIGHT, spaceAfter=0
    )
    edu_left_style = ParagraphStyle(
        'EduLeft', fontName='Times-Bold', fontSize=9.5,
        spaceAfter=0
    )
    edu_right_style = ParagraphStyle(
        'EduRight', fontName='Times-Roman', fontSize=9.5,
        alignment=TA_RIGHT, spaceAfter=0
    )
    edu_detail_style = ParagraphStyle(
        'EduDetail', fontName='Times-Roman', fontSize=9,
        spaceAfter=1
    )

    story = []

    # --- Name ---
    story.append(Paragraph(cv_data["name"], name_style))

    # --- Contact (with bold labels) ---
    contact = cv_data["contact"]
    # Make labels bold: Phone:, Email:, LinkedIn:, City:
    contact_formatted = contact.replace("Phone:", "<b>Phone:</b>")
    contact_formatted = contact_formatted.replace("Email:", "<b>Email:</b>")
    contact_formatted = contact_formatted.replace("LinkedIn:", "<b>LinkedIn:</b>")
    contact_formatted = contact_formatted.replace("City:", "<b>City:</b>")
    story.append(Paragraph(contact_formatted, contact_style))

    # --- Professional Summary ---
    story.append(Paragraph("<b>PROFESSIONAL SUMMARY</b>", section_header_style))
    story.append(HRFlowable(width="100%", thickness=0.75, color=TEAL, spaceAfter=3))
    story.append(Paragraph(cv_data["summary"], summary_style))

    # --- Work Experience ---
    story.append(Paragraph("<b>WORK EXPERIENCE</b>", section_header_style))
    story.append(HRFlowable(width="100%", thickness=0.75, color=TEAL, spaceAfter=2))

    for exp in cv_data["experience"]:
        # Company bold + Title italic on left, Date on right — using a table
        company = exp['company'].upper()
        title_text = exp['title']
        dates = exp['dates']

        left_para = Paragraph(
            f"<b>{company}</b> – <i>{title_text}</i>",
            job_left_style
        )
        right_para = Paragraph(dates, job_right_style)

        header_table = Table(
            [[left_para, right_para]],
            colWidths=[content_width * 0.78, content_width * 0.22]
        )
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ]))
        story.append(header_table)

        for bullet in exp["bullets"]:
            bolded = _bold_numbers(bullet)
            story.append(Paragraph(f"▪ {bolded}", bullet_style))

    # --- Education ---
    story.append(Paragraph("<b>EDUCATION</b>", section_header_style))
    story.append(HRFlowable(width="100%", thickness=0.75, color=TEAL, spaceAfter=3))

    edu = cv_data["education"]
    edu_left = Paragraph(f"<b>{edu['school']}</b>", edu_left_style)
    edu_right = Paragraph(edu['dates'], edu_right_style)

    edu_table = Table(
        [[edu_left, edu_right]],
        colWidths=[content_width * 0.82, content_width * 0.18]
    )
    edu_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))
    story.append(edu_table)

    # Degree line (optionally bold a GPA by wrapping it in <b>…</b> in your profile)
    degree_text = edu['degree']
    story.append(Paragraph(degree_text, edu_detail_style))

    # --- Skills ---
    story.append(Paragraph("<b>SKILLS</b>", section_header_style))
    story.append(HRFlowable(width="100%", thickness=0.75, color=TEAL, spaceAfter=3))

    for skill in cv_data["skills"]:
        # Bold the category before the colon
        if ":" in skill:
            parts = skill.split(":", 1)
            formatted = f"<b>{parts[0]}:</b>{parts[1]}"
        else:
            formatted = skill
        story.append(Paragraph(f"▪ {formatted}", skill_style))

    doc.build(story)


def _count_pdf_pages(path: str) -> int:
    """Return the page count of a PDF (used to enforce the one-page rule)."""
    try:
        from pypdf import PdfReader
        return len(PdfReader(path).pages)
    except Exception:
        return 1  # if we can't read it, assume fine rather than loop forever


def build_pdf_one_page(cv_data: dict, output_path: str) -> int:
    """Build the PDF and guarantee one page by trimming the longest section.

    This fixes the long-standing overflow bug: instead of trusting the LLM to
    keep it short, we measure the rendered PDF and drop the lowest-priority
    bullets (from the experience with the most bullets) until it fits.
    """
    import copy
    data = copy.deepcopy(cv_data)

    build_pdf(data, output_path)
    pages = _count_pdf_pages(output_path)

    # Safety bound: at most as many trims as there are bullets, so the loop
    # always terminates even in pathological cases.
    exps = data.get("experience", [])
    max_trims = sum(len(e.get("bullets", [])) for e in exps)

    for _ in range(max_trims):
        if pages <= 1:
            break
        # Drop the last bullet from the experience that currently has the most.
        idx = max(
            range(len(exps)),
            key=lambda i: len(exps[i].get("bullets", [])),
            default=-1,
        )
        if idx < 0 or len(exps[idx].get("bullets", [])) <= 1:
            break  # keep at least one bullet per role
        exps[idx]["bullets"].pop()
        build_pdf(data, output_path)
        pages = _count_pdf_pages(output_path)

    if pages > 1:
        print(f"[warn] CV still {pages} pages after trimming - check {output_path}")
    return pages


def _master_cv_result(role: str) -> dict:
    """The 'use your master CV' outcome — no PDF, no LLM spend."""
    return {
        "cv_path": None,
        "cv_label": "Master CV",
        "role_track": role,
        "llm_used": False,
        "pages": 0,
        "cover_letter_path": None,
        "cover_letter_text": None,
    }


def tailor_and_generate(job: dict, score: int = 10,
                        output_dir: str = "tailored_cvs",
                        allow_llm_tailor: bool = True,
                        user: dict = None) -> dict:
    """Generate the right CV for a job and guarantee it fits one page.

    Tailoring gate (cost-tuned 2026-06-04):
      - Strategy/consulting role WITH a CV variant -> that variant (no LLM).
      - Product role, strong fit (score >= 8)       -> master CV, no file.
      - Product role, score == 7 (almost-strong)    -> LLM-tailored CV.
      - Product role, score <= 6 (weak match)       -> master CV, no file.
    Only the score-7 band spends Claude tokens. `allow_llm_tailor` lets the
    orchestrator enforce a per-run cap. `user` selects whose CV to use (multi-
    user): falls back to the user's BASE_CV when None.
    """
    os.makedirs(output_dir, exist_ok=True)

    base_cv, variants, candidate_name = resolve_profile(user)
    name_slug = re.sub(r'[^\w\s-]', '', candidate_name).strip().replace(' ', '_') or "Candidate"

    company = re.sub(r'[^\w\s-]', '', job.get('company', 'Unknown')).strip().replace(' ', '_')
    title = re.sub(r'[^\w\s-]', '', job.get('title', 'PM')).strip().replace(' ', '_')
    filename = f"CV_{name_slug}_{company}_{title}"

    role = classify_role(job)
    has_variant = role in ("strategy", "consulting") and role in variants

    # Without a matching variant, treat the role under the product gate: only the
    # score-7 band is worth an LLM-tailored CV; 8+/<=6 use the master CV.
    if not has_variant:
        if not (score == 7 and allow_llm_tailor):
            reason = (
                "strong fit" if score >= 8
                else ("cap reached" if score == 7 else "weak match")
            )
            print(f"✅ {role.capitalize()} role ({score}/10, {reason}) — use Master CV (no file)")
            return _master_cv_result(role)
        print(f"✏️ Borderline fit ({score}/10) — tailoring CV for {job.get('title')}...")
        cv_data = tailor_cv(job, base_cv)
        label = "Tailored CV"
        llm_used = True
    else:
        cv_data = build_variant_cv(role, base_cv, variants)
        label = f"{role.capitalize()} CV"
        llm_used = False
        print(f"🧭 {role.capitalize()} role — generating {label} variant (no LLM)")

    pdf_path = os.path.join(output_dir, f"{filename}.pdf")
    pages = build_pdf_one_page(cv_data, pdf_path)
    print(f"📄 CV saved: {pdf_path} ({pages} page{'s' if pages != 1 else ''}) — {label}")

    # Cover letter (only if the JD explicitly asks for one)
    cover_letter = generate_cover_letter(job, base_cv)
    cl_path = None
    if cover_letter:
        cl_path = os.path.join(output_dir, f"CL_{filename}.txt")
        with open(cl_path, "w") as f:
            f.write(cover_letter)
        print(f"📝 Cover letter saved: {cl_path}")
    else:
        print(f"📝 No cover letter needed")

    return {
        "cv_path": pdf_path,
        "cv_label": label,
        "role_track": role,
        "llm_used": llm_used,
        "pages": pages,
        "cover_letter_path": cl_path,
        "cover_letter_text": cover_letter,
    }
