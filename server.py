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

# ── API KEYS ──────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "GEMINI_API_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "SERPER_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "GROQ_API_KEY")
JWT_SECRET = "founderos-jwt-secret-2024"

# Gemini — only for onboarding report (runs once per user)
client_gemini = genai.Client(api_key=GEMINI_API_KEY)

# Groq — for everything else (unlimited, instant)
client_groq = Groq(api_key=GROQ_API_KEY)

def ask_gemini(prompt, system="", max_tokens=1500):
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
        return f"AI temporarily unavailable. Error: {str(e)}"

def ask_groq(prompt, system="", max_tokens=1000, deep=False):
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
        return response.choices[0].message.content
    except Exception as e:
        print(f"Groq error: {e}")
        return f"AI temporarily unavailable. Error: {str(e)}"

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
            founder_report TEXT,
            journey_start TEXT DEFAULT (date('now'))
        );
        CREATE TABLE IF NOT EXISTS founder_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            answers TEXT,
            archetype TEXT,
            predicted_revenue_date TEXT,
            top_risks TEXT,
            top_strengths TEXT,
            skill_gaps TEXT,
            ai_personality TEXT,
            startup_name TEXT,
            product TEXT,
            industry TEXT,
            stage TEXT,
            market TEXT,
            goal TEXT,
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
            done INTEGER DEFAULT 0,
            verified INTEGER DEFAULT 0,
            date TEXT DEFAULT (date('now')),
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS briefings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content TEXT,
            date TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS market_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            query TEXT,
            data TEXT,
            sources TEXT,
            saved_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS competitor_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            data TEXT,
            saved_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS community_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            platform TEXT,
            topic TEXT,
            draft TEXT,
            status TEXT DEFAULT 'pending',
            date TEXT DEFAULT (datetime('now'))
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

