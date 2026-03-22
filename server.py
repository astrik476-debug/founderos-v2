from flask import Flask, jsonify, request
from flask_cors import CORS
import threading, requests, json, re, os
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from groq import Groq
import jwt
import bcrypt
import psycopg2
import psycopg2.extras
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "founderos-secret-2024")
CORS(app, supports_credentials=True)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
MAIL_EMAIL = os.environ.get("MAIL_EMAIL", "")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
JWT_SECRET = "founderos-jwt-secret-2024"

client_gemini = genai.Client(api_key=GEMINI_API_KEY)
client_groq = Groq(api_key=GROQ_API_KEY)

password_reset_tokens = {}


def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def setup_db():
try:
conn = get_db()
cur = conn.cursor()
tables = [
"""CREATE TABLE IF NOT EXISTS users (
id SERIAL PRIMARY KEY,
email TEXT UNIQUE NOT NULL,
password TEXT NOT NULL,
name TEXT,
created_at TIMESTAMP DEFAULT NOW(),
onboarding_done INTEGER DEFAULT 0,
journey_start DATE DEFAULT CURRENT_DATE
)""",
"""CREATE TABLE IF NOT EXISTS founder_profiles (
id SERIAL PRIMARY KEY,
user_id INTEGER UNIQUE,
answers TEXT,
personality_type TEXT,
strengths TEXT,
weaknesses TEXT,
risk_profile TEXT,
execution_style TEXT,
decision_style TEXT,
growth_mindset_score INTEGER DEFAULT 0,
focus_score INTEGER DEFAULT 0,
productivity_pattern TEXT,
archetype TEXT,
ai_personality TEXT,
startup_name TEXT,
product TEXT,
industry TEXT,
stage TEXT,
market TEXT,
goal TEXT,
location TEXT,
timeline TEXT,
report_summary TEXT,
updated_at TIMESTAMP DEFAULT NOW()
)""",
"""CREATE TABLE IF NOT EXISTS tasks (
id SERIAL PRIMARY KEY,
user_id INTEGER,
title TEXT,
description TEXT,
how_to TEXT,
category TEXT,
priority TEXT,
time_est TEXT,
reason TEXT,
outcome TEXT,
done INTEGER DEFAULT 0,
started_at TIMESTAMP,
completed_at TIMESTAMP,
time_taken INTEGER DEFAULT 0,
verified INTEGER DEFAULT 0,
date DATE DEFAULT CURRENT_DATE
)""",
"""CREATE TABLE IF NOT EXISTS behaviour_log (
id SERIAL PRIMARY KEY,
user_id INTEGER,
date DATE DEFAULT CURRENT_DATE,
tasks_assigned INTEGER DEFAULT 0,
tasks_completed INTEGER DEFAULT 0,
tasks_avoided TEXT,
session_count INTEGER DEFAULT 0,
ai_interactions INTEGER DEFAULT 0,
patterns TEXT,
insight TEXT
)""",
"""CREATE TABLE IF NOT EXISTS chat_history (
id SERIAL PRIMARY KEY,
user_id INTEGER,
role TEXT,
content TEXT,
timestamp TIMESTAMP DEFAULT NOW()
)""",
"""CREATE TABLE IF NOT EXISTS daily_intelligence (
id SERIAL PRIMARY KEY,
user_id INTEGER,
date DATE DEFAULT CURRENT_DATE,
market_data TEXT,
competitor_data TEXT,
briefing TEXT,
opportunities TEXT,
generated_at TIMESTAMP DEFAULT NOW()
)""",
"""CREATE TABLE IF NOT EXISTS saved_reports (
id SERIAL PRIMARY KEY,
user_id INTEGER,
title TEXT,
content TEXT,
report_type TEXT,
created_at TIMESTAMP DEFAULT NOW()
)""",
"""CREATE TABLE IF NOT EXISTS content_library (
id SERIAL PRIMARY KEY,
user_id INTEGER,
platform TEXT,
content TEXT,
status TEXT DEFAULT 'draft',
created_at TIMESTAMP DEFAULT NOW()
)""",
"""CREATE TABLE IF NOT EXISTS market_data (
id SERIAL PRIMARY KEY,
user_id INTEGER,
query TEXT,
data TEXT,
sources TEXT,
saved_at TIMESTAMP DEFAULT NOW()
)""",
"""CREATE TABLE IF NOT EXISTS competitor_data (
id SERIAL PRIMARY KEY,
user_id INTEGER,
data TEXT,
saved_at TIMESTAMP DEFAULT NOW()
)"""
]
for table in tables:
cur.execute(table)
conn.commit()
cur.close()
conn.close()
print("Database setup complete")
except Exception as e:
print(f"Database setup error: {e}")


def create_token(user_id):
payload = {
"user_id": user_id,
"exp": datetime.utcnow() + timedelta(days=30)
}
return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_token(token):
try:
payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
return payload["user_id"]
except:
return None


def get_current_user():
auth = request.headers.get("Authorization", "")
if auth.startswith("Bearer "):
token = auth[7:]
user_id = verify_token(token)
if user_id:
try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
user = cur.fetchone()
cur.close()
conn.close()
return dict(user) if user else None
except:
return None
return None


def require_auth(f):
from functools import wraps
@wraps(f)
def decorated(*args, **kwargs):
user = get_current_user()
if not user:
return jsonify({"error": "Unauthorized"}), 401
return f(user, *args, **kwargs)
return decorated


def ask_gemini(prompt, system="", max_tokens=2000):
try:
full_prompt = f"{system}\n\n{prompt}" if system else prompt
response = client_gemini.models.generate_content(
model="gemini-1.5-flash",
contents=full_prompt,
config=types.GenerateContentConfig(
max_output_tokens=max_tokens,
temperature=0.7
)
)
return response.text
except Exception as e:
print(f"Gemini error: {e}")
return None


def ask_groq(prompt, system="", max_tokens=1500, deep=False):
try:
model = "deepseek-r1-distill-llama-70b" if deep else "llama-3.3-70b-versatile"
messages = []
if system:
messages.append({"role": "system", "content": system})
messages.append({"role": "user", "content": prompt})
response = client_groq.chat.completions.create(
model=model,
messages=messages,
max_tokens=max_tokens,
temperature=0.7
)
text = response.choices[0].message.content
if deep and "<think>" in text:
text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
return text
except Exception as e:
print(f"Groq error: {e}")
return "I am having trouble connecting right now. Please try again in a moment."


def serper_search(query, search_type="search", num=5):
try:
headers = {
"X-API-KEY": SERPER_API_KEY,
"Content-Type": "application/json"
}
if search_type == "news":
payload = {"q": query, "num": num}
resp = requests.post(
"https://google.serper.dev/news",
headers=headers, json=payload, timeout=10
)
data = resp.json()
results = []
for item in data.get("news", [])[:num]:
results.append({
"title": item.get("title", ""),
"snippet": item.get("snippet", ""),
"link": item.get("link", ""),
"source": item.get("source", ""),
"date": item.get("date", "")
})
return results
else:
if search_type == "reddit":
payload = {"q": f"site:reddit.com {query}", "num": num}
elif search_type == "linkedin":
payload = {"q": f"site:linkedin.com {query}", "num": num}
elif search_type == "youtube":
payload = {"q": f"site:youtube.com {query}", "num": num}
elif search_type == "quora":
payload = {"q": f"site:quora.com {query}", "num": num}
elif search_type == "twitter":
payload = {"q": f"site:twitter.com {query}", "num": num}
else:
payload = {"q": query, "num": num}
resp = requests.post(
"https://google.serper.dev/search",
headers=headers, json=payload, timeout=10
)
data = resp.json()
results = []
for item in data.get("organic", [])[:num]:
results.append({
"title": item.get("title", ""),
"snippet": item.get("snippet", ""),
"link": item.get("link", ""),
"source": item.get("displayLink", "")
})
return results
except Exception as e:
print(f"Serper error: {e}")
return []


