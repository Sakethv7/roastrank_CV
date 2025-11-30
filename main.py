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

from openai import OpenAI
from PyPDF2 import PdfReader
from docx import Document
import tempfile
import json

# ------------------ INIT ------------------
load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
if api_key:
    print(f"✅ OpenAI API key loaded (length {len(api_key)})")
    client = OpenAI(api_key=api_key)
else:
    print("❌ WARNING: OPENAI_API_KEY not set. Roasts will use fallback text.")
    client = None

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ------------------ DATABASE ------------------
conn = sqlite3.connect("roasts.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute(
    """
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
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """
)

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS daily_limits (
      ip TEXT,
      date TEXT,
      count INTEGER,
      PRIMARY KEY (ip, date)
    )
    """
)

conn.commit()

# ------------------ HELPERS ------------------


def clamp_score(value: int) -> int:
    """Clamp score into a sane range."""
    try:
        v = int(value)
    except Exception:
        return 70
    return max(30, min(99, v))


def build_fallback_roast() -> dict:
    """Fallback roast if OpenAI fails or key missing."""
    return {
        "score": 70,
        "one_line": "Your resume is like a data pipeline—overly complex and still not delivering anything useful.",
        "overview": "The model failed, but let's assume your CV is a work in progress with potential buried under clutter.",
        "detailed": (
            "Right now it reads more like raw logs than a story. "
            "Recruiters won't debug your life; bring the high-impact signals to the top."
        ),
        "strengths": "You clearly have real experience and initiative. There's substance once someone survives the layout.",
        "improvements": "Tighten bullets, group themes, and surface measurable impact in the first half of page one.",
        "fun_observation": "If resumes were logs, yours is running in DEBUG mode in production.",
    }


def normalize_roast(data: dict) -> dict:
    """Ensure all fields exist and are compact, using fallback defaults where needed."""
    if not isinstance(data, dict):
        return build_fallback_roast()

    base = build_fallback_roast()
    base.update(
        {
            "score": clamp_score(data.get("score", base["score"])),
            "one_line": (data.get("one_line") or "").strip() or base["one_line"],
            "overview": (data.get("overview") or "").strip() or base["overview"],
            "detailed": (data.get("detailed") or "").strip() or base["detailed"],
            "strengths": (data.get("strengths") or "").strip() or base["strengths"],
            "improvements": (data.get("improvements") or "").strip() or base["improvements"],
            "fun_observation": (data.get("fun_observation") or "").strip()
            or base["fun_observation"],
        }
    )
    return base


# ------------------ ROUTES ------------------


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    roasts = cursor.execute(
        """
        SELECT
          score,
          COALESCE(one_line, '') || '\n\n' || COALESCE(detailed, ''),
          created_at
        FROM roasts
        ORDER BY score DESC, created_at DESC
        LIMIT 50
        """
    ).fetchall()

    return templates.TemplateResponse(
        "leaderboard.html",
        {
            "request": request,
            "roasts": roasts,
        },
    )


@app.post("/upload", response_class=HTMLResponse)
async def upload_cv(request: Request, file: UploadFile = File(...)):
    ip = request.client.host
    today = datetime.now().strftime("%Y-%m-%d")

    # ---- RATE LIMIT ----
    cursor.execute("SELECT count FROM daily_limits WHERE ip=? AND date=?", (ip, today))
    row = cursor.fetchone()
    if row and row[0] >= 10:
        return HTMLResponse(
            "<h1 style='color:red;text-align:center;'>Daily Limit Reached</h1>",
            status_code=429,
        )

    # ---- READ FILE ----
    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    # ---- REUSE OLD ROAST IF SAME FILE ----
    existing = cursor.execute(
        """
        SELECT score, one_line, overview, detailed, strengths, improvements, fun_obs
        FROM roasts
        WHERE file_hash=?
        """,
        (file_hash,),
    ).fetchone()

    if existing:
        score, one_line, overview, detailed, strengths, improvements, fun_obs = existing
        data = {
            "score": score,
            "one_line": one_line,
            "overview": overview,
            "detailed": detailed,
            "strengths": strengths,
            "improvements": improvements,
            "fun_observation": fun_obs,
        }
        roast = normalize_roast(data)

        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "score": roast["score"],
                "one_line": roast["one_line"],
                "overview": roast["overview"],
                "detailed": roast["detailed"],
                "strengths": roast["strengths"],
                "improvements": roast["improvements"],
                "fun_obs": roast["fun_observation"],
            },
        )

    # ---- EXTRACT TEXT ----
    text = ""
    fname = (file.filename or "").lower()

    try:
        if fname.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(content))
            for page in reader.pages:
                text += (page.extract_text() or "") + "\n"

        elif fname.endswith(".docx"):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            doc = Document(tmp_path)
            text = "\n".join(p.text for p in doc.paragraphs)
            os.unlink(tmp_path)

        elif fname.endswith(".txt"):
            text = content.decode("utf-8", errors="ignore")

        else:
            return HTMLResponse(
                "<h1>Unsupported file type. Use PDF, DOCX, or TXT.</h1>", status_code=400
            )

    except Exception as e:
        print("FILE READ ERROR:", e)
        return HTMLResponse(
            "<h1>Error reading file. Try exporting a simpler version.</h1>",
            status_code=500,
        )

    if not text.strip():
        return HTMLResponse("<h1>No readable text found in file.</h1>", status_code=400)

    text = text[:15000]  # safety cap

    # ---------------- PROMPT ----------------
    REAL_DATE = "November 30, 2025"

    system_prompt = f"""
