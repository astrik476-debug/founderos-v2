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

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "founderos-secret-2024")
CORS(app, supports_credentials=True)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
JWT_SECRET = "founderos-jwt-secret-2024"

client_gemini = genai.Client(api_key=GEMINI_API_KEY)
client_groq = Groq(api_key=GROQ_API_KEY)

password_reset_tokens = {}


def get_db():
    conn = psycopg2.connect(
        DATABASE_URL,
        sslmode='require',
        connect_timeout=30,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5
    )
    return conn


def q(conn, sql, params=()):
    sql = sql.replace("?", "%s")
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    sql = sql.replace("TEXT DEFAULT (datetime('now'))", "TIMESTAMP DEFAULT NOW()")
    sql = sql.replace("TEXT DEFAULT (date('now'))", "DATE DEFAULT CURRENT_DATE")
    sql = sql.replace("datetime('now')", "NOW()")
    sql = sql.replace("date('now')", "CURRENT_DATE")
    sql = sql.replace("date('now','-1 day')", "CURRENT_DATE - INTERVAL '1 day'")
    sql = sql.replace("date('now','-7 days')", "CURRENT_DATE - INTERVAL '7 days'")
    sql = sql.replace("date('now','-30 days')", "CURRENT_DATE - INTERVAL '30 days'")
    sql = sql.replace("date=date('now')", "date=CURRENT_DATE")
    sql = sql.replace("date=date('now','-1 day')", "date=CURRENT_DATE - INTERVAL '1 day'")
    sql = sql.replace("date>=date('now','-7 days')", "date>=CURRENT_DATE - INTERVAL '7 days'")
    sql = sql.replace("date>=date('now','-30 days')", "date>=CURRENT_DATE - INTERVAL '30 days'")
    sql = sql.replace("date<date('now')", "date<CURRENT_DATE")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(sql, params if params else None)
    conn.commit()
    return cur


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
                    "source": item.get("source", "")
                })
            return results
        else:
            if search_type == "reddit":
                payload = {"q": f"site:reddit.com {query}", "num": num}
            elif search_type == "linkedin":
                payload = {"q": f"site:linkedin.com {query}", "num": num}
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


def reddit_search(query, limit=5):
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
                "text": p.get("selftext", "")[:400],
                "subreddit": p.get("subreddit", ""),
                "score": p.get("score", 0)
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
            for item in items[:3]:
                if isinstance(item, dict):
                    text = item.get("snippet") or item.get("text") or item.get("title", "")
                    if text:
                        formatted += f"- {text[:250]}\n"
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


def build_deep_context(user, profile):
    if not profile:
        return f"Founder: {user.get('name', 'Founder')}. Profile not yet complete."

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

    behaviour = get_behaviour(user["id"])
    avg_completion = 0
    if behaviour:
        completions = [
            b["tasks_completed"] / max(b["tasks_assigned"], 1) * 100
            for b in behaviour if b.get("tasks_assigned", 0) > 0
        ]
        if completions:
            avg_completion = sum(completions) / len(completions)

    return f"""
DEEP FOUNDER CONTEXT:

Identity:
- Name: {user.get('name', 'Founder')}
- Location: {profile.get('location', 'India')}
- Journey: Day {days} since starting

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

Strengths: {profile.get('strengths', 'Not analyzed')}
Weaknesses: {profile.get('weaknesses', 'Not analyzed')}
Productivity Pattern: {profile.get('productivity_pattern', 'Not analyzed')}

Behaviour (Last 7 days):
- Average Task Completion: {avg_completion:.0f}%
- Consistency: {'Strong' if avg_completion > 70 else 'Building' if avg_completion > 40 else 'Needs work'}

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
        print(f"Reset link for {email}: {reset_link}")
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
Analyze this founder profile from their onboarding answers and generate a Founder Intelligence Report.

Answers:
{json.dumps(answers, indent=2)}

Return ONLY valid JSON in this exact format. No markdown. No extra text:
{{
  "archetype": "Specific 3-5 word founder archetype",
  "personality_type": "Detailed personality in 2 sentences",
  "decision_style": "analytical or intuitive or consultative or decisive",
  "execution_style": "systematic or agile or opportunistic or methodical",
  "risk_profile": "conservative or moderate or aggressive or calculated",
  "growth_mindset_score": 7,
  "focus_score": 6,
  "productivity_pattern": "When and how they work best based on answers",
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

    if not is_greeting and len(message) > 15:
        industry = profile.get("industry", "")
        location = profile.get("location", "India")
        search_queries = {
            "google": (f"{message} {industry} {location} 2025", "search"),
            "news": (f"{message} {industry} latest 2025", "news"),
            "reddit": (f"{message} {industry} founder", "reddit_native"),
        }
        all_results = multi_search(search_queries)
        web_context, web_total = format_search_results(all_results)

    personality = profile.get("ai_personality", "mentor")
    personality_map = {
        "tough-love": "Be direct and challenging. Push back on weak thinking. No excuses.",
        "encouraging": "Be warm and supportive. Celebrate every step. Still honest.",
        "analytical": "Lead with data. Use numbers and frameworks. Be structured.",
        "challenger": "Question every assumption. Force deeper thinking.",
        "mentor": "Be wise and balanced. Guide through questions as much as answers."
    }

   system = f"""You are the AI Co-Founder of FounderOS. You have been working alongside this founder since day one and know their business deeply.

