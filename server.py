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
            location TEXT,
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
Location: {profile.get('location', profile.get('market', 'India'))}
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
        "location": answers.get("q2", "India"),
    }
    prompt = f"""
Analyze this founder profile from their onboarding answers.

Answers:
{json.dumps(answers, indent=2)}

Generate a Founder Intelligence Report in this EXACT JSON format with no extra text:
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

Return ONLY valid JSON. No markdown. No extra text.
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
            industry=?, stage=?, market=?, goal=?, location=?,
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
            profile_data["location"], user["id"]
        ))
    else:
        conn.execute("""
            INSERT INTO founder_profiles
            (user_id, answers, archetype, predicted_revenue_date,
            top_risks, top_strengths, skill_gaps, ai_personality,
            startup_name, product, industry, stage, market, goal, location)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            profile_data["market"], profile_data["goal"],
            profile_data["location"]
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
        location = profile.get("location", "India")
        search_query = f"{message} {industry} {location}"

        agent_steps.append({
            "agent": "Research Agent",
            "status": "Searching Google, Reddit, LinkedIn, News...",
            "icon": "🔍"
        })

        search_queries = {
            "google": (search_query, "search"),
            "news": (f"{message} {industry} 2025", "news"),
            "reddit": (f"{message} {industry} founder startup", "reddit_native"),
            "linkedin": (f"{message} {industry} {location}", "linkedin"),
        }

        all_results = multi_search(search_queries)
        web_context = format_search_results(all_results)
        total_results = sum(len(v) for v in all_results.values())

        if total_results > 0:
            agent_steps.append({
                "agent": "Research Agent",
                "status": f"Found {total_results} live sources",
                "icon": "📡"
            })
            sources_used = list(search_queries.keys())

        if any(w in message_lower for w in ["market", "demand", "size", "industry", "trend"]):
            agent_steps.append({"agent": "Market Agent", "status": "Analysing market data...", "icon": "📊"})
        if any(w in message_lower for w in ["competitor", "competition", "vs", "compare"]):
            agent_steps.append({"agent": "Competitor Agent", "status": "Mapping competitive landscape...", "icon": "🔎"})
        if any(w in message_lower for w in ["formula", "ingredient", "recipe", "make", "formulation"]):
            agent_steps.append({"agent": "Formulation Agent", "status": "Checking technical specs...", "icon": "🧪"})
        if any(w in message_lower for w in ["legal", "register", "tax", "gst", "compliance"]):
            agent_steps.append({"agent": "Legal Agent", "status": "Reviewing legal requirements...", "icon": "⚖️"})
        if any(w in message_lower for w in ["price", "pricing", "revenue", "profit", "fundraise"]):
            agent_steps.append({"agent": "Financial Agent", "status": "Running financial analysis...", "icon": "💰"})
        if any(w in message_lower for w in ["pitch", "sales pitch", "investor pitch"]):
            agent_steps.append({"agent": "Sales Agent", "status": "Building pitch structure...", "icon": "🎯"})
        if any(w in message_lower for w in ["quit", "give up", "stop", "fail", "hopeless"]):
            agent_steps.append({"agent": "Motivation Agent", "status": "Pulling real founder data...", "icon": "💪"})

        agent_steps.append({
            "agent": "Synthesis Agent",
            "status": "Preparing your answer...",
            "icon": "🧠"
        })

    personality = profile.get("ai_personality", "mentor")
    personality_map = {
        "tough-love": "Be direct and challenging. Push back on weak thinking. Demand accountability.",
        "encouraging": "Be warm and supportive. Celebrate progress. Keep energy high. But always honest.",
        "analytical": "Lead with data and frameworks. Use numbers. Be precise and structured.",
        "challenger": "Question every assumption. Play devil's advocate. Force harder thinking.",
        "mentor": "Be wise and balanced. Guide rather than dictate. Ask powerful questions."
    }

    system = f"""You are an elite startup advisor — brutally sharp, data-driven, and specific. You combine the expertise of a YC partner, McKinsey consultant, and serial entrepreneur who has built 10 companies.

{context}

Personality: {personality}
{personality_map.get(personality, '')}

RESPONSE RULES — follow every single one:

FORMAT FOR BUSINESS QUESTIONS:
- Line 1: One sharp insight specific to their exact situation. Never start with "Certainly", "Great", "Absolutely" or any filler.
- Then 4-6 bullet points. Each bullet must contain a real number, real company name, or specific platform.
- End with THIS WEEK: exactly 3 actions they can execute in 7 days. Each action must name a specific tool, platform, or person type to contact.

QUALITY RULES:
- NEVER say "it is important to" or "you should consider" — just say exactly what to do
- NEVER give advice that could apply to any random business — always specific to their product and market
- ALWAYS use their product name {profile.get('product', '')} and location {profile.get('location', 'India')} in responses
- For SALES PITCH requests: write the COMPLETE pitch with Hook, Problem, Solution, Proof, Offer, CTA — fully written out, not just advice
- For COMPETITOR questions: name real local competitors in their location first, then global ones
- For FORMULATION questions: give actual ingredients, ratios, and regulatory body names
- For PRICING questions: give actual rupee or dollar amounts based on market data
- For MOTIVATION or QUITTING: pull one real market statistic that validates their idea. Show them what they have already built. Give one tiny action they can do in the next 10 minutes.
- For GREETINGS: respond warmly by name, reference their journey days, ask one sharp question about their current challenge. Under 60 words. No bullet points.
- Keep responses under 400 words unless writing a full pitch, report, or document
- If asked for a full document — write it completely, not a summary"""

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
Mention Day {days} of their founder journey if more than 0.
Reference their startup {profile.get('startup_name', '')} and current stage {profile.get('stage', '')}.
Ask ONE sharp question about what they are working on right now.
Under 60 words. Conversational. No bullet points. No filler words.
"""
        reply = ask_groq(full_prompt, system=system, max_tokens=150)
    else:
        full_prompt = f"""