def reddit_search(query, limit=8):
try:
url = f"https://www.reddit.com/search.json?q={requests.utils.quote(query)}&sort=relevance&limit={limit}"
headers = {"User-Agent": "FounderOS/1.0"}
resp = requests.get(url, headers=headers, timeout=8)
data = resp.json()
results = []
for post in data.get("data", {}).get("children", []):
p = post.get("data", {})
results.append({
"title": p.get("title", ""),
"text": p.get("selftext", "")[:500],
"subreddit": p.get("subreddit", ""),
"score": p.get("score", 0),
"url": f"https://reddit.com{p.get('permalink', '')}",
"comments": p.get("num_comments", 0)
})
return results
except Exception as e:
print(f"Reddit error: {e}")
return []


def multi_search(queries_dict):
results = {}
threads = []

def fetch(key, query, stype):
if stype == "reddit_native":
results[key] = reddit_search(query)
else:
results[key] = serper_search(query, stype)

for key, (query, stype) in queries_dict.items():
t = threading.Thread(target=fetch, args=(key, query, stype))
threads.append(t)
t.start()
for t in threads:
t.join()
return results


def format_search_results(results_dict):
formatted = ""
total = 0
for source, items in results_dict.items():
if items:
formatted += f"\n[SOURCE: {source.upper()}]\n"
for item in items[:4]:
if isinstance(item, dict):
text = item.get("snippet") or item.get("text") or item.get("title", "")
title = item.get("title", "")
if text and len(text) > 10:
formatted += f"- {title}: {text[:300]}\n"
total += 1
return formatted, total


def get_profile(user_id):
try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT * FROM founder_profiles WHERE user_id=%s", (user_id,))
profile = cur.fetchone()
cur.close()
conn.close()
return dict(profile) if profile else {}
except Exception as e:
print(f"Profile error: {e}")
return {}


def get_behaviour(user_id):
try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute(
"SELECT * FROM behaviour_log WHERE user_id=%s ORDER BY date DESC LIMIT 7",
(user_id,)
)
logs = cur.fetchall()
cur.close()
conn.close()
return [dict(l) for l in logs]
except:
return []


def get_days_on_journey(user):
days = 0
try:
start = user.get("journey_start")
if start:
if isinstance(start, str):
start = datetime.strptime(start, "%Y-%m-%d")
elif hasattr(start, 'year'):
start = datetime(start.year, start.month, start.day)
days = (datetime.now() - start).days
except:
pass
return days


def build_deep_context(user, profile):
if not profile:
return f"Founder: {user.get('name', 'Founder')}. Profile not yet complete."

days = get_days_on_journey(user)
behaviour = get_behaviour(user["id"])
avg_completion = 0
avoided_patterns = []
if behaviour:
completions = [
b["tasks_completed"] / max(b["tasks_assigned"], 1) * 100
for b in behaviour if b.get("tasks_assigned", 0) > 0
]
if completions:
avg_completion = sum(completions) / len(completions)
for b in behaviour:
if b.get("tasks_avoided"):
try:
avoided = json.loads(b["tasks_avoided"])
avoided_patterns.extend(avoided)
except:
pass

strengths = profile.get("strengths", "[]")
weaknesses = profile.get("weaknesses", "[]")
try:
strengths = json.loads(strengths) if isinstance(strengths, str) else strengths
weaknesses = json.loads(weaknesses) if isinstance(weaknesses, str) else weaknesses
except:
strengths = []
weaknesses = []

return f"""
DEEP FOUNDER CONTEXT — This is everything known about this founder:

Identity:
- Name: {user.get('name', 'Founder')}
- Location: {profile.get('location', 'India')}
- Day {days} of their founder journey

Startup:
- Name: {profile.get('startup_name', 'Not specified')}
- Product: {profile.get('product', 'Not specified')}
- Industry: {profile.get('industry', 'Not specified')}
- Stage: {profile.get('stage', 'idea')}
- Target Market: {profile.get('market', 'Not specified')}
- Primary Goal: {profile.get('goal', 'Not specified')}
- Timeline: {profile.get('timeline', 'Not specified')}

Founder Psychology:
- Personality Type: {profile.get('personality_type', 'Not analyzed')}
- Archetype: {profile.get('archetype', 'Not analyzed')}
- Decision Style: {profile.get('decision_style', 'Not analyzed')}
- Execution Style: {profile.get('execution_style', 'Not analyzed')}
- Risk Profile: {profile.get('risk_profile', 'Not analyzed')}
- Growth Mindset Score: {profile.get('growth_mindset_score', 0)}/10
- Focus Score: {profile.get('focus_score', 0)}/10
- Productivity Pattern: {profile.get('productivity_pattern', 'Not analyzed')}

Strengths: {', '.join(strengths) if strengths else 'Not analyzed'}
Weaknesses: {', '.join(weaknesses) if weaknesses else 'Not analyzed'}
Report Summary: {profile.get('report_summary', 'Not analyzed')}

Behaviour Data Last 7 Days:
- Average Task Completion Rate: {avg_completion:.0f}%
- Consistency Level: {'Strong — above 70 percent' if avg_completion > 70 else 'Building — 40 to 70 percent' if avg_completion > 40 else 'Needs attention — below 40 percent'}
- Tasks Being Avoided: {', '.join(set(avoided_patterns[:5])) if avoided_patterns else 'No patterns detected yet'}

AI Personality Mode: {profile.get('ai_personality', 'mentor')}
"""


@app.route("/api/auth/signup", methods=["POST"])
def signup():
data = request.json
email = data.get("email", "").strip().lower()
password = data.get("password", "")
name = data.get("name", "").strip()
if not email or not password or not name:
return jsonify({"error": "Name, email and password required"}), 400
if len(password) < 6:
return jsonify({"error": "Password must be at least 6 characters"}), 400
hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute(
"INSERT INTO users (email, password, name) VALUES (%s,%s,%s) RETURNING *",
(email, hashed, name)
)
user = cur.fetchone()
conn.commit()
cur.close()
conn.close()
token = create_token(user["id"])
return jsonify({
"success": True, "token": token,
"name": name, "onboarding_done": False
})
except psycopg2.IntegrityError:
return jsonify({"error": "Email already registered"}), 400
except Exception as e:
print(f"Signup error: {e}")
return jsonify({"error": "Server error"}), 500


@app.route("/api/auth/login", methods=["POST"])
def login():
data = request.json
email = data.get("email", "").strip().lower()
password = data.get("password", "")
try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT * FROM users WHERE email=%s", (email,))
user = cur.fetchone()
cur.close()
conn.close()
if not user or not bcrypt.checkpw(
password.encode(), user["password"].encode()
):
return jsonify({"error": "Invalid email or password"}), 401
token = create_token(user["id"])
return jsonify({
"success": True, "token": token,
"name": user["name"],
"onboarding_done": bool(user["onboarding_done"])
})
except Exception as e:
print(f"Login error: {e}")
return jsonify({"error": "Server error"}), 500


@app.route("/api/auth/me")
@require_auth
def get_me(user):
return jsonify({
"id": user["id"], "name": user["name"],
"email": user["email"],
"onboarding_done": bool(user["onboarding_done"]),
"journey_start": str(user.get("journey_start", ""))
})