{context}

YOUR PERSONALITY AND COMMUNICATION STYLE:
- You speak like a brilliant co-founder who has built companies before and genuinely cares about this founder's success
- You never give textbook advice or generic startup platitudes
- Every response references their specific product, market, location, and stage
- You write in flowing natural paragraphs — never robotic bullet lists as your primary format
- You give reasoning behind every recommendation
- You are honest even when it is uncomfortable — if their idea has a flaw you say so with care
- You remember everything about their journey and reference it naturally
- You never start with Certainly, Great, Absolutely, Sure, or any filler word
- For greetings — warm, personal, under 3 sentences, ask one sharp question
- For business questions — structured paragraphs with clear logic, specific examples, actionable next steps
- For emotional moments like wanting to quit — acknowledge the feeling fully first, then ground them in their specific progress data, then give one small action

WHAT MAKES YOUR ADVICE DIFFERENT FROM CHATGPT:
- ChatGPT gives advice for any founder anywhere. You give advice for THIS founder with THIS product in THIS market.
- You know their archetype, their fears, their skill gaps, their avoidance patterns
- You reference real data from live research — not generic statistics
- You push back when they are avoiding hard things
- You celebrate real progress, not just activity

Personality mode: {personality}
{personality_map.get(personality, '')}

CRITICAL RULES:
- Always reference {profile.get('product', 'their product')} and {profile.get('location', 'India')} specifically
- For sales pitches — write the complete pitch word for word, not advice about what to include
- For competitor questions — name real LOCAL competitors first, not global giants
- For market research — cite what you actually found in research, say clearly when data was not found
- For idea generation — search real platforms like Reddit, LinkedIn, and news to find real demand signals
- Keep responses under 400 words unless writing a complete document
- If they have no idea yet — help them discover opportunities from real market demand signals"""

    history_text = "\n".join([
        f"{h['role'].upper()}: {h['content']}" for h in history[-8:]
    ])

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

    if is_greeting:
        full_prompt = f"""
Conversation so far:
{history_text}

{user.get('name', 'Founder')} just said: {message}

Respond warmly and naturally. You know them well.
Mention Day {days} of their journey if it feels natural.
Reference their startup {profile.get('startup_name', '')} or stage {profile.get('stage', '')}.
Ask one genuinely curious question about what they are working on right now.
Under 80 words. Human. Warm. No lists.
"""
        reply = ask_groq(full_prompt, system=system, max_tokens=180)
    else:
        data_note = f"\n\nLive research data ({web_total} sources):\n{web_context}" if web_context else "\n\nNote: Real-time search data limited for this query."
        full_prompt = f"""
Previous conversation:
{history_text}
{data_note}

{user.get('name', 'Founder')} asks: {message}