Previous conversation:
{history_text}

Live research data from Google, Reddit, LinkedIn, and News:
{web_context}

Founder question: {message}

Answer using the live research data AND your knowledge.
Be completely specific to their product {profile.get('product', '')} in {profile.get('location', 'India')}.
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
    location = profile.get("location", "India")
    query = custom_query if custom_query else f"{product} {industry}"

    search_queries = {
        "google_trends": (f"{query} market demand {location} 2025", "search"),
        "market_size": (f"{query} market size revenue statistics {location}", "search"),
        "reddit_demand": (f"{query} demand consumer interest reddit", "reddit_native"),
        "news": (f"{query} industry news {location} 2025", "news"),
        "platforms": (f"{query} popular platform social media {location}", "search"),
        "global": (f"{query} global market opportunity 2025", "search"),
    }

    all_results = multi_search(search_queries)
    web_data = format_search_results(all_results)
    total = sum(len(v) for v in all_results.values())

    prompt = f"""
You are a market intelligence analyst specialising in {location} markets.

Founder Context:
{build_context(user, profile)}

Live Research from {total} sources:
{web_data}

Generate market intelligence report with these exact sections:

MARKET DEMAND IN {location.upper()}
Current demand level with specific numbers. Is it growing or declining and why.

WHERE DEMAND IS HIGHEST
Which platforms, cities, age groups in {location}. Name specific places and platforms.

WHAT TO POST TODAY
3 specific content ideas based on current trends. Include exact platform, format, and hook line.

MARKET SIZE
TAM SAM SOM for {location} market with real numbers.

RISING TRENDS
3 trends rising right now with evidence from research data.

GLOBAL OPPORTUNITY
How big is the global market beyond {location}.

Keep each section to 3-5 bullet points. Use real data. No generic statements.
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
    location = data.get("location", profile.get("location", profile.get("market", "India")))
    product = profile.get("product", "")
    industry = profile.get("industry", "")

    search_queries = {
        "local_competitors": (f"top competitors {product} {industry} {location} 2025", "search"),
        "global_competitors": (f"top competitors {product} {industry} worldwide 2025", "search"),
        "pricing": (f"{product} {industry} {location} pricing competitors", "search"),
        "reddit": (f"{product} {industry} best alternative complaints reddit", "reddit_native"),
        "news": (f"{industry} startup {location} funding 2025", "news"),
        "weaknesses": (f"{competitor_names or product} {location} problems reviews complaints", "search"),
    }

    all_results = multi_search(search_queries)
    web_data = format_search_results(all_results)
    total = sum(len(v) for v in all_results.values())

    prompt = f"""
You are a competitive intelligence expert specialising in {location} markets.

Founder Context:
{build_context(user, profile)}

