# intake_cv.py
#
# Simple CV intake: turn a CV file (PDF/TXT) into a ready-to-run user profile.
# Claude reads the CV and structures it into (a) the `cv` dict the tailoring
# engine needs (same shape as cv_tailor.BASE_CV) and (b) the matcher profile
# fields (target_roles, years_experience, etc.). Writes users/<slug>.json.
#
# Usage:
#   python intake_cv.py "C:/path/to/CV.pdf" --name "Ashar Ismail" \
#       --email YOUR_EMAIL [--demo] [--paid]
#
#   --demo  -> active, limits {max_results:4}, free sources only (cheap demo)
#   --paid  -> include the paid LinkedIn source (otherwise free sources only)
#
# After review, set "active": true and adjust limits when the person is paying.

import os
import re
import sys
import json
import argparse
from anthropic import Anthropic
from dotenv import load_dotenv
import cost_tracker

load_dotenv()
client = Anthropic()


def extract_text(path: str) -> str:
    """Pull plain text from a CV file (PDF or TXT)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(path)
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if ext in (".txt", ".md"):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    raise ValueError(f"Unsupported CV type '{ext}'. Use PDF or TXT "
                     "(export DOCX to PDF first).")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "user"


def parse_cv(cv_text: str, name: str, email: str) -> dict:
    """Ask Claude to structure the CV into a full profile (cv + matcher fields)."""
    prompt = f"""Convert this CV into a JSON profile. Use ONLY information present
in the CV — do not invent experience, metrics, or skills.

Return ONLY valid JSON (no prose, no code fences) with EXACTLY these keys:

{{
  "current_title": "their most recent job title",
  "years_experience": <number, estimate from work history>,
  "target_roles": ["5-8 realistic target roles given their background and seniority"],
  "target_industries": ["3-5 industries from their experience"],
  "core_skills": ["8-12 concrete skills from the CV"],
  "domain_expertise": ["3-6 domains they know"],
  "notable_achievements": ["3-5 quantified achievements, quoted/condensed from the CV"],
  "education": "one-line: degree, field, institution",
  "search_keywords": ["1-2 short job-search keywords matching their target roles"],
  "cv": {{
    "name": "{name}",
    "contact": "Phone: ... | Email: {email} | LinkedIn: ... | City: ...  (fill from CV)",
    "summary": "2-3 sentence professional summary written from the CV",
    "experience": [
      {{"company": "COMPANY", "title": "Title", "dates": "Mon YYYY - Mon YYYY",
        "bullets": ["achievement bullet", "..."]}}
    ],
    "education": {{"school": "School", "dates": "YYYY-YYYY", "degree": "Degree | Field | CGPA: x/y"}},
    "skills": ["Category: skill, skill, skill", "..."]
  }}
}}

Keep every experience entry and its bullets (condense lightly if very long).
CV TEXT:
{cv_text}
"""
    msg = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    cost_tracker.record("tailor")  # similar token profile; counts toward cost line
    raw = msg.content[0].text.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def build_profile(parsed: dict, name: str, email: str, demo: bool, paid: bool) -> dict:
    """Assemble the final users/<slug>.json structure."""
    profile = {
        "name": name,
        "sheet_tab": name,
        "email": email,
        "active": bool(demo),  # demo profiles are active; otherwise off until paid
        "use_paid_sources": bool(paid),
        "search_keywords": parsed.get("search_keywords") or ["Product Manager"],
        "target_roles": parsed["target_roles"],
        "freelance_ok": "no",
        "target_industries": parsed["target_industries"],
        "core_skills": parsed["core_skills"],
        "domain_expertise": parsed["domain_expertise"],
        "notable_achievements": parsed["notable_achievements"],
        "education": parsed["education"],
        "years_experience": parsed["years_experience"],
        "current_title": parsed["current_title"],
        "preferred_work_type": ["Remote", "Hybrid", "On-site"],
        "relocation": "Open to relocation with visa sponsorship to Europe and the Gulf",
        "languages": ["English"],
        "cv": parsed["cv"],
        "cv_variants": {},
    }
    if demo:
        profile["limits"] = {"max_scored": 25, "max_results": 4}
    return profile


def main():
    ap = argparse.ArgumentParser(description="Parse a CV into a user profile.")
    ap.add_argument("cv_path", help="Path to the CV (PDF or TXT)")
    ap.add_argument("--name", required=True, help="Person's full name")
    ap.add_argument("--email", required=True, help="Person's email")
    ap.add_argument("--demo", action="store_true",
                    help="Active demo profile, capped to 4 results")
    ap.add_argument("--paid", action="store_true",
                    help="Include the paid LinkedIn source (default: free only)")
    args = ap.parse_args()

    print(f"📄 Reading CV: {args.cv_path}")
    text = extract_text(args.cv_path)
    print(f"   extracted {len(text)} chars; parsing with Claude...")

    parsed = parse_cv(text, args.name, args.email)
    profile = build_profile(parsed, args.name, args.email, args.demo, args.paid)

    os.makedirs("users", exist_ok=True)
    out = os.path.join("users", f"{slugify(args.name)}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)

    print(f"✅ Wrote {out}")
    print(f"   name={profile['name']} | email={profile['email']} | "
          f"active={profile['active']} | paid={profile['use_paid_sources']} | "
          f"limits={profile.get('limits')}")
    print(f"   target_roles: {', '.join(profile['target_roles'])}")
    print("   Review the file, then run:  python run_all.py \""
          f"{profile['name']}\"")


if __name__ == "__main__":
    main()