Respond as their co-founder. Specific to their product {profile.get('product', '')} in {profile.get('location', 'India')}.
Mode: {mode}
"""
        use_deep = mode in ["deep", "plan"]
        reply = ask_groq(
            full_prompt, system=system,
            max_tokens=1000 if use_deep else 600,
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

    avoidance_note = f"Tasks the founder has been avoiding: {', '.join(avoided)}" if avoided else ""

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

Return ONLY a valid JSON array. No markdown. No other text:
[
  {{
    "title": "Specific task title mentioning their product or market",
    "description": "2 sentences explaining exactly what to do and why it matters for their specific startup right now.",
    "how_to": "Step 1: Specific action with exact tool or platform. Step 2: Specific action. Step 3: Specific action. Step 4: How to measure success.",
    "category": "one of: revenue, validation, marketing, product, operations, research",
    "priority": "one of: critical, high, medium",
    "time_est": "realistic time estimate",
    "outcome": "Exactly what success looks like when done well"
  }}
]

Rules:
- First 2 tasks must relate to revenue or customer validation
- At least one task must address an avoided pattern or weakness
- Every how_to must have 4 specific steps with real platform names
- Never generate generic tasks — every task must be about their specific startup
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
            "title": f"Talk to 3 potential customers about {profile.get('product', 'your product')}",
            "description": f"Contact 3 real people who could be your first customers in {location}. Have a conversation, not a sales pitch.",
            "how_to": "Step 1: Open LinkedIn and search for people matching your target customer in your city. Step 2: Send a connection request with a personal note. Step 3: When they accept ask one specific question about the problem your product solves. Step 4: Note exactly what words they use to describe the problem.",
            "category": "validation",
            "priority": "critical",
            "time_est": "2 hours",
            "outcome": "3 real conversations with notes on whether the problem is real for them"
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
        cur.execute(
            "INSERT INTO behaviour_log (user_id, date, tasks_assigned, tasks_avoided) VALUES (%s, CURRENT_DATE, %s, %s) ON CONFLICT DO NOTHING",
            (user["id"], len(tasks), json.dumps(avoided))
        )
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
        cur.execute(
            "UPDATE behaviour_log SET tasks_completed=tasks_completed+1 WHERE user_id=%s AND date=CURRENT_DATE",
            (user["id"],)
        )
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
        "trends": (f"{industry} {location} trends 2025", "search"),
        "reddit": (f"{product} {industry} discussion reddit", "reddit_native"),
        "competitor_news": (f"{industry} startup {location} news 2025", "news"),
    }
    all_results = multi_search(search_queries)
    web_data, total = format_search_results(all_results)

    days_journey = 0
    try:
        start = user.get("journey_start")
        if start:
            if isinstance(start, str):
                start = datetime.strptime(start, "%Y-%m-%d")
            elif hasattr(start, 'year'):
                start = datetime(start.year, start.month, start.day)
            days_journey = (datetime.now() - start).days
    except:
        pass

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

Live market data ({total} sources):
{web_data if web_data else 'Limited data available today'}

Write a morning briefing as flowing paragraphs. No section headers. No bullet points.
Feel like a real co-founder who worked all night and is now briefing them.
Cover: personalised good morning referencing their journey, what happened in their market overnight based only on real data found, today's market pulse for their product, one clear priority for today, one observation about their execution pattern this week.
Maximum 300 words. Human. Specific. No waffle.
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
        "demand": (f"{query} market demand {location} 2025", "search"),
        "size": (f"{query} market size statistics", "search"),
        "reddit": (f"{query} consumer discussion reddit", "reddit_native"),
        "news": (f"{query} industry news 2025", "news"),
        "platforms": (f"{query} social media platform {location}", "search"),
        "global": (f"{query} global market 2025", "search"),
    }

    all_results = multi_search(search_queries)
    web_data, total = format_search_results(all_results)

    if total == 0:
        return jsonify({
            "analysis": "Data not available for this specific query. The search did not return relevant results. Try a more specific product or market term.",
            "sources_count": 0,
            "success": True
        })

    prompt = f"""
Market intelligence report based ONLY on the data below. Never invent statistics.