@app.route("/api/auth/forgot-password", methods=["POST"])
def forgot_password():
data = request.json
email = data.get("email", "").strip().lower()
if not email:
return jsonify({"error": "Email required"}), 400
try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT * FROM users WHERE email=%s", (email,))
user = cur.fetchone()
cur.close()
conn.close()
if not user:
return jsonify({"success": True})
reset_token = secrets.token_urlsafe(32)
password_reset_tokens[reset_token] = {
"email": email,
"name": user["name"],
"expires": (datetime.utcnow() + timedelta(hours=1)).isoformat()
}
reset_link = f"{request.host_url}?reset={reset_token}"
if MAIL_EMAIL and MAIL_PASSWORD:
try:
msg = MIMEMultipart("alternative")
msg["Subject"] = "Reset your FounderOS password"
msg["From"] = MAIL_EMAIL
msg["To"] = email
html = f"""
<div style="font-family:Inter,sans-serif;max-width:480px;margin:0 auto;padding:40px 20px">
<div style="background:#1a1d23;width:40px;height:40px;border-radius:10px;display:inline-flex;align-items:center;justify-content:center;margin-bottom:24px">
<span style="color:white;font-weight:800;font-size:18px">F</span>
</div>
<h2 style="font-size:22px;font-weight:700;color:#1a1d23;margin-bottom:8px">Reset your password</h2>
<p style="color:#6b7280;font-size:14px;line-height:1.6;margin-bottom:24px">
Hi {user['name']}, click the button below to reset your FounderOS password.
</p>
<a href="{reset_link}" style="background:#1a1d23;color:white;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;display:inline-block;margin-bottom:24px">
Reset Password
</a>
<p style="color:#9ca3af;font-size:12px">This link expires in 1 hour.</p>
</div>
"""
msg.attach(MIMEText(html, "html"))
server = smtplib.SMTP("smtp.gmail.com", 587)
server.starttls()
server.login(MAIL_EMAIL, MAIL_PASSWORD)
server.sendmail(MAIL_EMAIL, email, msg.as_string())
server.quit()
except Exception as e:
print(f"Email error: {e}")
print(f"Reset link: {reset_link}")
return jsonify({"success": True, "message": "Reset instructions sent"})
except Exception as e:
print(f"Forgot password error: {e}")
return jsonify({"success": True})


@app.route("/api/auth/reset-password", methods=["POST"])
def reset_password():
data = request.json
token = data.get("token", "")
new_password = data.get("password", "")
if not token or not new_password or len(new_password) < 6:
return jsonify({"error": "Valid token and password required"}), 400
token_data = password_reset_tokens.get(token)
if not token_data:
return jsonify({"error": "Invalid or expired reset link"}), 400
try:
expires = datetime.fromisoformat(token_data["expires"])
if datetime.utcnow() > expires:
del password_reset_tokens[token]
return jsonify({"error": "Reset link has expired"}), 400
except:
return jsonify({"error": "Invalid token"}), 400
email = token_data["email"]
hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
try:
conn = get_db()
cur = conn.cursor()
cur.execute("UPDATE users SET password=%s WHERE email=%s", (hashed, email))
conn.commit()
cur.close()
conn.close()
del password_reset_tokens[token]
return jsonify({"success": True, "message": "Password updated successfully"})
except Exception as e:
print(f"Reset password error: {e}")
return jsonify({"error": "Server error"}), 500


@app.route("/api/onboarding/submit", methods=["POST"])
@require_auth
def submit_onboarding(user):
data = request.json
answers = data.get("answers", {})

prompt = f"""
Analyze this founder profile and generate their Founder Intelligence Report.

Answers:
{json.dumps(answers, indent=2)}

Return ONLY valid JSON. No markdown. No extra text:
{{
"archetype": "Specific 3-5 word founder archetype",
"personality_type": "Detailed personality in 2 sentences",
"decision_style": "analytical or intuitive or consultative or decisive",
"execution_style": "systematic or agile or opportunistic or methodical",
"risk_profile": "conservative or moderate or aggressive or calculated",
"growth_mindset_score": 7,
"focus_score": 6,
"productivity_pattern": "When and how they work best",
"strengths": ["strength 1", "strength 2", "strength 3"],
"weaknesses": ["weakness 1", "weakness 2", "weakness 3"],
"ai_personality": "one of: tough-love, encouraging, analytical, challenger, mentor",
"report_summary": "4-5 sentence honest assessment of this specific founder",
"predicted_timeline": {{
"first_customer": "realistic timeframe",
"first_revenue": "realistic timeframe",
"first_10k_revenue": "realistic timeframe",
"product_market_fit": "realistic timeframe"
}},
"key_insight": "Single most important thing this founder needs to understand about themselves",
"biggest_risk": "Most likely way this founder will self-sabotage",
"superpower": "The one thing that could make this founder unstoppable"
}}
"""

report_text = ask_gemini(prompt, max_tokens=1500)
if not report_text:
report_text = ask_groq(prompt, max_tokens=1200)

try:
clean = report_text.strip()
if "```" in clean:
clean = re.sub(r'```json\n?|\n?```', '', clean)
start_idx = clean.find('{')
end_idx = clean.rfind('}') + 1
if start_idx != -1:
clean = clean[start_idx:end_idx]
report = json.loads(clean)
except:
report = {
"archetype": "Determined First-Time Builder",
"personality_type": "A focused individual serious about building something meaningful.",
"decision_style": "analytical",
"execution_style": "systematic",
"risk_profile": "moderate",
"growth_mindset_score": 7,
"focus_score": 6,
"productivity_pattern": "Most productive with structured daily routines",
"strengths": ["Strong vision", "Determination", "Domain knowledge"],
"weaknesses": ["Sales experience", "Marketing", "Financial planning"],
"ai_personality": "mentor",
"report_summary": "You are at the beginning of your founder journey with a clear vision.",
"predicted_timeline": {
"first_customer": "2-3 months",
"first_revenue": "3-4 months",
"first_10k_revenue": "6-9 months",
"product_market_fit": "12-18 months"
},
"key_insight": "Focus on talking to customers before building features",
"biggest_risk": "Building without validating demand first",
"superpower": "Your determination to see this through"
}

profile_data = {
"startup_name": answers.get("q11", ""),
"product": answers.get("q12", ""),
"industry": answers.get("q13", ""),
"stage": answers.get("q16", "idea"),
"market": answers.get("q19", ""),
"goal": answers.get("q21", ""),
"location": answers.get("q2", "India"),
"timeline": answers.get("q22", ""),
}

strengths_json = json.dumps(report.get("strengths", []))
weaknesses_json = json.dumps(report.get("weaknesses", []))

try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT id FROM founder_profiles WHERE user_id=%s", (user["id"],))
existing = cur.fetchone()

if existing:
cur.execute("""
UPDATE founder_profiles SET
answers=%s, personality_type=%s, strengths=%s, weaknesses=%s,
risk_profile=%s, execution_style=%s, decision_style=%s,
growth_mindset_score=%s, focus_score=%s, productivity_pattern=%s,
archetype=%s, ai_personality=%s, startup_name=%s, product=%s,
industry=%s, stage=%s, market=%s, goal=%s, location=%s, timeline=%s,
report_summary=%s, updated_at=NOW()
WHERE user_id=%s
""", (
json.dumps(answers), report.get("personality_type", ""),
strengths_json, weaknesses_json,
report.get("risk_profile", ""), report.get("execution_style", ""),
report.get("decision_style", ""), report.get("growth_mindset_score", 5),
report.get("focus_score", 5), report.get("productivity_pattern", ""),
report.get("archetype", ""), report.get("ai_personality", "mentor"),
profile_data["startup_name"], profile_data["product"],
profile_data["industry"], profile_data["stage"],
profile_data["market"], profile_data["goal"],
profile_data["location"], profile_data["timeline"],
report.get("report_summary", ""), user["id"]
))
else:
cur.execute("""
INSERT INTO founder_profiles
(user_id, answers, personality_type, strengths, weaknesses,
risk_profile, execution_style, decision_style, growth_mindset_score,
focus_score, productivity_pattern, archetype, ai_personality,
startup_name, product, industry, stage, market, goal,
location, timeline, report_summary)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
""", (
user["id"], json.dumps(answers), report.get("personality_type", ""),
strengths_json, weaknesses_json,
report.get("risk_profile", ""), report.get("execution_style", ""),
report.get("decision_style", ""), report.get("growth_mindset_score", 5),
report.get("focus_score", 5), report.get("productivity_pattern", ""),
report.get("archetype", ""), report.get("ai_personality", "mentor"),
profile_data["startup_name"], profile_data["product"],
profile_data["industry"], profile_data["stage"],
profile_data["market"], profile_data["goal"],
profile_data["location"], profile_data["timeline"],
report.get("report_summary", "")
))