def reddit_search(query):
    try:
        url = f"https://www.reddit.com/search.json?q={requests.utils.quote(query)}&sort=relevance&limit=5"
        headers = {"User-Agent": "FounderOS/1.0"}
        resp = requests.get(url, headers=headers, timeout=8)
        data = resp.json()
        results = []
        for post in data.get("data", {}).get("children", []):
            p = post.get("data", {})
            results.append({
                "title": p.get("title", ""),
                "text": p.get("selftext", "")[:300],
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
    for source, items in results_dict.items():
        if items:
            formatted += f"\n[{source.upper()}]\n"
            for item in items[:3]:
                if isinstance(item, dict):
                    text = item.get("snippet") or item.get("text") or item.get("title", "")
                    formatted += f"- {text[:200]}\n"
    return formatted

def get_profile(user_id):
    conn = get_db()
    profile = conn.execute(
        "SELECT * FROM founder_profiles WHERE user_id=?", (user_id,)
    ).fetchone()
    conn.close()
    return dict(profile) if profile else {}

def build_context(user, profile):
    if not profile:
        return f"Founder: {user.get('name', 'Founder')}. Profile not complete yet."
    days = 0
    try:
        start = datetime.strptime(
            user.get("journey_start", str(datetime.now().date())), "%Y-%m-%d"
        )
        days = (datetime.now() - start).days
    except:
        pass
    return f"""
FOUNDER PROFILE:
Name: {user.get('name', 'Founder')}
Startup: {profile.get('startup_name', 'Not specified')}
Product: {profile.get('product', 'Not specified')}
Industry: {profile.get('industry', 'Not specified')}
Stage: {profile.get('stage', 'idea')}
Target Market: {profile.get('market', 'Not specified')}
Primary Goal: {profile.get('goal', 'Not specified')}
Archetype: {profile.get('archetype', 'Not analyzed yet')}
AI Personality: {profile.get('ai_personality', 'mentor')}
Days on Journey: {days}
Top Strengths: {profile.get('top_strengths', 'Not analyzed')}
Skill Gaps: {profile.get('skill_gaps', 'Not analyzed')}
Top Risks: {profile.get('top_risks', 'Not analyzed')}
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
            "success": True,
            "token": token,
            "name": name,
            "onboarding_done": False
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
        "success": True,
        "token": token,
        "name": user["name"],
        "onboarding_done": bool(user["onboarding_done"])
    })

@app.route("/api/auth/me")
@require_auth
def get_me(user):
    return jsonify({
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "onboarding_done": bool(user["onboarding_done"]),
        "journey_start": user.get("journey_start")
    })

@app.route("/api/onboarding/submit", methods=["POST"])
@require_auth
def submit_onboarding(user):
    data = request.json
    answers = data.get("answers", {})
    profile_data = {
        "startup_name": answers.get("q11", ""),
        "product": answers.get("q12", ""),
        "industry": answers.get("q13", ""),
        "stage": answers.get("q16", "idea"),
        "market": answers.get("q19", ""),
        "goal": answers.get("q21", ""),
    }
    prompt = f"""
Analyze this founder profile from their onboarding answers.

Answers:
{json.dumps(answers, indent=2)}

Generate a Founder Intelligence Report in this EXACT JSON format:
{{
  "archetype": "2-4 word founder archetype",
  "predicted_revenue_date": "realistic month and year for first revenue",
  "top_risks": ["risk 1", "risk 2", "risk 3"],
  "top_strengths": ["strength 1", "strength 2", "strength 3"],
  "skill_gaps": ["gap 1", "gap 2", "gap 3"],
  "ai_personality": "one of: tough-love, encouraging, analytical, challenger, mentor",
  "summary": "3 sentence founder summary",
  "predicted_timeline": {{
    "first_customer": "month year",
    "first_revenue": "month year",
    "first_10k_revenue": "month year",
    "product_market_fit": "month year"
  }}
}}

Return ONLY valid JSON. No other text. No markdown.
"""
    report_text = ask_gemini(prompt, max_tokens=1000)
    try:
        clean = report_text.strip()
        if "```" in clean:
            clean = re.sub(r'```json\n?|\n?```', '', clean)
        report = json.loads(clean)
    except:
        report = {
            "archetype": "Determined Founder",
            "predicted_revenue_date": "3-6 months",
            "top_risks": ["Execution speed", "Market validation", "Resource constraints"],
            "top_strengths": ["Vision", "Determination", "Domain knowledge"],
            "skill_gaps": ["Sales", "Marketing", "Finance"],
            "ai_personality": "mentor",
            "summary": "A driven founder building something meaningful.",
            "predicted_timeline": {
                "first_customer": "2 months",
                "first_revenue": "3 months",
                "first_10k_revenue": "6 months",
                "product_market_fit": "12 months"
            }
        }
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM founder_profiles WHERE user_id=?", (user["id"],)
    ).fetchone()
    if existing:
        conn.execute("""
            UPDATE founder_profiles SET
            answers=?, archetype=?, predicted_revenue_date=?,
            top_risks=?, top_strengths=?, skill_gaps=?,
            ai_personality=?, startup_name=?, product=?,
            industry=?, stage=?, market=?, goal=?,
            updated_at=datetime('now')
            WHERE user_id=?
        """, (
            json.dumps(answers), report.get("archetype", ""),
            report.get("predicted_revenue_date", ""),
            json.dumps(report.get("top_risks", [])),
            json.dumps(report.get("top_strengths", [])),
            json.dumps(report.get("skill_gaps", [])),
            report.get("ai_personality", "mentor"),
            profile_data["startup_name"], profile_data["product"],
            profile_data["industry"], profile_data["stage"],
            profile_data["market"], profile_data["goal"],
            user["id"]
        ))
    else:
        conn.execute("""
            INSERT INTO founder_profiles
            (user_id, answers, archetype, predicted_revenue_date,
            top_risks, top_strengths, skill_gaps, ai_personality,
            startup_name, product, industry, stage, market, goal)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            user["id"], json.dumps(answers),
            report.get("archetype", ""),
            report.get("predicted_revenue_date", ""),
            json.dumps(report.get("top_risks", [])),
            json.dumps(report.get("top_strengths", [])),
            json.dumps(report.get("skill_gaps", [])),
            report.get("ai_personality", "mentor"),
            profile_data["startup_name"], profile_data["product"],
            profile_data["industry"], profile_data["stage"],
            profile_data["market"], profile_data["goal"]
        ))
    conn.execute(
        "UPDATE users SET onboarding_done=1, founder_report=? WHERE id=?",
        (json.dumps(report), user["id"])
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True, "report": report})

