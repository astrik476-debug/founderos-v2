from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3, threading, requests, json, re, os
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from groq import Groq
import jwt
import bcrypt

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "founderos-secret-2024")
CORS(app, supports_credentials=True)

DB = "founderos.db"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
JWT_SECRET = "founderos-jwt-secret-2024"

client_gemini = genai.Client(api_key=GEMINI_API_KEY)
client_groq = Groq(api_key=GROQ_API_KEY)


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


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def setup_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            onboarding_done INTEGER DEFAULT 0,
            journey_start TEXT DEFAULT (date('now'))
        );

        CREATE TABLE IF NOT EXISTS founder_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            started_at TEXT,
            completed_at TEXT,
            time_taken INTEGER DEFAULT 0,
            verified INTEGER DEFAULT 0,
            date TEXT DEFAULT (date('now'))
        );

        CREATE TABLE IF NOT EXISTS behaviour_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT DEFAULT (date('now')),
            tasks_assigned INTEGER DEFAULT 0,
            tasks_completed INTEGER DEFAULT 0,
            tasks_avoided TEXT,
            session_count INTEGER DEFAULT 0,
            ai_interactions INTEGER DEFAULT 0,
            patterns TEXT,
            insight TEXT
        );

        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS daily_intelligence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT DEFAULT (date('now')),
            market_data TEXT,
            competitor_data TEXT,
            briefing TEXT,
            opportunities TEXT,
            generated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS saved_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            content TEXT,
            report_type TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS content_library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            platform TEXT,
            content TEXT,
            status TEXT DEFAULT 'draft',
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


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
            conn = get_db()
            user = conn.execute(
                "SELECT * FROM users WHERE id=?", (user_id,)
            ).fetchone()
            conn.close()
            return dict(user) if user else None
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
                "score": p.get("score", 0),
                "url": f"https://reddit.com{p.get('permalink', '')}"
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
    conn = get_db()
    profile = conn.execute(
        "SELECT * FROM founder_profiles WHERE user_id=?", (user_id,)
    ).fetchone()
    conn.close()
    return dict(profile) if profile else {}


def get_behaviour(user_id):
    conn = get_db()
    logs = conn.execute(
        "SELECT * FROM behaviour_log WHERE user_id=? ORDER BY date DESC LIMIT 7",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(l) for l in logs]


def build_deep_context(user, profile):
    if not profile:
        return f"Founder: {user.get('name', 'Founder')}. Profile not yet complete."

    days = 0
    try:
        start = datetime.strptime(
            user.get("journey_start", str(datetime.now().date())), "%Y-%m-%d"
        )
        days = (datetime.now() - start).days
    except:
        pass

    behaviour = get_behaviour(user["id"])
    avg_completion = 0
    if behaviour:
        completions = [b["tasks_completed"] / max(b["tasks_assigned"], 1) * 100 for b in behaviour if b["tasks_assigned"] > 0]
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

Behaviour Data (Last 7 days):
- Average Task Completion Rate: {avg_completion:.0f}%
- AI Interaction Sessions: {sum(b.get('ai_interactions', 0) for b in behaviour)}
- Consistency Pattern: {'Strong' if avg_completion > 70 else 'Building' if avg_completion > 40 else 'Needs work'}

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
        conn.execute(
            "INSERT INTO users (email, password, name) VALUES (?,?,?)",
            (email, hashed, name)
        )
        conn.commit()
        user = conn.execute(
            "SELECT * FROM users WHERE email=?", (email,)
        ).fetchone()
        conn.close()
        token = create_token(user["id"])
        return jsonify({
            "success": True, "token": token,
            "name": name, "onboarding_done": False
        })
    except sqlite3.IntegrityError:
        return jsonify({"error": "Email already registered"}), 400


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE email=?", (email,)
    ).fetchone()
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


@app.route("/api/auth/me")
@require_auth
def get_me(user):
    return jsonify({
        "id": user["id"], "name": user["name"],
        "email": user["email"],
        "onboarding_done": bool(user["onboarding_done"]),
        "journey_start": user.get("journey_start")
    })