cur.execute("UPDATE users SET onboarding_done=1 WHERE id=%s", (user["id"],))
conn.commit()
cur.close()
conn.close()
return jsonify({"success": True, "report": report})
except Exception as e:
print(f"Onboarding error: {e}")
return jsonify({"error": "Server error saving profile"}), 500


@app.route("/api/profile/report")
@require_auth
def get_founder_report(user):
profile = get_profile(user["id"])
if not profile:
return jsonify({"error": "Profile not found"}), 404

days = get_days_on_journey(user)

try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT COUNT(*) as cnt FROM tasks WHERE user_id=%s", (user["id"],))
total_tasks = cur.fetchone()["cnt"]
cur.execute("SELECT COUNT(*) as cnt FROM tasks WHERE user_id=%s AND done=1", (user["id"],))
done_tasks = cur.fetchone()["cnt"]
cur.close()
conn.close()
except:
total_tasks = 0
done_tasks = 0

strengths = profile.get("strengths", "[]")
weaknesses = profile.get("weaknesses", "[]")
try:
strengths = json.loads(strengths) if isinstance(strengths, str) else strengths
weaknesses = json.loads(weaknesses) if isinstance(weaknesses, str) else weaknesses
except:
strengths = []
weaknesses = []

return jsonify({
"archetype": profile.get("archetype", ""),
"personality_type": profile.get("personality_type", ""),
"decision_style": profile.get("decision_style", ""),
"execution_style": profile.get("execution_style", ""),
"risk_profile": profile.get("risk_profile", ""),
"growth_mindset_score": profile.get("growth_mindset_score", 0),
"focus_score": profile.get("focus_score", 0),
"productivity_pattern": profile.get("productivity_pattern", ""),
"strengths": strengths,
"weaknesses": weaknesses,
"report_summary": profile.get("report_summary", ""),
"days_journey": days,
"total_tasks": total_tasks,
"completed_tasks": done_tasks,
"completion_rate": round(done_tasks / max(total_tasks, 1) * 100),
"startup_name": profile.get("startup_name", ""),
"stage": profile.get("stage", ""),
"updated_at": str(profile.get("updated_at", ""))
})


@app.route("/api/chat", methods=["POST"])
@require_auth
def chat(user):
data = request.json
message = data.get("message", "")
mode = data.get("mode", "quick")
profile = get_profile(user["id"])
context = build_deep_context(user, profile)
message_lower = message.lower().strip()

try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute(
"SELECT role, content FROM chat_history WHERE user_id=%s ORDER BY id DESC LIMIT 12",
(user["id"],)
)
history = list(reversed([dict(h) for h in cur.fetchall()]))
cur.close()
conn.close()
except:
history = []

is_greeting = len(message.split()) <= 4 and any(
message_lower.startswith(p) for p in [
"hey", "hi", "hello", "good morning", "good evening",
"thanks", "thank you", "ok", "okay", "sup"
]
)

web_context = ""
web_total = 0

if not is_greeting and len(message) > 10:
industry = profile.get("industry", "")
location = profile.get("location", "India")
product = profile.get("product", "")

search_queries = {
"google": (f"{message} {industry} {location} 2025", "search"),
"news": (f"{message} {industry} latest news 2025", "news"),
"reddit": (f"{message} {industry} {location} founder experience", "reddit_native"),
"linkedin": (f"{message} {industry} {location} 2025", "linkedin"),
"quora": (f"{message} {industry} India", "quora"),
}
all_results = multi_search(search_queries)
web_context, web_total = format_search_results(all_results)

personality = profile.get("ai_personality", "mentor")
personality_map = {
"tough-love": "Be direct and demanding. Push back on weak thinking and avoidance. You believe in this founder but refuse to let them make excuses. Call out patterns you see in their behaviour data.",
"encouraging": "Be warm and genuinely excited about their progress. Celebrate every real step forward. Keep energy high. Still completely honest but always framed constructively.",
"analytical": "Lead with data, frameworks, and logical structure. Use numbers and percentages. Reference their completion rates and behaviour patterns. Be precise and structured in your responses.",
"challenger": "Question every assumption they make. Push back hard. Play devil's advocate. Force them to think three levels deeper than they naturally would. Make them defend their decisions.",
"mentor": "Be wise, patient, and thoughtful. Guide through powerful questions as much as direct answers. Help them develop their own thinking. Share perspective from experience without prescribing."
}

system = (
"You are the AI Co-Founder of FounderOS. You are not a chatbot. You are not ChatGPT. "
"You are a deeply intelligent execution partner who has been working alongside this founder "
"since day one and knows their business, their fears, their behaviour patterns, and their "
"goals more deeply than anyone else.\n\n"
+ context +
"\n\nYOUR PERSONALITY AND COMMUNICATION STYLE:\n"
"You speak like a brilliant co-founder who has built companies before and genuinely cares "
"about this founder's success. You are warm but direct. You are honest even when it is "
"uncomfortable. You celebrate real progress but never give fake encouragement. You push back "
"when the founder is avoiding hard things. You ask sharp questions that make them think deeper. "
"You remember everything about their journey and reference it naturally in conversation.\n\n"
"You write in flowing natural paragraphs, never robotic bullet lists as your primary format. "
"You give reasoning behind every recommendation, not just instructions. Every single response "
"references their specific product, their specific market, their specific stage. You never give "
"advice that could apply to any random founder anywhere in the world.\n\n"
"You never start a response with Certainly, Great, Absolutely, Sure, Of course, or any filler "
"opener. You get straight to the point with intelligence and warmth.\n\n"
"For greetings respond warmly and personally in 2-3 sentences. Reference their journey or their "
"startup. Ask one genuinely curious question about what they are working on right now.\n\n"
"For business questions give thorough specific paragraph-based responses grounded in their context "
"and the live research data found. Lead with the most important insight first.\n\n"
"For emotional moments like wanting to quit acknowledge the feeling fully and honestly first "
"without dismissing it. Then ground them in their specific real progress data. Then give one "
"small concrete action they can do in the next 10 minutes.\n\n"
"WHAT MAKES YOUR ADVICE DIFFERENT FROM CHATGPT:\n"
"ChatGPT knows nothing about this founder. Every conversation with ChatGPT starts from zero. "
"ChatGPT gives brilliant generic advice that could apply to anyone anywhere. You give advice "
"that is only possible because you know THIS founder deeply.\n\n"
"You know their archetype, their decision style, their execution style, their risk profile, "
"their skill gaps, their avoidance patterns, how many tasks they completed this week, what "
"they have been avoiding, and what their market looks like right now based on live research "
"from Reddit, LinkedIn, Quora, and Google.\n\n"
"You do not just answer questions. You notice patterns. If they keep asking about product "
"features but never about sales, you name that pattern. If their completion rate dropped this "
"week, you reference it. If their market has a new signal from Reddit or LinkedIn, you bring "
"it up before they ask. This is the difference between a brilliant stranger and a co-founder "
"who has been in the trenches with them.\n\n"
"Personality mode: " + personality + "\n"
+ personality_map.get(personality, '') +
"\n\nCRITICAL RULES:\n"
"- Always reference their specific product "
+ profile.get('product', '') +
" and location "
+ profile.get('location', 'India') +
" in every substantive response\n"
"- For sales pitches write the complete pitch word for word, not advice about what to include\n"
"- For competitor questions name real local competitors in their city and country first, "
"never lead with global giants\n"
"- For market research show what you actually found in Reddit discussions, LinkedIn posts, "
"Quora answers, and news. Quote real sentiments from real platforms.\n"
"- For idea generation base recommendations on real demand signals found in live research\n"
"- Keep responses under 400 words unless writing a complete document or full plan\n"
"- If they mention quitting never agree. Acknowledge the emotion, show them real progress "
"data, give one action for the next 10 minutes\n"
"- Never invent statistics or research data. If it was not found say so clearly"
)