@app.route("/api/chat", methods=["POST"])
@require_auth
def chat(user):
    data = request.json
    message = data.get("message", "")
    mode = data.get("mode", "quick")
    profile = get_profile(user["id"])
    context = build_context(user, profile)
    message_lower = message.lower().strip()

    conn = get_db()
    history = conn.execute(
        "SELECT role, content FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT 10",
        (user["id"],)
    ).fetchall()
    conn.close()
    history = list(reversed([dict(h) for h in history]))

    is_greeting = any(message_lower.startswith(p) for p in [
        "hey", "hi", "hello", "good morning", "good evening",
        "thanks", "thank you", "ok", "okay", "sup"
    ])

    web_context = ""
    sources_used = []
    agent_steps = []

    if not is_greeting:
        industry = profile.get("industry", "")
        market = profile.get("market", "")
        search_query = f"{message} {industry} {market}"

        agent_steps.append({
            "agent": "Research Agent",
            "status": "Searching Google, Reddit, LinkedIn, News simultaneously...",
            "icon": "🔍"
        })

        search_queries = {
            "google": (search_query, "search"),
            "news": (f"{message} {industry} 2025", "news"),
            "reddit": (f"{message} {industry} founder startup", "reddit_native"),
            "linkedin": (f"{message} {industry}", "linkedin"),
        }

        all_results = multi_search(search_queries)
        web_context = format_search_results(all_results)
        total_results = sum(len(v) for v in all_results.values())

        if total_results > 0:
            agent_steps.append({
                "agent": "Research Agent",
                "status": f"Found {total_results} live sources across Google, Reddit, LinkedIn, News",
                "icon": "📡"
            })
            sources_used = list(search_queries.keys())

        if any(w in message_lower for w in ["market", "demand", "size", "industry", "trend"]):
            agent_steps.append({
                "agent": "Market Agent",
                "status": "Analysing market data...",
                "icon": "📊"
            })
        if any(w in message_lower for w in ["competitor", "competition", "vs", "compare", "alternative"]):
            agent_steps.append({
                "agent": "Competitor Agent",
                "status": "Mapping competitive landscape...",
                "icon": "🔎"
            })
        if any(w in message_lower for w in ["formula", "ingredient", "recipe", "make", "formulation", "how to make"]):
            agent_steps.append({
                "agent": "Formulation Agent",
                "status": "Checking technical specifications...",
                "icon": "🧪"
            })
        if any(w in message_lower for w in ["legal", "register", "tax", "gst", "compliance", "contract"]):
            agent_steps.append({
                "agent": "Legal Agent",
                "status": "Reviewing legal requirements...",
                "icon": "⚖️"
            })
        if any(w in message_lower for w in ["price", "pricing", "revenue", "profit", "margin", "fundraise", "money"]):
            agent_steps.append({
                "agent": "Financial Agent",
                "status": "Running financial analysis...",
                "icon": "💰"
            })
        if any(w in message_lower for w in ["quit", "give up", "stop", "fail", "hopeless", "not working", "depressed"]):
            agent_steps.append({
                "agent": "Motivation Agent",
                "status": "Pulling real founder success data...",
                "icon": "💪"
            })

        agent_steps.append({
            "agent": "Synthesis Agent",
            "status": "Preparing your answer...",
            "icon": "🧠"
        })

    personality = profile.get("ai_personality", "mentor")
    personality_map = {
        "tough-love": "Be direct and challenging. Push back on weak thinking. Demand accountability. No excuses.",
        "encouraging": "Be warm and supportive. Celebrate progress. Keep energy high. But always honest.",
        "analytical": "Lead with data and frameworks. Use numbers. Be precise and structured.",
        "challenger": "Question every assumption. Play devil's advocate. Force harder thinking.",
        "mentor": "Be wise and balanced. Guide rather than dictate. Ask powerful questions."
    }

    system = f"""You are an elite AI Co-Founder. Not a generic chatbot. A real co-founder who knows this founder deeply.

{context}

Personality mode: {personality}
{personality_map.get(personality, '')}

CRITICAL RULES:
1. Use the founder name, startup name, and product naturally in every response.
2. NEVER give generic advice. Every answer must be specific to their product, market, stage, and goals.
3. If they say they want to quit — do NOT agree. Pull the market data provided. Show them evidence. Give them one small win to focus on right now.
4. FORMAT every business response: One line brief summary at top. Then 3 to 5 bullet points. Then section THIS WEEK with 3 specific actions.
5. Answer about ANY product in ANY industry anywhere in the world — food, fashion, tech, health, D2C, B2B, SaaS, physical products, services, anything.
6. For formulation questions about any product — give safe accurate guidance with regulatory notes.
7. For personal questions about burnout motivation co-founder conflict — respond as a trusted advisor who knows them well.
8. Keep responses under 350 words unless asked for deep research.
9. Greetings — respond warmly using their name, reference their journey days, ask one sharp question. No bullet points for greetings.
10. NEVER say you cannot find data. Always give your best analysis using the research data provided.
"""

    history_text = ""
    for h in history[-6:]:
        history_text += f"\n{h['role'].upper()}: {h['content']}"

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
Previous conversation:
{history_text}