@app.route("/api/onboarding/submit", methods=["POST"])
@require_auth
def submit_onboarding(user):
    data = request.json
    answers = data.get("answers", {})

    prompt = f"""
You are analyzing a founder's complete onboarding profile to generate their Founder Intelligence Report.

Founder Answers:
{json.dumps(answers, indent=2)}

Generate a comprehensive Founder Intelligence Report in this EXACT JSON format. Be specific and insightful, not generic:

{{
  "archetype": "Specific 3-5 word founder archetype based on their answers",
  "personality_type": "Detailed personality description in 2 sentences",
  "decision_style": "How they make decisions - analytical/intuitive/consultative/decisive",
  "execution_style": "How they execute - systematic/agile/opportunistic/methodical",
  "risk_profile": "Risk tolerance level and behavior - conservative/moderate/aggressive/calculated",
  "growth_mindset_score": 7,
  "focus_score": 6,
  "productivity_pattern": "When and how they are most productive based on their answers",
  "strengths": ["strength 1", "strength 2", "strength 3"],
  "weaknesses": ["weakness 1", "weakness 2", "weakness 3"],
  "ai_personality": "one of: tough-love, encouraging, analytical, challenger, mentor",
  "report_summary": "A powerful 4-5 sentence summary of this founder that reads like a real human assessment. Reference their specific situation.",
  "predicted_timeline": {{
    "first_customer": "realistic timeframe",
    "first_revenue": "realistic timeframe",
    "first_10k_revenue": "realistic timeframe",
    "product_market_fit": "realistic timeframe"
  }},
  "key_insight": "The single most important thing this founder needs to understand about themselves right now",
  "biggest_risk": "The most likely way this founder will self-sabotage",
  "superpower": "The one thing about this founder that could make them unstoppable"
}}

Return ONLY valid JSON. No markdown. No extra text.
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
            "personality_type": "A focused individual who is serious about building something meaningful.",
            "decision_style": "analytical",
            "execution_style": "systematic",
            "risk_profile": "moderate",
            "growth_mindset_score": 7,
            "focus_score": 6,
            "productivity_pattern": "Most productive with structured daily routines",
            "strengths": ["Strong vision", "Determination", "Domain knowledge"],
            "weaknesses": ["Sales experience", "Marketing", "Financial planning"],
            "ai_personality": "mentor",
            "report_summary": "You are at the beginning of your founder journey with a clear vision of what you want to build. Your determination is your biggest asset right now.",
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
        "timeline": answers.get("q22_timeline", ""),
    }

    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM founder_profiles WHERE user_id=?", (user["id"],)
    ).fetchone()

    strengths_json = json.dumps(report.get("strengths", []))
    weaknesses_json = json.dumps(report.get("weaknesses", []))

    if existing:
        conn.execute("""
            UPDATE founder_profiles SET
            answers=?, personality_type=?, strengths=?, weaknesses=?,
            risk_profile=?, execution_style=?, decision_style=?,
            growth_mindset_score=?, focus_score=?, productivity_pattern=?,
            archetype=?, ai_personality=?, startup_name=?, product=?,
            industry=?, stage=?, market=?, goal=?, location=?, timeline=?,
            report_summary=?, updated_at=datetime('now')
            WHERE user_id=?
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
        conn.execute("""
            INSERT INTO founder_profiles
            (user_id, answers, personality_type, strengths, weaknesses,
            risk_profile, execution_style, decision_style, growth_mindset_score,
            focus_score, productivity_pattern, archetype, ai_personality,
            startup_name, product, industry, stage, market, goal,
            location, timeline, report_summary)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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

    conn.execute(
        "UPDATE users SET onboarding_done=1 WHERE id=?", (user["id"],)
    )
    conn.commit()
    conn.close()

    return jsonify({"success": True, "report": report})


@app.route("/api/profile/report")
@require_auth
def get_founder_report(user):
    profile = get_profile(user["id"])
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    conn = get_db()
    days = 0
    try:
        start = datetime.strptime(
            user.get("journey_start", str(datetime.now().date())), "%Y-%m-%d"
        )
        days = (datetime.now() - start).days
    except:
        pass

    total_tasks = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=?", (user["id"],)
    ).fetchone()[0]
    completed_tasks = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1", (user["id"],)
    ).fetchone()[0]
    conn.close()

    completion_rate = round(completed_tasks / max(total_tasks, 1) * 100)

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
        "completed_tasks": completed_tasks,
        "completion_rate": completion_rate,
        "startup_name": profile.get("startup_name", ""),
        "stage": profile.get("stage", ""),
        "updated_at": profile.get("updated_at", "")
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

    conn = get_db()
    history = conn.execute(
        "SELECT role, content FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT 12",
        (user["id"],)
    ).fetchall()
    conn.execute(
        "UPDATE behaviour_log SET ai_interactions = ai_interactions + 1 WHERE user_id=? AND date=date('now')",
        (user["id"],)
    )
    conn.commit()
    conn.close()
    history = list(reversed([dict(h) for h in history]))

    is_greeting = len(message.split()) <= 4 and any(
        message_lower.startswith(p) for p in [
            "hey", "hi", "hello", "good morning", "good evening",
            "thanks", "thank you", "ok", "okay", "sup", "how are"
        ]
    )

    web_context = ""
    web_total = 0

    if not is_greeting and len(message) > 15:
        industry = profile.get("industry", "")
        location = profile.get("location", "India")

        search_queries = {
            "google": (f"{message} {industry} {location} 2025", "search"),
            "news": (f"{message} {industry} latest news 2025", "news"),
            "reddit": (f"{message} {industry} founder experience", "reddit_native"),
        }

        all_results = multi_search(search_queries)
        web_context, web_total = format_search_results(all_results)

    personality = profile.get("ai_personality", "mentor")
    personality_instructions = {
        "tough-love": "Be direct, demanding, and challenging. Call out avoidance and weak thinking immediately. You believe in this founder but refuse to let them make excuses.",
        "encouraging": "Be warm, energetic, and celebrate every step forward. You genuinely believe in this founder and your enthusiasm is contagious. Still honest but always constructive.",
        "analytical": "Lead with data, frameworks, and logical structure. Give numbered steps and measurable outcomes. You think in systems and help the founder see the full picture.",
        "challenger": "Question everything. Push back on assumptions. Force the founder to think three levels deeper. Play devil's advocate when needed.",
        "mentor": "Be wise, patient, and thoughtful. Share perspective from experience. Guide through questions as much as answers. Help the founder develop their own thinking."
    }

    system = f"""You are the AI Co-Founder of FounderOS. You are not a chatbot. You are not ChatGPT. You are a deeply intelligent execution partner who has been working alongside this founder since they joined the platform.

{context}

Your communication style:
- You speak like a real co-founder who knows this person deeply. You use their name occasionally.
- You never use basic bullet points for your main responses. You write in natural, flowing paragraphs that feel human and intelligent.
- You give reasoning behind everything. Not just what to do but why, based on their specific situation.
- You reference their actual startup, product, and market in every substantive response.
- You remember what has been discussed and build on it.
- You are direct without being robotic. Warm without being generic.
- For greetings you respond conversationally in 2-3 sentences, ask one sharp question.
- For business questions you give a thorough response that feels like sitting with an expert who knows your business.
- You never start a response with "Certainly", "Great question", "Absolutely", or any filler.
- When you see avoidance patterns in their behaviour data you address them with care but honesty.

Personality mode: {personality}
{personality_instructions.get(personality, '')}

Critical rules:
- If they mention wanting to quit, you do not agree. You pull specific data about their progress and market, acknowledge the feeling as real, then give one concrete small action.
- For any industry, any product, any market — give specific intelligent answers using the research data provided.
- For sales pitches — write the complete pitch, not advice about pitches.
- For formulas or recipes — give real ingredients and proportions with safety and regulatory notes.
- For competitor questions — name real companies in their specific location first.
- If research data is not available for a specific claim, say so clearly rather than inventing data.
- Keep responses under 450 words unless writing a full document or plan."""

    history_text = "\n".join([
        f"{h['role'].upper()}: {h['content']}" for h in history[-8:]
    ])

    days = 0
    try:
        start = datetime.strptime(
            user.get("journey_start", str(datetime.now().date())), "%Y-%m-%d"
        )
        days = (datetime.now() - start).days
    except:
        pass

    if is_greeting:
        full_prompt = f"""
Conversation so far:
{history_text}

{user.get('name', 'Founder')} just said: {message}

Respond warmly and naturally. You know them well. Mention Day {days} of their journey if it feels natural.
Reference what they are building — {profile.get('startup_name', '')} — or what stage they are at.
End with one genuinely curious question about what they are working on or struggling with right now.
Keep it under 80 words. Human. Warm. No lists.
"""
        reply = ask_groq(full_prompt, system=system, max_tokens=180)
    else:
        data_note = f"\n\nLive research data ({web_total} sources found):\n{web_context}" if web_context else "\n\nNote: Real-time search data not available for this query. Responding from training knowledge."

        full_prompt = f"""
Previous conversation:
{history_text}

{data_note}

{user.get('name', 'Founder')}'s question: {message}

Respond as their deeply knowledgeable co-founder. Be specific to their actual situation.
Product: {profile.get('product', '')} | Market: {profile.get('location', 'India')} | Stage: {profile.get('stage', '')}
Mode: {mode}
"""
        use_deep = mode in ["deep", "plan"]
        reply = ask_groq(
            full_prompt, system=system,
            max_tokens=1000 if mode in ["deep", "plan"] else 600,
            deep=use_deep
        )

    conn = get_db()
    conn.execute(
        "INSERT INTO chat_history (user_id, role, content) VALUES (?,?,?)",
        (user["id"], "user", message)
    )
    conn.execute(
        "INSERT INTO chat_history (user_id, role, content) VALUES (?,?,?)",
        (user["id"], "assistant", reply)
    )
    conn.commit()
    conn.close()

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

    conn = get_db()
    completed_yesterday = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1 AND date=date('now','-1 day')",
        (user["id"],)
    ).fetchone()[0]
    total_yesterday = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND date=date('now','-1 day')",
        (user["id"],)
    ).fetchone()[0]
    avoided = conn.execute(
        "SELECT title FROM tasks WHERE user_id=? AND done=0 AND date<date('now') LIMIT 5",
        (user["id"],)
    ).fetchall()
    avoided_titles = [a["title"] for a in avoided]
    conn.close()

    avoidance_note = f"Tasks the founder has been avoiding: {', '.join(avoided_titles)}" if avoided_titles else ""

    prompt = f"""
{context}

Yesterday: completed {completed_yesterday} of {total_yesterday} tasks.
{avoidance_note}

Generate exactly 5 highly specific tasks for today. These must be completely tailored to:
- Their product: {profile.get('product', '')}
- Their industry: {profile.get('industry', '')}
- Their stage: {profile.get('stage', '')}
- Their location: {location}
- Their weaknesses: {profile.get('weaknesses', '[]')}
- Their goal: {profile.get('goal', '')}

Return ONLY a valid JSON array:
[
  {{
    "title": "Specific task title that mentions their product or market",
    "description": "2 sentences explaining exactly what to do and why it matters for their specific startup right now.",
    "how_to": "Step 1: Specific action with exact tool or platform name. Step 2: Specific action. Step 3: Specific action. Step 4: How to measure if this worked.",
    "category": "one of: revenue, validation, marketing, product, operations, research",
    "priority": "one of: critical, high, medium",
    "time_est": "realistic time estimate",
    "outcome": "Exactly what success looks like when this task is done well"
  }}
]

Rules:
- First 2 tasks must directly relate to revenue or customer validation
- At least one task must address an avoided task or weakness
- Every how_to must have 4 specific steps with real platform names
- Never generate generic tasks. Every task must be undeniably about their specific startup.
- Return ONLY the JSON array. No other text.
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
            "description": f"Contact 3 real people who could be your first customers for {profile.get('product', 'your product')} in {location}. Have a real conversation, not a sales pitch.",
            "how_to": "Step 1: Open LinkedIn and search for people matching your target customer profile in your city. Step 2: Send a connection request with a personal note explaining you are building something and want their perspective. Step 3: When they accept, ask one specific question about the problem your product solves. Step 4: Take notes on exactly what words they use to describe the problem.",
            "category": "validation",
            "priority": "critical",
            "time_est": "2 hours",
            "outcome": "3 real conversations with potential customers and notes on whether the problem is real for them"
        }]

    conn = get_db()
    conn.execute(
        "DELETE FROM tasks WHERE user_id=? AND date=date('now') AND done=0",
        (user["id"],)
    )
    for task in tasks:
        conn.execute(
            "INSERT INTO tasks (user_id, title, description, how_to, category, priority, time_est, outcome) VALUES (?,?,?,?,?,?,?,?)",
            (
                user["id"], task.get("title"), task.get("description"),
                task.get("how_to"), task.get("category"), task.get("priority"),
                task.get("time_est"), task.get("outcome", "")
            )
        )

    conn.execute("""
        INSERT INTO behaviour_log (user_id, tasks_assigned, tasks_avoided)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
        tasks_assigned = ?,
        tasks_avoided = ?
        WHERE date = date('now')
    """, (user["id"], len(tasks), json.dumps(avoided_titles),
          len(tasks), json.dumps(avoided_titles)))

    try:
        conn.execute("""
            INSERT INTO behaviour_log (user_id, date, tasks_assigned, tasks_avoided)
            SELECT ?, date('now'), ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM behaviour_log WHERE user_id=? AND date=date('now'))
        """, (user["id"], len(tasks), json.dumps(avoided_titles), user["id"]))
    except:
        pass

    conn.commit()
    conn.close()

    return jsonify({"success": True, "count": len(tasks)})


