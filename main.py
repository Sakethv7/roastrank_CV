import os
import sqlite3
import json
from datetime import datetime
from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from openai import OpenAI
import PyPDF2
from docx import Document


# ------------------------------------------------------------
# FASTAPI SETUP
# ------------------------------------------------------------
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

client = OpenAI()


# ------------------------------------------------------------
# DATABASE SETUP
# ------------------------------------------------------------
DB_PATH = "roasts.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS roasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    score INTEGER,
    one_line TEXT,
    overview TEXT,
    detailed TEXT,
    fun_obs TEXT,
    created_at TEXT
)
""")
conn.commit()


# ------------------------------------------------------------
# EXTRACT TEXT
# ------------------------------------------------------------
def extract_text_from_file(file: UploadFile) -> str:
    ext = file.filename.lower()

    if ext.endswith(".pdf"):
        reader = PyPDF2.PdfReader(file.file)
        text = ""
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
        return text

    elif ext.endswith(".docx"):
        doc = Document(file.file)
        return "\n".join(p.text for p in doc.paragraphs)

    else:
        return file.file.read().decode("utf-8", errors="ignore")


# ------------------------------------------------------------
# NAME GUESSER
# ------------------------------------------------------------
def guess_name(text: str) -> str:
    lines = text.split("\n")
    for line in lines[:5]:
        cleaned = line.strip()
        if 2 <= len(cleaned.split()) <= 4 and cleaned.replace(" ", "").isalpha():
            return cleaned
    return "Anonymous"


# ------------------------------------------------------------
# ROASTING ENGINE (Unified for quick/full)
# ------------------------------------------------------------
def roast_resume(text: str, mode: str):
    BASE_PROMPT = f"""
You are RoastRank — a brutally funny resume roasting engine.

RULES:
- Always return **valid JSON only**.
- Keep output compact.
- Humor must be sharp, quick, intelligent (NOT generic compliments).
- Score must be between 1–100.

JSON FORMAT:
{{
  "one_line": "",
  "overview": "",
  "detailed": "",
  "fun_obs": "",
  "score": 0
}}

GUIDELINES:
- "one_line": A single-line roast, punchy, mean, specific to flaws in the CV.
- "overview": 3–4 lines. Factual + funny commentary on resume style, structure, vibe.
- "detailed": 3–5 lines, a deeper roast about structure, content choices, and tone.
- "fun_obs": 1–2 funny observations about the candidate or resume.
- Consistent scoring across quick/full. Same scoring logic, only length differs.

Resume Text:
{text}
"""

    QUICK_ADDITION = """
For quick roast:
- Shorten everything.
- Still roast properly (no generic lines).
- Max 1–2 lines per section.
"""

    FULL_ADDITION = """
