from fastapi import FastAPI, Request, File, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import sqlite3
import os
import io
import hashlib
from datetime import datetime
from dotenv import load_dotenv

import google.generativeai as genai
from PyPDF2 import PdfReader
from docx import Document
import tempfile
import json
import re

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# ---------------- APP ----------------
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ---------------- DATABASE ----------------
conn = sqlite3.connect("roasts.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS roasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_hash TEXT UNIQUE,
    score INTEGER,
    roast_text TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_limits (
    ip TEXT, date TEXT, count INTEGER, PRIMARY KEY (ip, date)
)""")
conn.commit()

# ---------------- ROUTES ----------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    roasts = cursor.execute(
        "SELECT score, roast_text, created_at FROM roasts ORDER BY score DESC LIMIT 50"
    ).fetchall()
    return templates.TemplateResponse("leaderboard.html", {"request": request, "roasts": roasts})


@app.post("/upload")
async def upload_cv(request: Request, file: UploadFile = File(...)):
    ip = request.client.host
    today = datetime.now().strftime("%Y-%m-%d")

    # -------- RATE LIMITING --------
    cursor.execute("SELECT count FROM daily_limits WHERE ip=? AND date=?", (ip, today))
    row = cursor.fetchone()
    if row and row[0] >= 10:
        return HTMLResponse("<h1 style='color:red;text-align:center;'>Daily Limit Reached</h1>")

    # -------- READ FILE --------
    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    # If file already roasted
    if cursor.execute("SELECT 1 FROM roasts WHERE file_hash=?", (file_hash,)).fetchone():
        roast = cursor.execute(
            "SELECT score, roast_text FROM roasts WHERE file_hash=?", (file_hash,)
        ).fetchone()
        return templates.TemplateResponse(
            "result.html",
            {"request": request, "score": roast[0], "one_line": "", "overview": "",
             "detailed": roast[1], "strengths": "", "improvements": "", "fun_obs": ""}
        )

    # -------- EXTRACT TEXT --------
    text = ""
    filename = file.filename.lower()

    try:
        if filename.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(content))
            for page in reader.pages:
                text += (page.extract_text() or "") + "\n"

        elif filename.endswith(".docx"):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            doc = Document(tmp_path)
            text = "\n".join([p.text for p in doc.paragraphs])
            os.unlink(tmp_path)

        elif filename.endswith(".txt"):
            text = content.decode("utf-8")

        else:
            return HTMLResponse("<h1>Invalid File Type</h1>")

    except Exception:
        return HTMLResponse("<h1>Error Reading File</h1>")

    # -------- GEMINI PROMPT --------
    REAL_DATE = "November 22, 2025"

    prompt = f"""
You are ROASTRANK — a 70% brutal CV roaster and 30% supportive career coach.

IMPORTANT DATE RULES:
- Today's REAL date is: {REAL_DATE}
- If the resume says “Feb 2025 – Present”, it is **valid**, not a future date.
- DO NOT accuse the user of time travel.
- DO NOT penalize or roast date inconsistencies.
- ASSUME ALL DATES ARE CORRECT AND REAL.

STRUCTURE REQUIRED (JSON ONLY):
{{
  "score": int,
  "one_line": str,
  "overview": str,
  "detailed": str,
  "strengths": str,
  "improvements": str,
  "fun_observation": str
}}

GUIDELINES:
- 70%: savage, clever, funny roast  
- 30%: praise + genuine career improvement  
- Score must reflect content quality  
- Do NOT give extremely low scores unless resume is genuinely weak  
- If resume is strong, score should be 70–95

NOW ANALYZE THIS RESUME:

{text[:15000]}
"""

    # -------- CALL GEMINI --------
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)

        raw = response.text.strip()
        
        # Extract JSON from any noise
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw_json = match.group(0)
        else:
            raise ValueError("No JSON returned by Gemini.")

        data = json.loads(raw_json)

    except Exception as e:
        print("ERROR:", str(e))
        data = {
            "score": 50,
            "one_line": "API error — default roast triggered.",
            "overview": "",
            "detailed": "Gemini failed, but your CV deserves a roast anyway.",
            "strengths": "",
            "improvements": "",
            "fun_observation": "Even the AI choked on your CV, legendary."
        }

    score = data.get("score", 50)

    # -------- SCORE CORRECTION --------
    sentiment = (
        data.get("overview", "") + " " +
        data.get("detailed", "") + " " +
        data.get("strengths", "")
    ).lower()

    positive_words = ["excellent", "strong", "impressive", "advanced",
                      "impact", "senior", "powerful", "robust", "top-tier"]

    if score < 40 and any(w in sentiment for w in positive_words):
        score = 70  # auto-fix stupidity

    # -------- SAVE --------
    roast_text = (
        f"ONE-LINE ROAST:\n{data.get('one_line')}\n\n"
        f"OVERVIEW SUMMARY:\n{data.get('overview')}\n\n"
        f"DETAILED ROAST:\n{data.get('detailed')}\n\n"
        f"STRENGTHS:\n{data.get('strengths')}\n\n"
        f"IMPROVEMENTS:\n{data.get('improvements')}\n\n"
        f"FUN OBSERVATION:\n{data.get('fun_observation')}"
    )

    cursor.execute(
        "INSERT INTO roasts (file_hash, score, roast_text) VALUES (?, ?, ?)",
        (file_hash, score, roast_text)
    )
    cursor.execute(
        "INSERT OR REPLACE INTO daily_limits (ip, date, count) VALUES (?, ?, COALESCE((SELECT count FROM daily_limits WHERE ip=? AND date=?), 0)+1)",
        (ip, today, ip, today)
    )
    conn.commit()

    # -------- RENDER --------
    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "score": score,
            "one_line": data.get("one_line", ""),
            "overview": data.get("overview", ""),
            "detailed": data.get("detailed", ""),
            "strengths": data.get("strengths", ""),
            "improvements": data.get("improvements", ""),
            "fun_obs": data.get("fun_observation", "")
        }
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860, debug=False)