@app.route("/api/tasks")
@require_auth
def get_tasks(user):
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM tasks WHERE user_id=? AND date=date('now')
        ORDER BY CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 ELSE 3 END""",
        (user["id"],)
    ).fetchall()
    conn.close()
    return jsonify({"tasks": [dict(r) for r in rows]})


@app.route("/api/tasks/<int:task_id>/start", methods=["POST"])
@require_auth
def start_task(user, task_id):
    conn = get_db()
    conn.execute(
        "UPDATE tasks SET started_at=datetime('now') WHERE id=? AND user_id=?",
        (task_id, user["id"])
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/tasks/<int:task_id>/complete", methods=["POST"])
@require_auth
def complete_task(user, task_id):
    data = request.json or {}
    time_spent = data.get("time_spent", 0)
    conn = get_db()
    task = conn.execute(
        "SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user["id"])
    ).fetchone()
    if not task:
        conn.close()
        return jsonify({"error": "Task not found"}), 404

    if time_spent < 30 and task["priority"] in ["critical", "high"]:
        conn.close()
        return jsonify({
            "verified": False,
            "message": f"This is a {task['priority']} priority task. Have you actually completed it? Take a moment to confirm."
        })

    conn.execute(
        "UPDATE tasks SET done=1, verified=1, completed_at=datetime('now'), time_taken=? WHERE id=? AND user_id=?",
        (time_spent, task_id, user["id"])
    )
    conn.execute("""
        UPDATE behaviour_log SET tasks_completed = tasks_completed + 1
        WHERE user_id=? AND date=date('now')
    """, (user["id"],))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "verified": True})


@app.route("/api/tasks/<int:task_id>/confirm", methods=["POST"])
@require_auth
def confirm_task(user, task_id):
    conn = get_db()
    conn.execute(
        "UPDATE tasks SET done=1, verified=1, completed_at=datetime('now') WHERE id=? AND user_id=?",
        (task_id, user["id"])
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/intelligence/daily")
@require_auth
def get_daily_intelligence(user):
    profile = get_profile(user["id"])
    conn = get_db()
    intel = conn.execute(
        "SELECT * FROM daily_intelligence WHERE user_id=? AND date=date('now') ORDER BY id DESC LIMIT 1",
        (user["id"],)
    ).fetchone()
    conn.close()

    if intel:
        return jsonify({
            "briefing": intel["briefing"],
            "market_data": intel["market_data"],
            "opportunities": intel["opportunities"],
            "generated_at": intel["generated_at"],
            "fresh": True
        })

    return jsonify({
        "briefing": None,
        "fresh": False,
        "message": "Click Generate Intelligence to see today's market data"
    })


@app.route("/api/intelligence/generate", methods=["POST"])
@require_auth
def generate_intelligence(user):
    profile = get_profile(user["id"])
    product = profile.get("product", "")
    industry = profile.get("industry", "")
    location = profile.get("location", "India")

    search_queries = {
        "market_news": (f"{industry} {product} market news {location} 2025", "news"),
        "trends": (f"{industry} {location} trends opportunity 2025", "search"),
        "reddit": (f"{product} {industry} discussion reddit", "reddit_native"),
        "competitor_news": (f"{industry} startup {location} news funding 2025", "news"),
    }

    all_results = multi_search(search_queries)
    web_data, total = format_search_results(all_results)

    conn = get_db()
    days_journey = 0
    try:
        start = datetime.strptime(
            user.get("journey_start", str(datetime.now().date())), "%Y-%m-%d"
        )
        days_journey = (datetime.now() - start).days
    except:
        pass

    tasks_done_week = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1 AND date>=date('now','-7 days')",
        (user["id"],)
    ).fetchone()[0]
    conn.close()

    now = datetime.now()

    prompt = f"""