{build_deep_context(user, profile)}

Research Data ({total} real sources):
{web_data}

Write analysis covering demand signals, geographic distribution, what people are saying on Reddit and news, market size if found in data otherwise say estimate unavailable, 3 real opportunities, 2 real threats. Reference actual sources found. Be honest about what data was and was not available. Write in flowing paragraphs. Maximum 400 words.
"""

    analysis = ask_groq(prompt, max_tokens=800)
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

    search_queries = {
        "local": (f"top {industry} {product} companies {location} 2025", "search"),
        "global": (f"top {industry} {product} companies global 2025", "search"),
        "specific": (f"{competitor_names} company overview", "search") if competitor_names else (f"{industry} startups {location} 2025", "search"),
        "reddit": (f"{product} {industry} alternative comparison reddit", "reddit_native"),
        "news": (f"{competitor_names or industry} startup news 2025", "news"),
        "reviews": (f"{competitor_names or product} {location} reviews problems", "search"),
    }

    all_results = multi_search(search_queries)
    web_data, total = format_search_results(all_results)

    if total == 0:
        return jsonify({
            "analysis": "Data not available. The search did not return competitor information. Try entering specific competitor names.",
            "sources_count": 0,
            "success": True
        })

   prompt = f"""
You are a competitive intelligence expert who specialises deeply in {location} market specifically.

Founder Context:
{build_deep_context(user, profile)}

IMPORTANT INSTRUCTION: This founder is building {product} in {location}. They want to know about competitors specifically in {location} — NOT global giants like Pepsi, Coca Cola, or Paper Boat unless they are specifically operating in the same niche and price range in {location}.

Research Data ({total} sources):
{web_data}

Write competitor analysis in this exact structure:

LOCAL COMPETITORS IN {location.upper()} — SAME NICHE AS {product.upper()}
Find 3-5 real local or regional competitors operating in {location} that are in the same product category and price range as {profile.get('product','')}. For each one:
- Company name and where they sell
- What their product actually is and their price range in rupees
- Their strongest advantage
- Their biggest weakness based on customer feedback

DO NOT include Pepsi, Coca Cola, Paper Boat, or any giant national brands unless {profile.get('startup_name','')} is directly competing with them at scale. Focus on startups and small brands in {location} that a new founder would actually compete with.

ONLINE COMPETITORS
Brands selling similar products online in India — D2C brands, Instagram brands, quick commerce brands.

WHERE THEY ARE ALL WEAK
Based on real customer complaints found in research — what are customers frustrated about that {profile.get('product','')} could solve better.

YOUR POSITIONING TO WIN {location.upper()}
Specific positioning strategy against these local competitors. Specific to {profile.get('product','')} at their current stage and budget.

FIRST 30 DAYS TO BEAT LOCAL COMPETITION
3 specific moves to gain advantage over local competitors. Name real platforms, communities, and distribution channels in {location}.

Be specific. Name real local brands. Never pad the list with giants the founder cannot compete with.
"""

    analysis = ask_groq(prompt, max_tokens=1000)
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
        num=5
    )
    trends = "\n".join([f"- {r.get('snippet', '')}" for r in search_results if r.get('snippet')])

    prompt = f"""
{build_deep_context(user, profile)}

Trends on {platform} in {location}:
{trends if trends else 'Limited trend data'}

Generate a {days}-day content calendar for {platform} targeting {location}.