You are ROASTRANK — a brutally honest but ultimately helpful CV reviewer.

You MUST respond ONLY with a JSON object, no prose, no markdown, no backticks.

JSON SHAPE (strict):
{{
  "score": int,                 // 30–99
  "one_line": str,              // 1 punchy roast line
  "overview": str,              // 2–4 lines max
  "detailed": str,              // 3–6 lines max, compact
  "strengths": str,             // 2–4 lines max
  "improvements": str,          // 2–4 lines max, actionable
  "fun_observation": str        // 1–2 lines, witty
}}

STYLE:
- 70% roast, 30% genuine career coaching
- Be funny, confident, and sharp, but not cruel or offensive.
- Avoid giant paragraphs. Use short lines separated by line breaks.
- Assume ALL dates in the resume are valid and real.
- Today's date is {REAL_DATE}. Do NOT comment about “future” dates.

SCORING:
- 50–69: average CV with clear issues but some promise.
- 70–85: good CV with room to sharpen.
- 86–95: strong CV; only minor refinements.
- Only go below 50 if the resume is truly empty/chaotic.
""".strip()

    user_prompt = f"Here is the resume text:\n\n{text}"

    # ---------------- OPENAI CALL ----------------
    if client is None:
        roast = build_fallback_roast()
    else:
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=900,
            )

            raw = response.choices[0].message.content
            data = json.loads(raw)
            roast = normalize_roast(data)

        except Exception as e:
            print("OPENAI ERROR:", e)
            roast = build_fallback_roast()

    # ---------------- SAVE ----------------
    cursor.execute(
        """
        INSERT INTO roasts (file_hash, score, one_line, overview, detailed, strengths, improvements, fun_obs)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_hash,
            roast["score"],
            roast["one_line"],
            roast["overview"],
            roast["detailed"],
            roast["strengths"],
            roast["improvements"],
            roast["fun_observation"],
        ),
    )

    cursor.execute(
        """
        INSERT OR REPLACE INTO daily_limits (ip, date, count)
        VALUES (
          ?, ?,
          COALESCE((SELECT count FROM daily_limits WHERE ip=? AND date=?), 0) + 1
        )
        """,
        (ip, today, ip, today),
    )

    conn.commit()

    # ---------------- RENDER RESULT ----------------
    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "score": roast["score"],
            "one_line": roast["one_line"],
            "overview": roast["overview"],
            "detailed": roast["detailed"],
            "strengths": roast["strengths"],
            "improvements": roast["improvements"],
            "fun_obs": roast["fun_observation"],
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7860)