Generate a morning intelligence briefing for this founder.

{build_deep_context(user, profile)}

Today: {now.strftime('%A, %B %d, %Y')}
Day {days_journey} of their journey
Tasks completed this week: {tasks_done_week}

Live market data ({total} sources):
{web_data if web_data else 'Limited data available today'}

Write a morning briefing that feels like a real co-founder wrote it after working all night. It should have these sections but written as flowing paragraphs, not labels and bullet points:

Start with a personalised good morning that references where they are in their journey and what they are building.

Then share 2-3 specific things that happened in their market or industry overnight, based only on the real data above. If no relevant data was found, say so honestly.

Then share what the market feels like today for their specific product — is momentum building, flat, or there are new signals they should know about.

Then give them one clear priority for today with reasoning.

Then close with one observation about what their behaviour data suggests about where they are mentally this week.

Write it like a human. No section headers. No bullet points. Natural paragraphs. Maximum 350 words.
"""

    briefing = ask_groq(prompt, max_tokens=600)

    conn = get_db()
    conn.execute(
        "INSERT INTO daily_intelligence (user_id, briefing, market_data, opportunities) VALUES (?,?,?,?)",
        (user["id"], briefing, web_data, "")
    )
    conn.commit()
    conn.close()

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
        "size": (f"{query} market size revenue statistics", "search"),
        "reddit": (f"{query} consumer discussion reddit", "reddit_native"),
        "news": (f"{query} industry news 2025", "news"),
        "platforms": (f"{query} social media audience platform {location}", "search"),
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
You are a market analyst. Generate a market intelligence report based ONLY on the data below.
Do not invent statistics. If specific data is not in the research, say "Data not available" for that point.

Founder Context:
{build_deep_context(user, profile)}

Research Data ({total} real sources):
{web_data}

Write a market analysis that covers:
- Current demand signals for their specific product in {location} based on the data found
- Where demand is coming from geographically and demographically based on research
- What people are actually saying about this type of product based on Reddit and news data
- Market size estimates — only cite if found in research data, otherwise say estimate unavailable
- 3 real opportunities visible in the data
- 2 honest threats or challenges visible in the data

Write in flowing paragraphs. Reference the actual sources found. Be honest about what data was and was not available.
Maximum 400 words.
"""

    analysis = ask_groq(prompt, max_tokens=800)

    conn = get_db()
    conn.execute(
        "INSERT INTO market_data (user_id, query, data, sources) VALUES (?,?,?,?)",
        (user["id"], query, analysis, json.dumps(list(search_queries.keys())))
    ) if False else None
    conn.close()

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
        "specific": (f"{competitor_names} company overview funding", "search") if competitor_names else (f"{industry} startups {location} 2025", "search"),
        "reddit": (f"{product} {industry} alternative comparison reddit", "reddit_native"),
        "news": (f"{competitor_names or industry} startup news funding 2025", "news"),
        "reviews": (f"{competitor_names or product} {location} reviews problems", "search"),
    }

    all_results = multi_search(search_queries)
    web_data, total = format_search_results(all_results)

    if total == 0:
        return jsonify({
            "analysis": "Data not available. The search did not return competitor information for this query. Try entering specific competitor names for better results.",
            "sources_count": 0,
            "success": True
        })

    prompt = f"""
You are a competitive intelligence analyst. Generate a competitor report based ONLY on the research data below.
Never invent company details, founder names, or revenue figures. If information is not in the data, say clearly "Information not available."

Founder Context:
{build_deep_context(user, profile)}

Location Focus: {location}
Research Data ({total} sources):
{web_data}

Write a competitor analysis covering:

LOCAL COMPETITORS IN {location.upper()}:
Based only on search results, name real companies found. For each one found: what they do, their apparent pricing if available, their visible strengths, complaints found about them. If founder information is not publicly available, state: "Founder information not available on public platforms."

GLOBAL COMPETITORS:
Name global players found in the research. Same format.

WHERE COMPETITORS ARE WEAK:
Based on reviews and Reddit data only, what real complaints do customers have.

YOUR POSITIONING OPPORTUNITY:
Based on the gaps found in research, where this founder could position.

If any company's information was not found in the research, clearly say "Detailed information not available for [company name]."

Write in clear paragraphs. Maximum 500 words. Honesty over sounding impressive.
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

Current trends on {platform} in {location}:
{trends if trends else 'Limited trend data available'}

Generate a {days}-day content calendar for {platform}.

For each day write:
Day [number] — [best posting time for {location} timezone]
Type: [content type]
Caption: [Complete ready-to-post caption. Real words. Not a template. Written for {profile.get('product', '')} specifically.]
Hashtags: [5 relevant hashtags for {location} and industry]
Hook: [Opening line designed to stop the scroll]

Make every post specific to {profile.get('product', '')} targeting {location}.
Mix: 4 value posts for every 1 promotional post.
"""

    calendar = ask_groq(prompt, max_tokens=2500)

    conn = get_db()
    conn.execute(
        "INSERT INTO content_library (user_id, platform, content) VALUES (?,?,?)",
        (user["id"], platform, calendar)
    )
    conn.commit()
    conn.close()

    return jsonify({"calendar": calendar, "platform": platform, "success": True})