For each day:
Day [number] — [best posting time for {location}]
Type: [content type]
Caption: [Complete ready-to-post caption for {profile.get('product', '')}. Real words. Not a template.]
Hashtags: [5 relevant hashtags]
Hook: [Opening line to stop the scroll]
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

    prompt = f"""
Generate a {report_type} report for this founder.

{build_deep_context(user, profile)}

Data:
- Days on journey: {days}
- Total tasks assigned: {total_tasks}
- Completed: {done_tasks}
- Completion rate: {round(done_tasks/max(total_tasks,1)*100)}%

Write an honest {report_type} report covering where the founder is right now, what they have accomplished, what the execution data says, what needs to change, and top 3 priorities for next 30 days. Write as a real co-founder would. Professional, honest, specific. Maximum 600 words.
"""

    report_content = ask_groq(prompt, max_tokens=800)
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
        "legal": f"You are a senior startup lawyer specialising in {location} law including Companies Act, GST, FSSAI, SEBI, Startup India. Give specific guidance with real form names, fees, and timelines. Note when a matter requires a licensed lawyer.",
        "financial": f"You are a CFO for early-stage startups in {location}. Build real models with actual numbers. Name specific platforms. Calculate unit economics precisely.",
        "consumer": f"You are a consumer psychology expert who has studied {location} buying behaviour. Give specific messaging frameworks and real examples from this market.",
        "growth": f"You are a growth strategist who has built 0-to-1 for 20 startups in {location}. Give specific experiments with expected outcomes and real community names.",
        "product": f"You are a senior product manager. Give specific frameworks, prioritisation methods, and build vs buy decisions with clear reasoning.",
        "formulation": f"You are a certified formulation chemist for food, beverage, and cosmetics for the {location} market. Give actual ingredient names, proportions, FSSAI regulations, and manufacturing guidance. Never give unverified safety claims.",
        "sales": f"You are a sales director who has closed deals in {location}. Write actual scripts word for word. Give specific objection responses. Name real platforms relevant to this market.",
    }

    system = agent_systems.get(agent_type, agent_systems["legal"])
    search_results = serper_search(
        f"{question} {profile.get('industry', '')} {location}", num=6
    )
    search_context = "\n".join([
        f"- {r.get('snippet', '')}" for r in search_results if r.get('snippet')
    ])

    prompt = f"""
{context}

Live research:
{search_context if search_context else 'Limited search data for this query.'}

Question: {question}

Answer as the specialist you are. Be specific to their product and market.
If asked for a complete document — write the entire thing, not advice about it.
If data was not found in search say so clearly.
Write in natural paragraphs. Give reasoning. Maximum 500 words unless writing a full document.
"""

    reply = ask_groq(prompt, system=system, max_tokens=800)
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

    days_journey = 0
    try:
        start = user.get("journey_start")
        if start:
            if isinstance(start, str):
                start = datetime.strptime(start, "%Y-%m-%d")
            elif hasattr(start, 'year'):
                start = datetime(start.year, start.month, start.day)
            days_journey = (datetime.now() - start).days
    except:
        pass

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

@app.route("/api/discover/ideas", methods=["POST"])
@require_auth
def discover_ideas(user):
    profile = get_profile(user["id"])
    data = request.json
    interests = data.get("interests", "")
    location = profile.get("location", "India")

    search_queries = {
        "reddit_problems": (f"problems people face {location} {interests} reddit 2025", "reddit_native"),
        "reddit_gaps": (f"I wish someone made {interests} {location} reddit", "reddit_native"),
        "trending": (f"trending startup ideas {location} {interests} 2025", "search"),
        "demand": (f"people looking for {interests} solution {location}", "search"),
        "news": (f"gap in market {interests} {location} opportunity 2025", "news"),
        "linkedin": (f"startup opportunity {interests} {location} 2025", "linkedin"),
    }

    all_results = multi_search(search_queries)
    web_data, total = format_search_results(all_results)

    prompt = f"""
You are a market opportunity analyst. Based on REAL data from Reddit, LinkedIn, and news below, identify genuine startup opportunities.

Location: {location}
Interests/Skills: {interests}
Real Research Data ({total} sources found):
{web_data}

Find 5 real startup opportunities based ONLY on what people are actually discussing and complaining about in the research data. For each opportunity:

OPPORTUNITY NAME
What the gap is — based on real discussions found
Evidence — quote the type of complaints or requests found in research
Market size signal — is this a small niche or large market based on discussion volume
Who would pay — specific type of customer
Simple first version — what could be built in 30 days to test this
Why {location} specifically — local angle

Only include opportunities that have real evidence in the research data. If data is limited say so honestly and suggest better search terms.
"""

    ideas = ask_groq(prompt, max_tokens=1500)
    return jsonify({"ideas": ideas, "sources": total, "success": True})
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