history_text = "\n".join([
f"{h['role'].upper()}: {h['content']}" for h in history[-8:]
])

days = get_days_on_journey(user)

if is_greeting:
full_prompt = (
f"Conversation so far:\n{history_text}\n\n"
f"{user.get('name', 'Founder')} just said: {message}\n\n"
f"Respond warmly and naturally. You know them well. "
f"Mention Day {days} of their journey if it feels natural. "
f"Reference their startup {profile.get('startup_name', '')} or stage {profile.get('stage', '')}. "
f"Ask one genuinely curious question about what they are working on right now. "
f"Under 80 words. Human. Warm. No lists."
)
reply = ask_groq(full_prompt, system=system, max_tokens=180)
else:
data_note = (
f"\n\nLive research data found from Reddit, LinkedIn, Quora, Google, and News ({web_total} sources):\n{web_context}"
if web_context
else "\n\nNote: Limited search data returned for this specific query."
)
full_prompt = (
f"Previous conversation:\n{history_text}"
f"{data_note}\n\n"
f"{user.get('name', 'Founder')} asks: {message}\n\n"
f"Respond as their deeply knowledgeable co-founder. "
f"Be completely specific to their product {profile.get('product', '')} "
f"in {profile.get('location', 'India')}. "
f"Reference specific things found in the research data above. "
f"Mode: {mode}"
)
use_deep = mode in ["deep", "plan"]
reply = ask_groq(
full_prompt, system=system,
max_tokens=1000 if use_deep else 700,
deep=use_deep
)

try:
conn = get_db()
cur = conn.cursor()
cur.execute(
"INSERT INTO chat_history (user_id, role, content) VALUES (%s,%s,%s)",
(user["id"], "user", message)
)
cur.execute(
"INSERT INTO chat_history (user_id, role, content) VALUES (%s,%s,%s)",
(user["id"], "assistant", reply)
)
conn.commit()
cur.close()
conn.close()
except Exception as e:
print(f"Chat history error: {e}")

return jsonify({
"reply": reply,
"sources_found": web_total,
"success": True
})


@app.route("/api/tasks/generate", methods=["POST"])
@require_auth
def generate_tasks(user):
profile = get_profile(user["id"])
context = build_deep_context(user, profile)
location = profile.get("location", "India")

try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute(
"SELECT COUNT(*) as cnt FROM tasks WHERE user_id=%s AND done=1 AND date=CURRENT_DATE - INTERVAL '1 day'",
(user["id"],)
)
completed_yesterday = cur.fetchone()["cnt"]
cur.execute(
"SELECT COUNT(*) as cnt FROM tasks WHERE user_id=%s AND date=CURRENT_DATE - INTERVAL '1 day'",
(user["id"],)
)
total_yesterday = cur.fetchone()["cnt"]
cur.execute(
"SELECT title FROM tasks WHERE user_id=%s AND done=0 AND date<CURRENT_DATE LIMIT 5",
(user["id"],)
)
avoided = [a["title"] for a in cur.fetchall()]
cur.close()
conn.close()
except Exception as e:
print(f"Task gen query error: {e}")
completed_yesterday = 0
total_yesterday = 0
avoided = []

avoidance_note = f"Tasks being avoided repeatedly: {', '.join(avoided)}" if avoided else ""

prompt = f"""
{context}

Yesterday: completed {completed_yesterday} of {total_yesterday} tasks.
{avoidance_note}

Generate exactly 5 highly specific tasks for today completely tailored to:
- Product: {profile.get('product', '')}
- Industry: {profile.get('industry', '')}
- Stage: {profile.get('stage', '')}
- Location: {location}
- Weaknesses: {profile.get('weaknesses', '[]')}
- Goal: {profile.get('goal', '')}
- Avoidance patterns: {avoidance_note}

Return ONLY a valid JSON array. No markdown. No other text:
[
{{
"title": "Specific task title mentioning their product or market — not generic",
"description": "2 sentences explaining exactly what to do and why it matters for their specific startup right now.",
"how_to": "Step 1: Specific action with exact tool or platform name. Step 2: Specific action with exact method. Step 3: Specific action. Step 4: How to measure if this worked.",
"category": "one of: revenue, validation, marketing, product, operations, research",
"priority": "one of: critical, high, medium",
"time_est": "realistic time estimate",
"outcome": "Exactly what success looks like when this task is done well today"
}}
]

Rules:
- First 2 tasks must directly relate to revenue or customer validation
- At least one task must address an avoided task or weakness
- At least one task must involve talking to a real potential customer
- Every how_to must have 4 specific steps with real platform names like LinkedIn, IndiaMART, WhatsApp, Instagram, etc
- Never generate generic tasks — every task must be undeniably about their specific startup
- If they are avoiding sales tasks, include a sales task they cannot avoid
"""

tasks_text = ask_groq(prompt, max_tokens=2000)

try:
clean = tasks_text.strip()
if "```" in clean:
clean = re.sub(r'```json\n?|\n?```', '', clean)
start_idx = clean.find('[')
end_idx = clean.rfind(']') + 1
if start_idx != -1 and end_idx > start_idx:
clean = clean[start_idx:end_idx]
tasks = json.loads(clean)
except:
tasks = [{
"title": f"Talk to 3 potential customers about {profile.get('product', 'your product')} today",
"description": f"Contact 3 real people who could be your first customers in {location}. Have a real conversation about their problem, not a sales pitch.",
"how_to": "Step 1: Open LinkedIn and search for people in your target customer category in your city. Step 2: Send a personalised connection request mentioning you are building something and want their perspective. Step 3: When they accept ask one specific question about the problem your product solves. Step 4: Record their exact words — this is your market research.",
"category": "validation",
"priority": "critical",
"time_est": "2 hours",
"outcome": "3 real conversations completed with notes on whether the problem is real and urgent for them"
}]

try:
conn = get_db()
cur = conn.cursor()
cur.execute(
"DELETE FROM tasks WHERE user_id=%s AND date=CURRENT_DATE AND done=0",
(user["id"],)
)
for task in tasks:
cur.execute(
"INSERT INTO tasks (user_id, title, description, how_to, category, priority, time_est, outcome) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
(
user["id"], task.get("title"), task.get("description"),
task.get("how_to"), task.get("category"), task.get("priority"),
task.get("time_est"), task.get("outcome", "")
)
)
try:
cur.execute(
"INSERT INTO behaviour_log (user_id, date, tasks_assigned, tasks_avoided) VALUES (%s, CURRENT_DATE, %s, %s) ON CONFLICT DO NOTHING",
(user["id"], len(tasks), json.dumps(avoided))
)
except:
pass
conn.commit()
cur.close()
conn.close()
return jsonify({"success": True, "count": len(tasks)})
except Exception as e:
print(f"Task insert error: {e}")
return jsonify({"error": "Error saving tasks"}), 500


@app.route("/api/tasks")
@require_auth
def get_tasks(user):
try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute(
"""SELECT * FROM tasks WHERE user_id=%s AND date=CURRENT_DATE
ORDER BY CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 ELSE 3 END""",
(user["id"],)
)
rows = cur.fetchall()
cur.close()
conn.close()
return jsonify({"tasks": [dict(r) for r in rows]})
except Exception as e:
print(f"Get tasks error: {e}")
return jsonify({"tasks": []})