Search Location: {location}
Live Research from {total} sources:
{web_data}

Generate competitor intelligence report in this EXACT structure:

LOCAL COMPETITORS IN {location.upper()}
Name 3-5 real companies operating in {location}. For each:
- Company name and website if available
- What they sell and at what price in local currency
- Their biggest strength
- Their biggest weakness based on customer complaints

GLOBAL COMPETITORS
Name 2-3 global players with their market position and why they have not dominated {location} yet.

WHERE LOCAL COMPETITORS ARE WEAK IN {location.upper()}
3 specific gaps based on real customer complaints from research. These are your opportunities.

YOUR COMPETITIVE POSITIONING
Exactly where to position against local competition given the founder's stage and budget.

30-DAY STRATEGY TO WIN {location.upper()} MARKET
3 specific moves. Each must name a platform, community, or specific type of person to target.

REVENUE SIGNALS
Estimated revenue range of top 2 local competitors based on team size, funding, and market presence.

Be specific. Name real companies. Clearly separate local from global.
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
        "location": location,
        "success": True
    })

@app.route("/api/tasks/generate", methods=["POST"])
@require_auth
def generate_tasks(user):
    profile = get_profile(user["id"])
    context = build_context(user, profile)
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
    skill_gaps = profile.get("skill_gaps", "[]")
    conn.close()

    prompt = f"""
{context}

Yesterday: completed {completed_yesterday} of {total_yesterday} tasks.
Founder location: {location}
Skill gaps to address: {skill_gaps}

Generate exactly 6 tasks for today. These are NOT generic tasks. Each task must be completely specific to:
- Their product: {profile.get('product', '')}
- Their industry: {profile.get('industry', '')}
- Their stage: {profile.get('stage', '')}
- Their location: {location}
- Their skill gaps: {skill_gaps}

Return ONLY a valid JSON array in this exact format:
[
  {{
    "title": "Short specific task title — must mention their product or market",
    "description": "Exactly what to do in 2 sentences. Must include a specific platform, tool, or person type.",
    "how_to": "Step 1: [exact action with specific tool or platform]. Step 2: [exact action]. Step 3: [exact action]. Include specific websites, search terms, or contact methods they should use.",
    "category": "one of: marketing, product, sales, research, finance, legal, operations",
    "priority": "one of: high, medium, low",
    "time_est": "realistic time eg 45 mins or 2 hours",
    "reason": "One sentence explaining exactly why this task matters for their startup right now and what outcome it will produce."
  }}
]

Rules:
- First 2 tasks must be high priority revenue or validation tasks
- At least one task must address a skill gap
- At least one task must involve reaching out to a potential customer or partner
- Every how_to must have at least 3 specific steps with real platform names
- NEVER generate generic tasks like check emails or update social media
- Return ONLY the JSON array. No other text. No markdown.
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
            "title": f"Find 5 potential customers for {profile.get('product', 'your product')} in {location}",
            "description": f"Identify and contact 5 people who could be your first paying customers for {profile.get('product', 'your product')} in {location}.",
            "how_to": f"Step 1: Go to LinkedIn and search for people in {location} who match your target customer profile. Step 2: Send a personalised connection request explaining what you are building. Step 3: Follow up with a specific question about their current problem your product solves.",
            "category": "sales",
            "priority": "high",
            "time_est": "1.5 hours",
            "reason": "Finding your first customers is the single most important thing you can do right now to validate your idea and generate revenue."
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
            "message": f"This task takes {task['time_est']}. Did you actually complete it?"
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
    location = profile.get("location", "India")

    search_queries = {
        "market_news": (f"{industry} {product} {location} market news today 2025", "news"),
        "competitor_moves": (f"{industry} startup {location} competitor news this week", "news"),
        "community": (f"{product} {industry} discussion reddit", "reddit_native"),
        "trends": (f"{industry} {location} trend opportunity 2025", "search"),
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

Live Market Intelligence from {location}:
{web_data}

Write briefing in these exact sections. Be specific and sharp:

GOOD MORNING {user.get('name', 'Founder').upper()}
One powerful sentence about where they are on Day {days_journey}. Reference their specific startup and what they are building.

WHILE YOU WERE SLEEPING
3 specific things that happened in the {industry} market in {location} overnight. Use research data. Name real companies or trends.

TODAY'S MARKET PULSE
Is demand for {product} up or down today in {location}. What specific signal tells you this.

MOST IMPORTANT TASK TODAY
ONE task only. Be specific about what it is, why today, and what outcome it produces.

COMPETITOR WATCH
One specific thing a competitor in {location} did recently that the founder should know about and respond to.

COMMUNITY SIGNAL
What real customers or founders are saying about {industry} right now based on research data.

MOTIVATION SIGNAL
One real market statistic or signal that validates {profile.get('startup_name', 'their idea')}. Not a quote. A data point.

Each section 2-3 sentences maximum. Sharp. Useful. No waffle.
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
    location = profile.get("location", "India")

    agent_systems = {
        "legal": f"You are a senior corporate lawyer specialising in startup law in {location}. You know Indian law (Companies Act, GST, FSSAI, SEBI, Startup India), US law, and EU regulations. Give specific actionable legal guidance. Name actual forms, fees, and timelines. Note when to consult a real lawyer.",
        "financial": f"You are a CFO who has worked with 50 early-stage startups in {location}. Give specific numbers, formulas, and calculations. Name actual platforms like Razorpay, Stripe, QuickBooks. Build unit economics with real numbers not placeholders.",
        "consumer": f"You are a consumer behaviour expert who has studied {location} buying patterns deeply. Give specific psychological triggers, exact messaging frameworks, and real examples from {location} market. Name actual platforms and communities where the target customer spends time.",
        "growth": f"You are a growth hacker who has grown 10 startups in {location} from zero to first 1000 users. Give specific experiments with expected results. Name actual tools, communities, and tactics that work specifically in {location}.",
        "product": f"You are a senior PM who has shipped products used by millions in {location}. Give specific frameworks, prioritisation methods, and build vs buy decisions. Name actual tools like Notion, Figma, Mixpanel.",
        "formulation": f"You are a product formulation chemist who has helped launch 30 consumer products in {location}. Give actual ingredient names, ratios, suppliers in {location}, and regulatory bodies like FSSAI. Include shelf life, packaging, and manufacturing cost estimates.",
        "sales": f"You are a sales coach who has closed deals in {location} market specifically. Give actual scripts word for word. Name real platforms like LinkedIn Sales Navigator, IndiaMART, Justdial. Include follow-up sequences and objection responses specific to {location} buyer behavior.",
    }

    system = agent_systems.get(agent_type, agent_systems["legal"])
    search_results = serper_search(
        f"{question} {profile.get('industry', '')} {location}", num=5
    )
    search_context = "\n".join([
        f"- {r.get('snippet', '')}" for r in search_results
    ])

    prompt = f"""
{context}

