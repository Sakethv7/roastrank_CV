from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import sqlite3
import os
import io
import hashlib
from datetime import datetime
from dotenv import load_dotenv

from openai import OpenAI
from PyPDF2 import PdfReader
from docx import Document
import tempfile
import json
import re

# ------------------ RESET DB ON DEPLOY (HF fix) ------------------
if os.path.exists("roasts.db"):
    print("🧹 Removing old roasts.db to reset schema...")
    os.remove("roasts.db")

# ------------------ INIT ------------------
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=api_key) if api_key else None

if api_key:
    print("✅ OpenAI API key loaded")
else:
    print("❌ No OpenAI API key found!")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ------------------ DATABASE ------------------
conn = sqlite3.connect("roasts.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS roasts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_hash TEXT UNIQUE,
  score INTEGER,
  one_line TEXT,
  overview TEXT,
  detailed TEXT,
  strengths TEXT,
  improvements TEXT,
  fun_obs TEXT,
  name TEXT DEFAULT 'Anonymous',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_limits (
  ip TEXT,
  date TEXT,
  count INTEGER,
  PRIMARY KEY (ip, date)
)
""")

conn.commit()


# ------------------ JSON EXTRACTION ------------------
def extract_json(raw: str):
    """
    Extract JSON from OpenAI output.
    Fixes trailing commas & invalid JSON before parsing.
    """

    raw = raw.replace("```json", "").replace("```", "")

    # Find largest {...} block
    matches = re.findall(r"\{[\s\S]*?\}", raw)
    if not matches:
        raise ValueError("No JSON found.")

    block = max(matches, key=len)

    block = re.sub(r",\s*}", "}", block)
    block = re.sub(r",\s*\]", "]", block)

    return json.loads(block)


# ------------------ NAME EXTRACTION ------------------
def extract_name_from_text(text):
    """Extracts name using small model; returns Anonymous if unclear."""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"""
Extract ONLY the candidate's full name from the resume.
If unsure, return "Anonymous". No extra text.

Resume:
{text[:3000]}
"""
            }]
        )
        name = resp.choices[0].message.content.strip()
        if len(name.split()) > 6:
            return "Anonymous"
        return name
    except:
        return "Anonymous"


# ------------------ ROUTES ------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    roasts = cursor.execute("""
        SELECT score, one_line || '\n\n' || detailed, created_at, name
        FROM roasts ORDER BY score DESC LIMIT 50
    """).fetchall()

    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "roasts": roasts
    })


@app.post("/upload")
async def upload_cv(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("full")
):

    ip = request.client.host
    today = datetime.now().strftime("%Y-%m-%d")

    # ---- RATE LIMIT ----
    cursor.execute("SELECT count FROM daily_limits WHERE ip=? AND date=?", (ip, today))
    row = cursor.fetchone()
    if row and row[0] >= 10:
        return HTMLResponse("<h1 style='color:red;text-align:center;'>Daily Limit Reached</h1>")

    # ---- FILE CONTENT ----
    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    # ---- CHECK CACHE ----
    existing = cursor.execute("""
        SELECT score, one_line, overview, detailed, strengths, improvements, fun_obs, name
        FROM roasts WHERE file_hash=?
    """, (file_hash,)).fetchone()

    if existing:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "score": existing[0],
            "one_line": existing[1],
            "overview": existing[2],
            "detailed": existing[3],
            "strengths": existing[4],
            "improvements": existing[5],
            "fun_obs": existing[6],
            "name": existing[7]
        })

    # ---- EXTRACT TEXT ----
    text = ""
    fn = file.filename.lower()

    try:
        if fn.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(content))
            for p in reader.pages:
                text += (p.extract_text() or "") + "\n"

        elif fn.endswith(".docx"):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(content)
                temp_path = tmp.name

            doc = Document(temp_path)
            text = "\n".join(p.text for p in doc.paragraphs)
            os.unlink(temp_path)

        elif fn.endswith(".txt"):
            text = content.decode()

    except:
        return HTMLResponse("<h1>File could not be read</h1>")

    text = text[:15000]

    # ---- NAME ----
    name = extract_name_from_text(text)

    # -------------------- PROMPT --------------------
    if mode == "quick":
        prompt = f"""
Return ONLY JSON:
{{
 "score": number,
 "one_line": string
}}

Roast must be max 4 lines.  
Never leave fields empty.

Resume:
{text}
"""
    else:
        prompt = f"""
You are ROASTRANK, a JSON-only CV roasting engine.

Return ONLY valid JSON — all fields must be NON-EMPTY:
{{
 "score": number,
 "one_line": string,
 "overview": string,
 "detailed": string,
 "strengths": string,
 "improvements": string,
 "fun_observation": string
}}

Rules:
- Every field must contain 3–6 lines
- Be funny, compact, punchy
- No markdown, no explanations
- If information missing → improvise creatively

Resume:
{text}
"""

    # -------------------- CALL OPENAI --------------------
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        raw = resp.choices[0].message.content
        data = extract_json(raw)

    except Exception as e:
        print("ERROR:", e)

        if mode == "quick":
            data = {
                "score": 60,
                "one_line": "Your CV confused the AI."
            }
        else:
            data = {
                "score": 65,
                "one_line": "Your CV confused the AI.",
                "overview": "The model panicked mid-roast.",
                "detailed": "Your resume made OpenAI question its life decisions.",
                "strengths": "You tried, and that's something.",
                "improvements": "Try re-uploading when the AI is emotionally stable.",
                "fun_observation": "Your CV broke a trillion-dollar machine."
            }

    # ---- Fallback for missing fields ----
    def fix(field, default):
        return data.get(field, "").strip() or default

    score = data.get("score", 70)

    one_line = fix("one_line", "Your CV stunned the AI into silence.")
    overview = fix("overview", "Your resume left the model unsure what to say.")
    detailed = fix("detailed", "The AI attempted a roast but blacked out midway.")
    strengths = fix("strengths", "You're resilient enough to upload this CV.")
    improvements = fix("improvements", "Try formatting, clarity, and fewer buzzwords.")
    fun_obs = fix("fun_observation", "Even AI needed therapy after reading your CV.")

    # ---------------- SAVE ----------------
    cursor.execute("""
        INSERT INTO roasts (
            file_hash, score, one_line, overview, detailed,
            strengths, improvements, fun_obs, name
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        file_hash,
        score,
        one_line,
        overview,
        detailed,
        strengths,
        improvements,
        fun_obs,
        name
    ))

    cursor.execute("""
        INSERT OR REPLACE INTO daily_limits (ip, date, count)
        VALUES (?, ?, COALESCE((SELECT count FROM daily_limits WHERE ip=? AND date=?), 0)+1)
    """, (ip, today, ip, today))

    conn.commit()

    # ---------------- RENDER ----------------
    return templates.TemplateResponse("result.html", {
        "request": request,
        "score": score,
        "one_line": one_line,
        "overview": overview,
        "detailed": detailed,
        "strengths": strengths,
        "improvements": improvements,
        "fun_obs": fun_obs,
        "name": name
    })