@app.route("/api/tasks/<int:task_id>/start", methods=["POST"])
@require_auth
def start_task(user, task_id):
try:
conn = get_db()
cur = conn.cursor()
cur.execute(
"UPDATE tasks SET started_at=NOW() WHERE id=%s AND user_id=%s",
(task_id, user["id"])
)
conn.commit()
cur.close()
conn.close()
return jsonify({"success": True})
except Exception as e:
return jsonify({"error": str(e)}), 500


@app.route("/api/tasks/<int:task_id>/complete", methods=["POST"])
@require_auth
def complete_task(user, task_id):
data = request.json or {}
time_spent = data.get("time_spent", 0)
try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute(
"SELECT * FROM tasks WHERE id=%s AND user_id=%s", (task_id, user["id"])
)
task = cur.fetchone()
if not task:
cur.close()
conn.close()
return jsonify({"error": "Task not found"}), 404
if time_spent < 30 and task["priority"] in ["critical", "high"]:
cur.close()
conn.close()
return jsonify({
"verified": False,
"message": f"This is a {task['priority']} priority task. Have you actually completed it?"
})
cur.execute(
"UPDATE tasks SET done=1, verified=1, completed_at=NOW(), time_taken=%s WHERE id=%s AND user_id=%s",
(time_spent, task_id, user["id"])
)
try:
cur.execute(
"UPDATE behaviour_log SET tasks_completed=tasks_completed+1 WHERE user_id=%s AND date=CURRENT_DATE",
(user["id"],)
)
except:
pass
conn.commit()
cur.close()
conn.close()
return jsonify({"success": True, "verified": True})
except Exception as e:
print(f"Complete task error: {e}")
return jsonify({"error": "Server error"}), 500


@app.route("/api/tasks/<int:task_id>/confirm", methods=["POST"])
@require_auth
def confirm_task(user, task_id):
try:
conn = get_db()
cur = conn.cursor()
cur.execute(
"UPDATE tasks SET done=1, verified=1, completed_at=NOW() WHERE id=%s AND user_id=%s",
(task_id, user["id"])
)
conn.commit()
cur.close()
conn.close()
return jsonify({"success": True})
except Exception as e:
return jsonify({"error": str(e)}), 500


@app.route("/api/intelligence/daily")
@require_auth
def get_daily_intelligence(user):
try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute(
"SELECT * FROM daily_intelligence WHERE user_id=%s AND date=CURRENT_DATE ORDER BY id DESC LIMIT 1",
(user["id"],)
)
intel = cur.fetchone()
cur.close()
conn.close()
if intel:
return jsonify({"briefing": intel["briefing"], "fresh": True})
return jsonify({"briefing": None, "fresh": False})
except Exception as e:
return jsonify({"briefing": None, "fresh": False})


@app.route("/api/intelligence/generate", methods=["POST"])
@require_auth
def generate_intelligence(user):
profile = get_profile(user["id"])
product = profile.get("product", "")
industry = profile.get("industry", "")
location = profile.get("location", "India")

search_queries = {
"market_news": (f"{industry} {product} market news {location} 2025", "news"),
"reddit_industry": (f"{product} {industry} {location} discussion reddit", "reddit_native"),
"linkedin_news": (f"{industry} startup {location} 2025", "linkedin"),
"trends": (f"{industry} {location} trends opportunity 2025", "search"),
"competitor_moves": (f"{industry} startup {location} funding news 2025", "news"),
}
all_results = multi_search(search_queries)
web_data, total = format_search_results(all_results)

days_journey = get_days_on_journey(user)

try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute(
"SELECT COUNT(*) as cnt FROM tasks WHERE user_id=%s AND done=1 AND date>=CURRENT_DATE - INTERVAL '7 days'",
(user["id"],)
)
tasks_done_week = cur.fetchone()["cnt"]
cur.close()
conn.close()
except:
tasks_done_week = 0

now = datetime.now()
prompt = f"""
Generate a morning intelligence briefing for this founder.

{build_deep_context(user, profile)}

Today: {now.strftime('%A, %B %d, %Y')}
Day {days_journey} of their journey
Tasks completed this week: {tasks_done_week}

Live data from Reddit, LinkedIn, Google News, and market sources ({total} sources found):
{web_data if web_data else 'Limited data available today for this market'}

Write a morning briefing as natural flowing paragraphs. No section headers. No bullet points. No lists.

Write as if you are a co-founder who worked through the night researching their market and is now briefing them over coffee. Cover what happened in their market overnight based only on real data found, what the current sentiment is on Reddit and LinkedIn about their industry, one signal that validates or challenges their current direction, today's single most important action with specific reasoning, and one honest observation about their execution pattern this week based on their task data.

Maximum 280 words. Human. Specific. Reference real things found in the research data. If limited data was found say so honestly.
"""

briefing = ask_groq(prompt, max_tokens=500)

try:
conn = get_db()
cur = conn.cursor()
cur.execute(
"INSERT INTO daily_intelligence (user_id, briefing, market_data) VALUES (%s,%s,%s)",
(user["id"], briefing, web_data)
)
conn.commit()
cur.close()
conn.close()
except Exception as e:
print(f"Intelligence save error: {e}")

return jsonify({"briefing": briefing, "sources": total, "success": True})


@app.route("/api/market/research", methods=["POST"])
@require_auth
def market_research(user):
profile = get_profile(user["id"])
data = request.json
custom_query = data.get("query", "")
product = profile.get("product", "")
industry = profile.get("industry", "")
location = profile.get("location", "India")
query = custom_query if custom_query else f"{product} {industry}"

search_queries = {
"google_demand": (f"{query} market demand {location} 2025", "search"),
"market_size": (f"{query} market size India global statistics 2025", "search"),
"reddit_consumers": (f"{query} reddit consumer discussion complaints wishes", "reddit_native"),
"linkedin_posts": (f"{query} {location} market opportunity 2025", "linkedin"),
"quora_demand": (f"{query} India market", "quora"),
"news": (f"{query} industry news {location} 2025", "news"),
"global_trends": (f"{query} global market trend 2025", "search"),
}

all_results = multi_search(search_queries)
web_data, total = format_search_results(all_results)

if total == 0:
return jsonify({
"analysis": f"No data found for '{query}' in {location}. Try a more specific product term or different market. The search returned zero relevant results from Google, Reddit, LinkedIn, and News.",
"sources_count": 0,
"success": True
})

prompt = f"""
You are a market intelligence analyst. Generate a market research report based ONLY on the real data below.
Never invent statistics. If specific data was not found say so clearly.

Founder Context:
{build_deep_context(user, profile)}

Real Research Data from Google, Reddit, LinkedIn, Quora, and News ({total} sources):
{web_data}

Write a market intelligence report covering these areas. For each area only include what was actually found in the research data:

WHAT REDDIT IS SAYING
Actual sentiments, complaints, and wishes from Reddit discussions about this product or industry. Quote specific types of comments found. If Reddit data was not found say so.

WHAT LINKEDIN IS SHOWING
Professional discussions, market signals, and industry commentary found on LinkedIn. If not found say so.

DEMAND SIGNALS
Real indicators of demand found across all platforms. Is demand growing, flat, or declining based on discussion volume and sentiment.

MARKET SIZE
Only include market size figures if they were actually found in the research data. Otherwise say estimate not available from current research.

REAL OPPORTUNITIES
3 specific opportunities based on gaps and complaints found in the actual research data. Each one must reference where the signal came from.

HONEST THREATS
2 real challenges or threats visible in the research data.

Write in clear flowing paragraphs. Reference where each insight came from. Maximum 500 words.
"""

analysis = ask_groq(prompt, max_tokens=900)
return jsonify({
"analysis": analysis,
"sources_count": total,
"success": True
})


@app.route("/api/competitors/analyse", methods=["POST"])
@require_auth
def competitor_analysis(user):
profile = get_profile(user["id"])
data = request.json
competitor_names = data.get("competitors", "")
location = data.get("location", profile.get("location", "India"))
product = profile.get("product", "")
industry = profile.get("industry", "")
startup_name = profile.get("startup_name", "")