Founder message: {message}

Respond warmly. Use their name {user.get('name', 'Founder')}.
Mention Day {days} of their founder journey.
Reference their startup {profile.get('startup_name', '')} and stage {profile.get('stage', '')}.
Ask ONE sharp question about their biggest current challenge.
Under 80 words. Conversational. No bullet points.
"""
        reply = ask_groq(full_prompt, system=system, max_tokens=200)
    else:
        full_prompt = f"""
Previous conversation:
{history_text}

Live research data from Google, Reddit, LinkedIn, and News:
{web_context}

Founder question: {message}

Answer using the live research data AND your knowledge.
Be completely specific to their product {profile.get('product', '')} and market {profile.get('market', '')}.
Mode: {mode}
"""
        use_deep = mode == "deep"
        reply = ask_groq(full_prompt, system=system, max_tokens=800, deep=use_deep)

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
        "agent_steps": agent_steps,
        "sources": sources_used,
        "success": True
    })

@app.route("/api/market/research", methods=["POST"])
@require_auth
def market_research(user):
    profile = get_profile(user["id"])
    data = request.json
    custom_query = data.get("query", "")
    product = profile.get("product", "")
    industry = profile.get("industry", "")
    market = profile.get("market", "")
    query = custom_query if custom_query else f"{product} {industry}"

    search_queries = {
        "google_trends": (f"{query} market demand 2025", "search"),
        "market_size": (f"{query} market size revenue statistics", "search"),
        "reddit_demand": (f"{query} demand consumer interest", "reddit_native"),
        "news": (f"{query} industry news 2025", "news"),
        "platforms": (f"{query} popular platform social media audience", "search"),
        "geography": (f"{query} {market} market opportunity", "search"),
    }

    all_results = multi_search(search_queries)
    web_data = format_search_results(all_results)
    total = sum(len(v) for v in all_results.values())

    prompt = f"""
You are a market intelligence analyst.

Founder Context:
{build_context(user, profile)}

Live Research Data from {total} sources across Google, Reddit, and News:
{web_data}

Generate a market intelligence report with these exact sections:

MARKET DEMAND
Current demand level and direction with specific numbers where available.

WHERE DEMAND IS HIGHEST
Which platforms, cities, countries. Be specific with real names.

WHAT TO POST TODAY
3 specific content ideas based on current trends. Platform and format for each.

MARKET SIZE
TAM SAM SOM estimate for their specific niche with numbers.

RISING TRENDS
3 trends rising in their market right now with evidence from research.

OPPORTUNITIES
2 specific gaps or underserved opportunities in this market right now.

Keep each section to 3 to 5 bullet points. Use real data. No waffle.
"""

    analysis = ask_groq(prompt, max_tokens=1200)

    conn = get_db()
    conn.execute(
        "INSERT INTO market_data (user_id, query, data, sources) VALUES (?,?,?,?)",
        (user["id"], query, analysis, json.dumps(list(search_queries.keys())))
    )
    conn.commit()
    conn.close()

    return jsonify({
        "analysis": analysis,
        "sources_count": total,
        "sources": list(search_queries.keys()),
        "success": True
    })

@app.route("/api/competitors/analyse", methods=["POST"])
@require_auth
def competitor_analysis(user):
    profile = get_profile(user["id"])
    data = request.json
    competitor_names = data.get("competitors", "")
    product = profile.get("product", "")
    industry = profile.get("industry", "")

    search_queries = {
        "top_competitors": (f"top competitors {product} {industry} 2025", "search"),
        "pricing": (f"{competitor_names or product} competitor pricing strategy", "search"),
        "reddit": (f"{product} {industry} best alternative complaints", "reddit_native"),
        "news": (f"{competitor_names or industry} startup funding news 2025", "news"),
        "weaknesses": (f"{competitor_names or product} problems complaints reviews", "search"),
        "gaps": (f"{industry} market gap underserved customers 2025", "search"),
    }

    all_results = multi_search(search_queries)
    web_data = format_search_results(all_results)
    total = sum(len(v) for v in all_results.values())

    prompt = f"""