@app.route("/api/reports/generate", methods=["POST"])
@require_auth
def generate_report(user):
    profile = get_profile(user["id"])
    data = request.json
    report_type = data.get("type", "progress")

    conn = get_db()
    total_tasks = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=?", (user["id"],)
    ).fetchone()[0]
    done_tasks = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1", (user["id"],)
    ).fetchone()[0]
    days = 0
    try:
        start = datetime.strptime(
            user.get("journey_start", str(datetime.now().date())), "%Y-%m-%d"
        )
        days = (datetime.now() - start).days
    except:
        pass
    conn.close()

    prompt = f"""
Generate a {report_type} report for this founder.

{build_deep_context(user, profile)}

Progress Data:
- Days on journey: {days}
- Total tasks assigned: {total_tasks}
- Tasks completed: {done_tasks}
- Completion rate: {round(done_tasks/max(total_tasks,1)*100)}%

Write a comprehensive {report_type} report that:
- Summarises where the founder is right now honestly
- What they have accomplished
- What the data says about their execution velocity
- What needs to change
- Their top 3 priorities for the next 30 days

Write as a real co-founder would write a progress memo. Professional, honest, specific.
Maximum 600 words.
"""

    report_content = ask_groq(prompt, max_tokens=800)

    conn = get_db()
    title = f"{report_type.title()} Report — {datetime.now().strftime('%B %d, %Y')}"
    conn.execute(
        "INSERT INTO saved_reports (user_id, title, content, report_type) VALUES (?,?,?,?)",
        (user["id"], title, report_content, report_type)
    )
    conn.commit()
    conn.close()

    return jsonify({"report": report_content, "title": title, "success": True})