search_queries = {
"local_startups": (f"{product} {industry} startup brand {location} 2025", "search"),
"local_d2c": (f"{product} {industry} D2C brand India online 2025", "search"),
"specific": (f"{competitor_names} {location} brand review", "search") if competitor_names else (f"small {industry} brand {location} 2025", "search"),
"reddit_compare": (f"{product} {industry} brand comparison reddit India", "reddit_native"),
"instagram_brands": (f"{product} {industry} Instagram brand India 2025", "search"),
"complaints": (f"{competitor_names or product} {location} customer complaint review problem", "search"),
"news": (f"{industry} startup India funding 2025", "news"),
}

all_results = multi_search(search_queries)
web_data, total = format_search_results(all_results)

if total == 0:
return jsonify({
"analysis": f"No competitor data found for this search. Try entering specific competitor names you already know of in the box above for better results.",
"sources_count": 0,
"success": True
})

prompt = f"""
You are a competitive intelligence expert who specialises in the {location} market, specifically in the {industry} industry.

Founder Context:
{build_deep_context(user, profile)}

The founder is building: {product} in {location}
Startup name: {startup_name}

CRITICAL INSTRUCTION: This founder is an early stage startup. Show them competitors they would ACTUALLY compete with — small brands, D2C startups, Instagram businesses, local producers in {location}. Do NOT list Pepsi, Coca Cola, Nestle, Paper Boat or any giant national or global brand unless the founder specifically asked about them. A new founder cannot compete with those. Focus on the realistic competitive landscape.

Real Research Data ({total} sources from Google, Reddit, Instagram searches, News):
{web_data}

Write competitor analysis in this structure:

LOCAL AND REGIONAL COMPETITORS IN {location.upper()}
Based only on what was found in research, name 3-5 real small brands, D2C startups, or local businesses in {location} competing in the same space as {product}. For each one found:
Name and where they sell (Instagram, website, offline, quick commerce)
What they actually sell and approximate price range in rupees
Their visible strength
Their biggest weakness based on customer complaints or reviews found

If specific competitor data was not found in research say: "Limited local competitor data found. Based on industry knowledge these are likely competitors to research further." Then suggest 2-3 types of competitors to manually search for.

ONLINE AND INSTAGRAM COMPETITORS
D2C brands, Instagram businesses, and quick commerce sellers found in research doing similar things.

WHERE ALL LOCAL COMPETITORS ARE WEAK
Based on real customer complaints and Reddit discussions found — what are customers frustrated about that {product} could solve better.

YOUR POSITIONING AGAINST LOCAL COMPETITION
Specific positioning strategy for {startup_name} against these local competitors. Based on their current stage, budget, and strengths. Not generic advice.

30 DAY PLAN TO GET AHEAD OF LOCAL COMPETITION
3 specific moves. Each must name a real platform, community, or distribution channel in {location}.

Never invent competitor names or details. Only cite what was found in research.
"""

analysis = ask_groq(prompt, max_tokens=1200)
return jsonify({
"analysis": analysis,
"sources_count": total,
"location": location,
"success": True
})


@app.route("/api/content/generate", methods=["POST"])
@require_auth
def generate_content(user):
profile = get_profile(user["id"])
data = request.json
platform = data.get("platform", "linkedin")
days = data.get("days", 7)
location = profile.get("location", "India")

search_results = serper_search(
f"{profile.get('product', '')} {profile.get('industry', '')} trending {platform} {location} 2025",
num=6
)
trends = "\n".join([
f"- {r.get('title', '')}: {r.get('snippet', '')}"
for r in search_results if r.get('snippet')
])

prompt = f"""
{build_deep_context(user, profile)}

Current trends on {platform} in {location}:
{trends if trends else 'Limited trend data available'}

Generate a {days}-day content calendar for {platform} targeting {location} audience.

For each day write:
Day [number] — [best posting time for {location} IST]
Content Type: [educational, founder story, product showcase, data insight, behind the scenes, or customer problem]
Full Caption: [Write the complete ready-to-post caption. Real words specific to {profile.get('product', '')}. Not a template. Conversational and genuine.]
Hashtags: [5 highly relevant hashtags for {location} and this industry]
Engagement Hook: [One specific question or CTA to end the post that drives comments]

Rules:
- Every post must mention {profile.get('product', '')} or the problem it solves
- Target customers in {location} specifically
- 4 value posts for every 1 promotional post
- Posts must feel like a real founder wrote them, not marketing copy
"""

calendar = ask_groq(prompt, max_tokens=2500)

try:
conn = get_db()
cur = conn.cursor()
cur.execute(
"INSERT INTO content_library (user_id, platform, content) VALUES (%s,%s,%s)",
(user["id"], platform, calendar)
)
conn.commit()
cur.close()
conn.close()
except:
pass

return jsonify({"calendar": calendar, "platform": platform, "success": True})


@app.route("/api/discover/ideas", methods=["POST"])
@require_auth
def discover_ideas(user):
profile = get_profile(user["id"])
data = request.json
interests = data.get("interests", "")
location = profile.get("location", "India")

search_queries = {
"reddit_problems": (f"problems people face {location} {interests} 2025 reddit", "reddit_native"),
"reddit_wishes": (f"I wish someone built {interests} {location} reddit", "reddit_native"),
"trending_india": (f"trending startup opportunity {interests} {location} 2025", "search"),
"demand_signals": (f"people looking for {interests} solution India 2025", "search"),
"news_gaps": (f"gap in market {interests} {location} opportunity 2025", "news"),
"linkedin_discuss": (f"startup opportunity {interests} India 2025", "linkedin"),
"quora_problems": (f"{interests} problem India people struggling", "quora"),
}

all_results = multi_search(search_queries)
web_data, total = format_search_results(all_results)

prompt = f"""
You are a market opportunity analyst specialising in finding real startup gaps.

Founder Location: {location}
Interests or Skills: {interests}

Real Research Data from Reddit, LinkedIn, Quora, Google, and News ({total} sources):
{web_data}

Find 5 real startup opportunities based ONLY on what people are actually discussing, complaining about, and asking for in the research data above.

For each opportunity write:

OPPORTUNITY [number]: [Name of the opportunity]
The Gap: What specific problem or unmet need was found in the research data
Real Evidence: What specific type of complaints or requests appeared in Reddit, Quora, or LinkedIn discussions
Demand Signal: Is this problem discussed by many people or a small niche — be honest about the volume
Who Would Pay: Specific type of person in {location} who would buy a solution
Simple First Version: What could be built or tested in 30 days with minimal money
Why {location}: Why this opportunity is specifically good for {location} market right now
Rough Market Size: Only if found in research data, otherwise say size unknown

Only include opportunities with real evidence from the research data. If the data was limited for some opportunities say so and explain what additional research the founder should do.

Be honest. A real opportunity backed by weak data is worth less than admitting the data was not conclusive.
"""

ideas = ask_groq(prompt, max_tokens=2000)
return jsonify({"ideas": ideas, "sources": total, "success": True})


@app.route("/api/reports/generate", methods=["POST"])
@require_auth
def generate_report(user):
profile = get_profile(user["id"])
data = request.json
report_type = data.get("type", "progress")

try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT COUNT(*) as cnt FROM tasks WHERE user_id=%s", (user["id"],))
total_tasks = cur.fetchone()["cnt"]
cur.execute("SELECT COUNT(*) as cnt FROM tasks WHERE user_id=%s AND done=1", (user["id"],))
done_tasks = cur.fetchone()["cnt"]
cur.close()
conn.close()
except:
total_tasks = 0
done_tasks = 0

days = get_days_on_journey(user)