You are a competitive intelligence expert.

Founder Context:
{build_context(user, profile)}

Live Competitive Research from {total} sources:
{web_data}

Generate competitor intelligence report with these sections:

TOP COMPETITORS
Name real competitors. For each: what they do, estimated pricing, their strength, their weakness.

WHERE THEY ARE WEAK
Specific complaints and gaps customers have about existing solutions.

YOUR POSITIONING
Where this founder should position given their stage and resources.

WHAT COMPETITORS ARE DOING NOW
Recent moves, content, campaigns based on research data.

STRATEGY TO WIN
3 specific moves this founder can take in the next 30 days to take market share.

REVENUE ESTIMATES
Estimated revenue range of top 2 to 3 competitors based on available signals.

Be specific. Name real companies. Use real data from research above.
"""

    analysis = ask_groq(prompt, max_tokens=1200)

    conn = get_db()
    conn.execute(
        "UPDATE competitor_data SET data=?, saved_at=datetime('now') WHERE user_id=?",
        (analysis, user["id"])
    )
    if conn.execute("SELECT changes()").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO competitor_data (user_id, data) VALUES (?,?)",
            (user["id"], analysis)
        )
    conn.commit()
    conn.close()

    return jsonify({
        "analysis": analysis,
        "sources_count": total,
        "success": True
    })

@app.route("/api/tasks/generate", methods=["POST"])
@require_auth
def generate_tasks(user):
    profile = get_profile(user["id"])
    context = build_context(user, profile)

    conn = get_db()
    completed_yesterday = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1 AND date=date('now','-1 day')",
        (user["id"],)
    ).fetchone()[0]
    total_yesterday = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND date=date('now','-1 day')",
        (user["id"],)
    ).fetchone()[0]
    conn.close()

    prompt = f"""
{context}

Yesterday: completed {completed_yesterday} of {total_yesterday} tasks.

Generate exactly 6 tasks for today in this EXACT JSON format:
[
  {{
    "title": "Short clear task title",
    "description": "What exactly to do in 1 to 2 sentences",
    "how_to": "Step by step instructions. Specific. Include exact platforms tools or links where relevant.",
    "category": "one of: marketing, product, sales, research, finance, legal, operations",
    "priority": "one of: high, medium, low",
    "time_est": "eg 30 mins or 2 hours",
    "reason": "Why this specific task matters for their startup right now in one sentence"
  }}
]

Rules:
- Tasks completely specific to their product industry and stage
- High priority tasks first
- Include at least one revenue generating task
- Include at least one market research task
- Return ONLY valid JSON array. No other text. No markdown.
"""

    tasks_text = ask_groq(prompt, max_tokens=1500)

    try:
        clean = tasks_text.strip()
        if "```" in clean:
            clean = re.sub(r'```json\n?|\n?```', '', clean)
        tasks = json.loads(clean)
    except:
        tasks = [{
            "title": "Research your top 3 competitors",
            "description": "Find your 3 main competitors and document their pricing and key features",
            "how_to": "Google your product category plus competitors. Visit their websites. Note pricing, features, and customer reviews.",
            "category": "research",
            "priority": "high",
            "time_est": "1 hour",
            "reason": "Understanding competition is essential before positioning your product"
        }]

    conn = get_db()
    conn.execute(
        "DELETE FROM tasks WHERE user_id=? AND date=date('now') AND done=0",
        (user["id"],)
    )
    for task in tasks:
        conn.execute(
            "INSERT INTO tasks (user_id, title, description, how_to, category, priority, time_est, reason) VALUES (?,?,?,?,?,?,?,?)",
            (
                user["id"], task.get("title"), task.get("description"),
                task.get("how_to"), task.get("category"), task.get("priority"),
                task.get("time_est"), task.get("reason")
            )
        )
    conn.commit()
    conn.close()

    return jsonify({"success": True, "count": len(tasks)})

@app.route("/api/tasks")
@require_auth
def get_tasks(user):
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM tasks WHERE user_id=? AND date=date('now')
        ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END""",
        (user["id"],)
    ).fetchall()
    conn.close()
    return jsonify({"tasks": [dict(r) for r in rows]})

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
    if time_spent < 60 and task["time_est"] and "hour" in str(task["time_est"]).lower():
        conn.close()
        return jsonify({
            "verified": False,
            "message": f"This task is estimated {task['time_est']}. Did you actually complete it?"
        })
    conn.execute(
        "UPDATE tasks SET done=1, verified=1, completed_at=datetime('now') WHERE id=? AND user_id=?",
        (task_id, user["id"])
    )
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