@app.route("/api/reports/saved")
@require_auth
def get_saved_reports(user):
    conn = get_db()
    reports = conn.execute(
        "SELECT id, title, report_type, created_at FROM saved_reports WHERE user_id=? ORDER BY id DESC LIMIT 10",
        (user["id"],)
    ).fetchall()
    conn.close()
    return jsonify({"reports": [dict(r) for r in reports]})


@app.route("/api/agent/<agent_type>", methods=["POST"])
@require_auth
def specialist_agent(user, agent_type):
    data = request.json
    question = data.get("question", "")
    profile = get_profile(user["id"])
    context = build_deep_context(user, profile)
    location = profile.get("location", "India")

    agent_systems = {
        "legal": f"You are a senior startup lawyer with deep expertise in {location} law including Companies Act, GST, FSSAI, SEBI, Startup India scheme, and international expansion. You give specific actionable guidance with real form names, fees in local currency, and realistic timelines. You always note when a matter requires consulting a licensed lawyer.",
        "financial": f"You are a CFO who has worked with 100 early-stage startups in {location}. You build real financial models with actual numbers. You name specific platforms like Razorpay, Stripe, QuickBooks, Tally. You calculate unit economics, burn rates, and runway with precision.",
        "consumer": f"You are a consumer psychology expert who has studied buying behaviour in {location} specifically. You understand cultural nuances, price sensitivity, and decision triggers specific to this market. You give specific messaging frameworks and real examples.",
        "growth": f"You are a growth strategist who has built 0-to-1 growth for 20 startups in {location}. You give specific growth experiments with expected outcomes. You name real communities, platforms, and tactics that work in this specific market.",
        "product": f"You are a senior product manager who has shipped products used by millions. You give specific frameworks, prioritisation methods, and technical guidance. You help founders make build vs buy decisions with clear reasoning.",
        "formulation": f"You are a certified product formulation chemist specialising in food, beverage, cosmetics, and consumer goods for the {location} market. You give actual ingredient names, proportions, FSSAI regulations, approved supplier categories, and manufacturing process guidance. You never give unverified safety claims.",
        "sales": f"You are a sales director who has personally closed enterprise and consumer deals in {location}. You write actual scripts word for word. You give specific objection responses. You name real platforms like LinkedIn Sales Navigator, IndiaMART, Justdial, Meesho depending on the product type.",
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

Live research data:
{search_context if search_context else 'Limited search data available for this query.'}

Founder's question: {question}

Answer as the world-class specialist you are. Be completely specific to their product and market.
If asked for a complete document like a sales pitch, contract, or plan — write the entire thing, not advice about it.
If specific data was not found in search results, say so clearly rather than inventing it.
Write in natural paragraphs. Give your reasoning. Maximum 500 words unless writing a full document.
"""

    reply = ask_groq(prompt, system=system, max_tokens=800)
    return jsonify({"reply": reply, "agent": agent_type, "success": True})


@app.route("/api/stats")
@require_auth
def get_stats(user):
    conn = get_db()
    total = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND date=date('now')",
        (user["id"],)
    ).fetchone()[0]
    done = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND date=date('now') AND done=1",
        (user["id"],)
    ).fetchone()[0]
    streak = conn.execute(
        """SELECT COUNT(DISTINCT date) FROM tasks
        WHERE user_id=? AND done=1 AND date >= date('now', '-30 days')""",
        (user["id"],)
    ).fetchone()[0]
    weekly_done = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1 AND date>=date('now','-7 days')",
        (user["id"],)
    ).fetchone()[0]
    weekly_total = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND date>=date('now','-7 days')",
        (user["id"],)
    ).fetchone()[0]
    total_ever = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=?", (user["id"],)
    ).fetchone()[0]
    done_ever = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1", (user["id"],)
    ).fetchone()[0]
    conn.close()

    days_journey = 0
    try:
        start = datetime.strptime(
            user.get("journey_start", str(datetime.now().date())), "%Y-%m-%d"
        )
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
    conn = get_db()
    users = conn.execute(
        "SELECT name, email, created_at FROM users ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return jsonify({"users": [dict(u) for u in users], "total": len(users)})


@app.route("/api/status")
def api_status():
    return jsonify({
        "status": "running",
        "time": datetime.now().strftime("%I:%M %p"),
        "version": "3.0"
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