Live Research from {location}:
{search_context}

Founder Question: {question}

ANSWER RULES:
- Give specific answers for {location} market, not generic global advice
- If asked for a sales pitch: write the COMPLETE pitch fully, not advice about pitches
- If asked for a script: write the actual words to say
- If asked for a formula: give actual ingredients and quantities
- If asked for legal steps: give actual form names, fees in rupees, and timelines
- Use real platform names, real company names, real numbers
- Format: One sharp summary line. Then numbered steps. Then 2 specific actions this week.
- Maximum 400 words unless writing a full document
"""

    reply = ask_groq(prompt, system=system, max_tokens=700)
    return jsonify({"reply": reply, "agent": agent_type, "success": True})

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
    trends = "\n".join([f"- {r.get('snippet', '')}" for r in search_results])

    prompt = f"""
{build_context(user, profile)}

Current trends in {location} on {platform}:
{trends}

Generate a {days}-day content calendar for {platform} targeting {location} audience.

For each day:
- Day number and exact best posting time for {location} timezone
- Content type: educational, story, data, controversy, product showcase, or founder journey
- Complete post caption ready to copy and paste — not a template, actual words
- 5 hashtags relevant to {location} and industry
- One specific engagement hook or question to end the post

Make all content specific to {profile.get('product', '')} targeting customers in {location}.
Reference local trends, local competitors, local events where relevant.
4 value posts for every 1 promotional post.
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
        ),
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
        "time": datetime.now().strftime("%I:%M %p")
    })

@app.route("/")
def home():
    try:
        return open("dashboard.html", encoding="utf-8").read()
    except:
        return "<h1>FounderOS</h1><p>dashboard.html not found</p>"

setup_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, port=port, host="0.0.0.0")