@app.route("/api/briefing/generate", methods=["POST"])
@require_auth
def generate_briefing(user):
    profile = get_profile(user["id"])
    context = build_context(user, profile)
    product = profile.get("product", "")
    industry = profile.get("industry", "")

    search_queries = {
        "market_news": (f"{industry} {product} market news today 2025", "news"),
        "competitor_moves": (f"{industry} startup competitor news this week", "news"),
        "community": (f"{product} {industry} discussion reddit", "reddit_native"),
        "trends": (f"{industry} trend opportunity 2025", "search"),
    }
    all_results = multi_search(search_queries)
    web_data = format_search_results(all_results)

    conn = get_db()
    days_journey = 0
    try:
        start = datetime.strptime(
            user.get("journey_start", str(datetime.now().date())), "%Y-%m-%d"
        )
        days_journey = (datetime.now() - start).days
    except:
        pass

    tasks_done = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1 AND date>=date('now','-7 days')",
        (user["id"],)
    ).fetchone()[0]
    tasks_total = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND date>=date('now','-7 days')",
        (user["id"],)
    ).fetchone()[0]
    conn.close()

    now = datetime.now()
    day_name = now.strftime("%A")
    date_str = now.strftime("%B %d, %Y")

    prompt = f"""
Generate a morning briefing for this founder.

{context}

Today: {day_name}, {date_str}
Day {days_journey} of their founder journey
Last 7 days: completed {tasks_done} of {tasks_total} tasks

Live Market Intelligence from Google, Reddit, and News:
{web_data}

Write briefing in these exact sections:

GOOD MORNING [use their actual name]
One powerful personalised sentence. Reference Day {days_journey}.

WHILE YOU WERE SLEEPING
3 things that happened in their market overnight. Use research data. Be specific.

TODAY'S MARKET PULSE
Is demand up or down for their product today. What is driving it.

MOST IMPORTANT TASK TODAY
ONE task only. What and exactly why it matters most today.

COMPETITOR WATCH
One specific thing a competitor did recently they should know about.

COMMUNITY SIGNAL
What potential customers or founders are saying about their market right now.

MOTIVATION SIGNAL
A real market signal that validates their idea. Not a generic quote.

Each section 2 to 3 sentences. Sharp and useful. No waffle.
"""

    briefing = ask_groq(prompt, max_tokens=1000)

    conn = get_db()
    conn.execute(
        "INSERT INTO briefings (user_id, content) VALUES (?,?)",
        (user["id"], briefing)
    )
    conn.commit()
    conn.close()

    return jsonify({"briefing": briefing, "success": True})

@app.route("/api/briefing")
@require_auth
def get_briefing(user):
    conn = get_db()
    row = conn.execute(
        "SELECT content, date FROM briefings WHERE user_id=? ORDER BY id DESC LIMIT 1",
        (user["id"],)
    ).fetchone()
    conn.close()
    if row:
        return jsonify({"briefing": row["content"], "date": row["date"]})
    return jsonify({
        "briefing": "Generate your morning briefing to see today's intelligence.",
        "date": ""
    })

