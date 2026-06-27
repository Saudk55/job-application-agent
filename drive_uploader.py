# drive_uploader.py
# Stores CVs as base64 in a local folder and returns the local path
# CVs are committed to the GitHub repo and accessible via raw GitHub links

import os

def upload_cv(pdf_path: str, filename: str) -> str:
    """Return the GitHub raw link for the CV file."""
    repo = "YOUR_GITHUB_USER/YOUR_REPO"
    branch = "main"
    
    # The file is already saved locally in tailored_cvs/
    # It will be committed to GitHub by the workflow
    relative_path = f"tailored_cvs/{filename}"
    
    link = f"https://github.com/{repo}/raw/{branch}/{relative_path}"
    print(f"📄 CV link: {filename}")
    return link