prompt = f"""
Generate a {report_type} report for this founder.

{build_deep_context(user, profile)}

Execution Data:
- Days on journey: {days}
- Total tasks assigned: {total_tasks}
- Tasks completed: {done_tasks}
- Completion rate: {round(done_tasks/max(total_tasks,1)*100)}%

Write an honest {report_type} report covering:
- Where the founder genuinely is right now — not sugarcoated
- What they have actually accomplished based on the data
- What the execution numbers say about their pace and consistency
- The one behaviour pattern that is most helping or hurting them
- Top 3 priorities for the next 30 days with specific reasoning

Write as a real co-founder would write an honest progress memo. Professional, specific, honest. Reference their actual product and market throughout. Maximum 600 words.
"""

report_content = ask_groq(prompt, max_tokens=900)
title = f"{report_type.title()} Report — {datetime.now().strftime('%B %d, %Y')}"

try:
conn = get_db()
cur = conn.cursor()
cur.execute(
"INSERT INTO saved_reports (user_id, title, content, report_type) VALUES (%s,%s,%s,%s)",
(user["id"], title, report_content, report_type)
)
conn.commit()
cur.close()
conn.close()
except Exception as e:
print(f"Report save error: {e}")

return jsonify({"report": report_content, "title": title, "success": True})


@app.route("/api/reports/saved")
@require_auth
def get_saved_reports(user):
try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute(
"SELECT id, title, report_type, created_at FROM saved_reports WHERE user_id=%s ORDER BY id DESC LIMIT 10",
(user["id"],)
)
reports = cur.fetchall()
cur.close()
conn.close()
return jsonify({"reports": [dict(r) for r in reports]})
except Exception as e:
return jsonify({"reports": []})


@app.route("/api/agent/<agent_type>", methods=["POST"])
@require_auth
def specialist_agent(user, agent_type):
data = request.json
question = data.get("question", "")
profile = get_profile(user["id"])
context = build_deep_context(user, profile)
location = profile.get("location", "India")

agent_systems = {
"legal": f"You are a senior startup lawyer with deep expertise in {location} law including Companies Act, GST, FSSAI, SEBI, Startup India, and international expansion. Give specific actionable guidance with real form names, fees in rupees, and realistic timelines. Always note when a matter requires consulting a licensed lawyer.",
"financial": f"You are a CFO who has worked with 100 early-stage startups in {location}. Build real financial models with actual numbers. Name specific platforms like Razorpay, Stripe, QuickBooks, Tally. Calculate unit economics, burn rates, and runway with precision.",
"consumer": f"You are a consumer psychology expert who has studied {location} buying behaviour specifically. Give specific messaging frameworks and real examples from this market. Understand cultural nuances and price sensitivity.",
"growth": f"You are a growth strategist who has built 0-to-1 for 20 startups in {location}. Give specific growth experiments with expected outcomes. Name real communities, platforms, and distribution channels that work in {location}.",
"product": f"You are a senior product manager who has shipped products used by millions. Give specific frameworks, prioritisation methods, and build vs buy decisions with clear reasoning.",
"formulation": f"You are a certified formulation chemist for food, beverage, and consumer goods in {location}. Give actual ingredient names, proportions, FSSAI compliance requirements, approved supplier categories, and manufacturing guidance. Never give unverified safety claims.",
"sales": f"You are a sales director who has personally closed deals in {location}. Write actual scripts word for word. Give specific objection responses. Name real platforms like LinkedIn Sales Navigator, IndiaMART, Justdial, Meesho based on the product type.",
}

system = agent_systems.get(agent_type, agent_systems["legal"])

search_results = serper_search(
f"{question} {profile.get('industry', '')} {location} 2025", num=6
)
reddit_results = reddit_search(f"{question} {profile.get('industry', '')} India", limit=3)

search_context = "\n".join([
f"- {r.get('title', '')}: {r.get('snippet', '')}"
for r in search_results if r.get('snippet')
])
reddit_context = "\n".join([
f"- Reddit r/{r.get('subreddit', '')}: {r.get('title', '')} — {r.get('text', '')[:200]}"
for r in reddit_results if r.get('title')
])

prompt = f"""
{context}

Live research from Google:
{search_context if search_context else 'Limited search data for this query.'}

What people are discussing on Reddit:
{reddit_context if reddit_context else 'No relevant Reddit discussions found.'}

Founder question: {question}

Answer as the specialist expert you are. Be completely specific to their product {profile.get('product', '')} and market {location}.
If asked for a complete document like a sales pitch, contract, or legal filing — write the entire thing completely, not advice about it.
If data was not found in search say so clearly rather than inventing it.
Write in natural paragraphs. Give your reasoning. Maximum 500 words unless writing a full document.
"""

reply = ask_groq(prompt, system=system, max_tokens=900)
return jsonify({"reply": reply, "agent": agent_type, "success": True})


@app.route("/api/stats")
@require_auth
def get_stats(user):
try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT COUNT(*) as cnt FROM tasks WHERE user_id=%s AND date=CURRENT_DATE", (user["id"],))
total = cur.fetchone()["cnt"]
cur.execute("SELECT COUNT(*) as cnt FROM tasks WHERE user_id=%s AND date=CURRENT_DATE AND done=1", (user["id"],))
done = cur.fetchone()["cnt"]
cur.execute("SELECT COUNT(DISTINCT date) as cnt FROM tasks WHERE user_id=%s AND done=1 AND date>=CURRENT_DATE - INTERVAL '30 days'", (user["id"],))
streak = cur.fetchone()["cnt"]
cur.execute("SELECT COUNT(*) as cnt FROM tasks WHERE user_id=%s AND done=1 AND date>=CURRENT_DATE - INTERVAL '7 days'", (user["id"],))
weekly_done = cur.fetchone()["cnt"]
cur.execute("SELECT COUNT(*) as cnt FROM tasks WHERE user_id=%s AND date>=CURRENT_DATE - INTERVAL '7 days'", (user["id"],))
weekly_total = cur.fetchone()["cnt"]
cur.execute("SELECT COUNT(*) as cnt FROM tasks WHERE user_id=%s", (user["id"],))
total_ever = cur.fetchone()["cnt"]
cur.execute("SELECT COUNT(*) as cnt FROM tasks WHERE user_id=%s AND done=1", (user["id"],))
done_ever = cur.fetchone()["cnt"]
cur.close()
conn.close()
except Exception as e:
print(f"Stats error: {e}")
return jsonify({
"tasks_total": 0, "tasks_done": 0, "streak_days": 0,
"days_journey": 0, "weekly_done": 0, "weekly_total": 0,
"total_ever": 0, "done_ever": 0, "completion_rate": 0,
"has_tasks": False
})

days_journey = get_days_on_journey(user)

return jsonify({
"tasks_total": total,
"tasks_done": done,
"streak_days": streak,
"days_journey": days_journey,
"weekly_done": weekly_done,
"weekly_total": weekly_total,
"total_ever": total_ever,
"done_ever": done_ever,
"completion_rate": round((weekly_done / weekly_total * 100) if weekly_total > 0 else 0),
"has_tasks": total > 0
})


@app.route("/api/admin/users")
def get_all_users():
secret = request.args.get("key", "")
if secret != "founderos-admin-2024":
return jsonify({"error": "unauthorized"}), 401
try:
conn = get_db()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT name, email, created_at FROM users ORDER BY created_at DESC")
users = cur.fetchall()
cur.close()
conn.close()
return jsonify({"users": [dict(u) for u in users], "total": len(users)})
except Exception as e:
return jsonify({"error": str(e)}), 500


@app.route("/api/status")
def api_status():
return jsonify({
"status": "running",
"time": datetime.now().strftime("%I:%M %p"),
"version": "3.0",
"db": "postgresql"
})


@app.route("/")
def home():
try:
return open("dashboard.html", encoding="utf-8").read()
except:
return "<h1>FounderOS v3</h1><p>dashboard.html not found</p>"


setup_db()

if __name__ == "__main__":
port = int(os.environ.get("PORT", 5000))
app.run(debug=False, port=port, host="0.0.0.0")