For full roast:
- Use full length (but still compact).
- Stronger insults and more detail.
"""

    full_prompt = BASE_PROMPT + (FULL_ADDITION if mode == "full" else QUICK_ADDITION)

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=full_prompt
    )

    raw = response.output[0].content[0].text

    try:
        return json.loads(raw)
    except:
        return {
            "one_line": "Your CV confused the AI.",
            "overview": "Model failed parsing JSON.",
            "detailed": "",
            "fun_obs": "",
            "score": 1
        }


# ------------------------------------------------------------
# ROUTES
# ------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile, mode: str = Form(...)):

    text = extract_text_from_file(file)
    name = guess_name(text)

    roast = roast_resume(text, mode)

    cursor.execute("""
        INSERT INTO roasts (name, score, one_line, overview, detailed, fun_obs, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        name,
        roast["score"],
        roast["one_line"],
        roast["overview"],
        roast["detailed"],
        roast["fun_obs"],
        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()

    return templates.TemplateResponse("result.html", {
        "request": request,
        "name": name,
        "score": roast["score"],
        "one_line": roast["one_line"],
        "overview": roast["overview"],
        "detailed": roast["detailed"],
        "fun_obs": roast["fun_obs"],
    })


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    cursor.execute("""
        SELECT name, score, one_line, created_at
        FROM roasts
        ORDER BY score DESC, created_at DESC
        LIMIT 50
    """)
    rows = cursor.fetchall()

    return templates.TemplateResponse(
        "leaderboard.html",
        {"request": request, "roasts": rows}
    )


# ------------------------------------------------------------
# LOCAL DEBUG RUN
# ------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
import os
import io
import json
import sqlite3
from datetime import datetime
from fastapi import FastAPI, Request, UploadFile, Form, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from openai import OpenAI
import PyPDF2
from docx import Document

# ------------------------------------------------------------
# INITIALIZE APP
# ------------------------------------------------------------
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

client = OpenAI()

# ------------------------------------------------------------
# DATABASE SETUP
# ------------------------------------------------------------
DB_PATH = "roasts.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS roasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    score INTEGER,
    one_line TEXT,
    overview TEXT,
    detailed TEXT,
    improvements TEXT,
    fun_obs TEXT,
    created_at TEXT
)
""")
conn.commit()

# ------------------------------------------------------------
# TEXT EXTRACTION — NOW BULLETPROOF FOR PDF / DOCX / TXT
# ------------------------------------------------------------
async def extract_text_from_file(file: UploadFile) -> str:
    fname = file.filename.lower()

    # Read bytes first — works for everything
    raw = await file.read()

    # ----- PDF -----
    if fname.endswith(".pdf"):
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(raw))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except:
            return ""

    # ----- DOCX -----
    elif fname.endswith(".docx"):
        try:
            doc = Document(io.BytesIO(raw))
            return "\n".join(p.text for p in doc.paragraphs)
        except:
            return ""

    # ----- DOC (old MS Word) -----
    elif fname.endswith(".doc"):
        # Try to decode something usable
        try:
            return raw.decode(errors="ignore")
        except:
            return ""

    # ----- TXT -----
    else:
        try:
            return raw.decode("utf-8", errors="ignore")
        except:
            return ""


# ------------------------------------------------------------
# NAME DETECTION
# ------------------------------------------------------------
def guess_name(text: str) -> str:
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    if len(lines) == 0:
        return "Anonymous"

    first = lines[0]
    parts = first.split()

    # Basic heuristic — works for most resumes
    if 2 <= len(parts) <= 4 and all(p.replace(".", "").isalpha() for p in parts):
        return first

    return "Anonymous"


# ------------------------------------------------------------
# JSON CLEANER
# ------------------------------------------------------------
def try_parse_json(block: str):
    block = block.replace("```json", "").replace("```", "")
    block = block.replace("\n", " ")

    # Fix trailing commas
    block = block.replace(", }", "}")
    block = block.replace(", ]", "]")

    try:
        return json.loads(block)
    except:
        return None


# ------------------------------------------------------------
# ROASTING ENGINE
# ------------------------------------------------------------
def roast_resume(text: str, mode: str):

    # QUICK MODE → short, fun, but still JSON
    QUICK_PROMPT = f"""
You are RoastRank, a savage resume roasting AI.

Return ONLY JSON with these keys:
one_line
overview
fun_obs
score

Rules:
- Be funny.
- Be compact (1–2 lines per field).
- Score must be realistically between 20 and 95.
- one_line MUST be a roast, not generic.

Resume:
{text}
"""

    # FULL MODE → full sections, still compact
    FULL_PROMPT = f"""
You are RoastRank, a galactic CV roasting engine.

Return ONLY JSON with these keys:
one_line
overview
detailed
improvements
fun_obs
score

Rules:
- Every field ≤ 3 tight lines.
- Punchy and funny.
- Score between 20 and 95.
- Do NOT return explanations, only JSON.

Resume:
{text}
"""

    prompt = FULL_PROMPT if mode == "full" else QUICK_PROMPT

    res = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )

    output = res.output_text

    data = try_parse_json(output)

    # If LLM fails → fallback roast
    if not data:
        return {
            "one_line": "Your resume confused the AI — that's already a roast.",
            "overview": "The model failed to extract structured output.",
            "detailed": "",
            "improvements": "",
            "fun_obs": "Even the AI rage quit.",
            "score": 25
        }

    return data


# ------------------------------------------------------------
# ROUTES
# ------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload", response_class=HTMLResponse)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("quick")
):

    text = await extract_text_from_file(file)
    name = guess_name(text)

    roast = roast_resume(text, mode)

    score = roast.get("score", 50)
    one_line = roast.get("one_line", "")
    overview = roast.get("overview", "")
    detailed = roast.get("detailed", "")
    improvements = roast.get("improvements", "")
    fun_obs = roast.get("fun_obs", "")

    # Store
    cursor.execute("""
        INSERT INTO roasts (name, score, one_line, overview, detailed, improvements, fun_obs, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name, score, one_line, overview, detailed,
        improvements, fun_obs,
        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()

    return templates.TemplateResponse("result.html", {
        "request": request,
        "name": name,
        "score": score,
        "one_line": one_line,
        "overview": overview,
        "detailed": detailed,
        "improvements": improvements,
        "fun_obs": fun_obs
    })


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    cursor.execute("""
        SELECT name, score, one_line, created_at
        FROM roasts
        ORDER BY score DESC, created_at DESC
        LIMIT 100
    """)
    data = cursor.fetchall()

    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "roasts": data
    })


# ------------------------------------------------------------
# RUN APP (ignored on HuggingFace)
# ------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