@app.route("/api/agent/<agent_type>", methods=["POST"])
@require_auth
def specialist_agent(user, agent_type):
    data = request.json
    question = data.get("question", "")
    profile = get_profile(user["id"])
    context = build_context(user, profile)

    agent_systems = {
        "legal": "You are a senior corporate lawyer specialising in startup law. You know Indian law including Companies Act, GST, FSSAI, SEBI, US law, and international regulations. Give accurate legal guidance. Always note when to consult a real lawyer for complex matters.",
        "financial": "You are a CFO advisor for early-stage startups. You specialise in unit economics, fundraising, financial modeling, pricing strategy, and cash flow management. Give precise numerical guidance with formulas and examples.",
        "consumer": "You are a consumer behaviour expert and market psychologist. You understand why people buy, what triggers decisions, how to craft messaging that converts, and how to map customer journeys for any product in any market.",
        "growth": "You are a growth hacker who has scaled multiple startups from zero to millions of users. You know viral loops, referral mechanics, retention tactics, product-led growth, and distribution channels. Give specific testable experiments.",
        "product": "You are a senior product manager from top tech companies. You know MVP scoping, feature prioritisation, product-market fit measurement, user research, and roadmap planning. Help founders build the right thing.",
        "formulation": "You are a product formulation expert covering food and beverage, cosmetics, supplements, and consumer goods. You know ingredient safety, regulatory compliance including FSSAI FDA and EU standards, sourcing, manufacturing processes, and shelf life guidance.",
        "sales": "You are a sales coach who has closed millions in B2B and B2C deals across India and globally. You know cold outreach, sales scripts, objection handling, pipeline management, and closing techniques. Give specific scripts the founder can use today.",
    }

    system = agent_systems.get(agent_type, agent_systems["legal"])
    search_results = serper_search(
        f"{question} {profile.get('industry', '')}", num=5
    )
    search_context = "\n".join([
        f"- {r.get('snippet', '')}" for r in search_results
    ])

    prompt = f"""
{context}

Live Research:
{search_context}

Founder Question: {question}

Answer as the specialist you are. Be completely specific to their startup and market.
Format: Brief summary first. Then bullet points. Then 2 to 3 specific actions they can take this week.
Under 400 words.
"""

    reply = ask_groq(prompt, system=system, max_tokens=600)
    return jsonify({"reply": reply, "agent": agent_type, "success": True})

@app.route("/api/content/generate", methods=["POST"])
@require_auth
def generate_content(user):
    profile = get_profile(user["id"])
    data = request.json
    platform = data.get("platform", "linkedin")
    days = data.get("days", 7)

    search_results = serper_search(
        f"{profile.get('product', '')} {profile.get('industry', '')} trending content {platform} 2025",
        num=5
    )
    trends = "\n".join([f"- {r.get('snippet', '')}" for r in search_results])

    prompt = f"""
{build_context(user, profile)}

Current trends in their market on {platform}:
{trends}

Generate a {days}-day content calendar for {platform}.

For each day provide:
- Day number and best posting time
- Content type: educational, story, data, controversy, product showcase, or founder journey
- Exact post caption ready to copy and paste
- 5 relevant hashtags
- One engagement hook or call to action

Make all content specific to their product {profile.get('product', '')} and market {profile.get('market', '')}.
Vary content types. Mix value posts with promotional posts in 4 to 1 ratio.
"""

    calendar = ask_groq(prompt, max_tokens=2000)
    return jsonify({"calendar": calendar, "platform": platform, "success": True})

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
        "SELECT COUNT(DISTINCT date) FROM tasks WHERE user_id=? AND done=1",
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
        "completion_rate": round(
            (weekly_done / weekly_total * 100) if weekly_total > 0 else 0
        )
    })

@app.route("/api/status")
def api_status():
    return jsonify({
        "status": "running",
        "time": datetime.now().strftime("%I:%M %p")
    })

@app.route("/")
def home():
    try:
        return open("dashboard.html", encoding="utf-8").read()
    except:
        return "<h1>FounderOS</h1><p>dashboard.html not found</p>"

# Run setup_db when imported by gunicorn too
setup_db()

if __name__ == "__main__":
    setup_db()
    print("\n" + "="*52)
    print("  FOUNDEROS — AI STARTUP OPERATING SYSTEM v2")
    print("="*52)
    print(f"  Chat AI:   Groq Llama 3.3 70B — unlimited")
    print(f"  Search:    Serper — Google Reddit LinkedIn")
    print("="*52)
    print("  Open http://localhost:5000 in browser")
    print("="*52 + "\n")
port = int(os.environ.get("PORT", 5000))
app.run(debug=False, port=port, host="0.0.0.0")
