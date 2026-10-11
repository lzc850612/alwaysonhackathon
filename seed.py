"""Demo data: fictional sponsors, hackers, teams and projects, with dates relative to now."""
import json
import random
import re
from datetime import datetime, timezone

from db import is_postgres
from server import DAY, connect, ensure_open_sprint, now

SPONSORS = [
    # handle, org, tagline, website, product_url, color
    ("nimbus", "Nimbus Cloud", "Serverless GPUs in one command.", "https://example.com/nimbus",
     "https://example.com/nimbus/start", "#2f80ed"),
    ("vectorly", "Vectorly", "The vector database that fits in a laptop.", "https://example.com/vectorly",
     "https://example.com/vectorly/free", "#e8590c"),
    ("paypilot", "PayPilot", "Payments APIs for weekend projects.", "https://example.com/paypilot",
     "https://example.com/paypilot/sandbox", "#0ca678"),
    ("sensei", "Sensei Voice", "Realtime speech, any language.", "https://example.com/sensei",
     "https://example.com/sensei/keys", "#d6336c"),
]

# key: sponsor handle, title, summary, prize, tags, start offset (days), length (days)
CHALLENGES = [
    ("nimbus", "Ship an AI agent on Nimbus", "Deploy an agent that does real work — on serverless GPUs.",
     "$3,000 + $10k Nimbus credits", ["ai", "agents", "python", "infra"], -3, 10),
    ("vectorly", "Search Everything", "Build semantic search over a dataset nobody has indexed yet.",
     "$2,000 + Vectorly Pro for a year", ["search", "ai", "data", "rag"], -1, 7),
    ("sensei", "Talk To It", "Voice-first apps: accessibility, language learning, games.",
     "$1,500 + mechanical keyboards", ["voice", "accessibility", "mobile", "ai"], 2, 7),
    ("paypilot", "Fintech for Students", "Make money less painful for students.",
     "$2,500 + PayPilot swag", ["fintech", "web", "payments"], -14, 7),
]

HACKERS = [
    # handle, name, skills, interests, tz, bio
    ("ada", "Ada Okafor", ["python", "pytorch", "ml"], ["ai", "agents", "research"], 1, "ML student, loves small models."),
    ("ben", "Ben Tran", ["react", "typescript", "design"], ["web", "accessibility"], -5, "Frontend + Figma."),
    ("chen", "Chen Wei", ["go", "kubernetes", "infra"], ["infra", "agents"], 8, "Makes things fast and boring."),
    ("dani", "Dani Morales", ["figma", "design", "product"], ["voice", "accessibility"], -6, "Product designer. Talks to users."),
    ("eli", "Eli Novak", ["swift", "ios", "mobile"], ["mobile", "voice"], 1, "iOS dev, weekend musician."),
    ("fatima", "Fatima Zahra", ["python", "data", "sql"], ["data", "search", "rag"], 0, "Data engineer who likes messy CSVs."),
    ("gus", "Gus Lindqvist", ["rust", "wasm", "infra"], ["search", "infra"], 1, "Rustacean. Will rewrite it in Rust."),
    ("hana", "Hana Kim", ["react", "node", "web"], ["fintech", "web"], 9, "Full-stack, first hackathon was 2023."),
    ("ivan", "Ivan Petrov", ["python", "fastapi", "backend"], ["ai", "fintech"], 3, "Backend APIs and coffee."),
    ("jules", "Jules Martin", ["pitching", "product", "marketing"], ["fintech", "web"], 1, "I make the demo video."),
    ("kofi", "Kofi Mensah", ["android", "kotlin", "mobile"], ["mobile", "accessibility"], 0, "Android + Compose."),
    ("lena", "Lena Fischer", ["ml", "nlp", "python"], ["voice", "ai", "rag"], 2, "NLP grad student."),
    ("mo", "Mo Rahman", ["node", "typescript", "backend"], ["agents", "web"], -8, "Bootcamp grad, ships fast."),
    ("nora", "Nora Silva", ["data", "visualization", "d3"], ["data", "search"], -3, "Charts or it didn't happen."),
]

# owner, challenge index, team name, idea, looking_for, members
TEAMS = [
    ("ada", 0, "Agent Smiths", "An agent that triages GitHub issues and drafts fixes.", ["react", "design"], ["chen"]),
    ("fatima", 1, "Needle", "Semantic search over every city council meeting transcript.", ["react", "design"], ["gus"]),
    ("mo", 0, "Inbox Zero Bot", "Email agent that negotiates meeting times for you.", ["python", "ml"], []),
    ("eli", 2, "Polyglot Parrot", "Practice conversations with a voice tutor.", ["ml", "design"], []),
    ("hana", 3, "SplitSmart", "Roommate bill-splitting with auto reminders.", [], ["ivan", "jules"]),
]

PROJECTS = [
    # team index, title, description, votes from
    (4, "SplitSmart", "Snap a receipt, split it, and PayPilot nudges whoever hasn't paid.", ["ada", "ben", "chen", "dani"]),
    (1, "Needle (WIP)", "Ask questions across 4,000 hours of council meetings. Early demo.", ["ben", "ivan"]),
]


def sponsor_user(db, handle):
    return db.execute("SELECT id FROM users WHERE handle=?", (handle,)).fetchone()[0]


def seed(db_path):
    db = connect(db_path)
    t = now()
    rng = random.Random(42)
    sponsor_ids = {}
    for handle, org, tagline, website, product, color in SPONSORS:
        sid = db.execute("INSERT INTO sponsors(name,tagline,website,product_url,color,created_at) VALUES(?,?,?,?,?,?)",
                         (org, tagline, website, product, color, t)).lastrowid
        sponsor_ids[handle] = sid
        db.execute("INSERT INTO users(handle,name,role,sponsor_id,looking,created_at) VALUES(?,?,?,?,0,?)",
                   (handle, f"{org} DevRel", "sponsor", sid, t))
    user_ids = {}
    for handle, name, skills, interests, tz, bio in HACKERS:
        user_ids[handle] = db.execute(
            "INSERT INTO users(handle,name,bio,skills,interests,tz,created_at) VALUES(?,?,?,?,?,?,?)",
            (handle, name, bio, json.dumps(skills), json.dumps(interests), tz, t - rng.randint(1, 60) * DAY)).lastrowid
    challenge_ids = []
    for key, title, summary, prize, tags, start, length in CHALLENGES:
        starts = t + start * DAY - (t % 3600)
        description = (f"{summary}\n\nUse at least one {SPONSORS[[s[0] for s in SPONSORS].index(key)][1]} API. "
                       "Judging: usefulness (40%), technical depth (30%), demo (30%). "
                       "Office hours with the sponsor team every Tuesday and Thursday on Discord.")
        challenge_ids.append(db.execute(
            "INSERT INTO challenges(sponsor_id,title,summary,description,prize,tags,resource_url,max_team,starts_at,ends_at,created_at)"
            " VALUES(?,?,?,?,?,?,?,4,?,?,?)",
            (sponsor_ids[key], title, summary, description, prize, json.dumps(tags),
             f"https://example.com/{key}/docs", starts, starts + length * DAY, t)).lastrowid)
    team_ids = []
    for owner, ci, name, idea, looking_for, members in TEAMS:
        tid = db.execute("INSERT INTO teams(challenge_id,name,idea,looking_for,max_size,owner_id,created_at) VALUES(?,?,?,?,4,?,?)",
                         (challenge_ids[ci], name, idea, json.dumps(looking_for), user_ids[owner], t - rng.randint(1, 48) * 3600)).lastrowid
        team_ids.append(tid)
        for i, h in enumerate([owner] + members):
            db.execute("INSERT INTO members(team_id,user_id,joined_at) VALUES(?,?,?)", (tid, user_ids[h], t - 3600 + i))
            db.execute("UPDATE users SET looking=0 WHERE id=?", (user_ids[h],))
    for ti, title, desc, voters in PROJECTS:
        sid = db.execute("INSERT INTO submissions(team_id,challenge_id,title,description,repo_url,demo_url,created_at)"
                         " VALUES(?,?,?,?,?,?,?)",
                         (team_ids[ti], challenge_ids[TEAMS[ti][1]], title, desc, "https://github.com/example/demo",
                          "https://example.com/demo", t - DAY)).lastrowid
        for v in voters:
            db.execute("INSERT INTO votes(submission_id,user_id) VALUES(?,?)", (sid, user_ids[v]))
    # Two people still looking get a pending invite / request so the inbox isn't empty.
    db.execute("INSERT INTO requests(team_id,user_id,kind,message,created_at) VALUES(?,?,?,?,?)",
               (team_ids[0], user_ids["ben"], "invite", "We need a frontend wizard!", t - 7200))
    db.execute("INSERT INTO requests(team_id,user_id,kind,message,created_at) VALUES(?,?,?,?,?)",
               (team_ids[2], user_ids["lena"], "join", "NLP person here — I can do the email parsing.", t - 3600))
    # Sponsor analytics: a couple of weeks of page views and product clicks.
    viewers = list(user_ids.values()) + [None] * 6
    for ci in challenge_ids:
        for _ in range(rng.randint(120, 260)):
            ts = t - rng.randint(0, 13 * DAY)
            db.execute("INSERT INTO events(challenge_id,kind,user_id,created_at) VALUES(?,?,?,?)",
                       (ci, "view", rng.choice(viewers), ts))
            if rng.random() < 0.18:
                db.execute("INSERT INTO events(challenge_id,kind,user_id,created_at) VALUES(?,?,?,?)",
                           (ci, "click", rng.choice(viewers), ts + 30))
    # A judge, with scores on the shipped projects.
    judge = db.execute("INSERT INTO users(handle,name,bio,role,looking,created_at) VALUES(?,?,?,?,0,?)",
                       ("judy", "Judy Hopps", "Staff engineer, judging since 2019.", "judge", t)).lastrowid
    first_sub = db.execute("SELECT id FROM submissions ORDER BY id LIMIT 1").fetchone()[0]
    db.execute("INSERT INTO scores(submission_id,judge_id,innovation,technical,design,impact,comment,created_at)"
               " VALUES(?,?,8,7,9,8,'Clean demo, real problem.',?)", (first_sub, judge, t - 3600))
    # Demos: one live right now, one later today.
    for ti, title, offset, dur in [(0, "Agent Smiths — first working demo", -300, 30), (1, "Needle: search 4,000 hours of meetings", 3 * 3600, 20)]:
        did = db.execute("INSERT INTO demos(team_id,title,zoom_url,starts_at,duration_min,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
                         (team_ids[ti], title, "https://us02web.zoom.us/j/1234567890", t + offset, dur, user_ids[TEAMS[ti][0]], t - 600)).lastrowid
        for v in rng.sample(list(user_ids.values()), 5):
            db.execute("INSERT OR IGNORE INTO demo_watchers(demo_id,user_id) VALUES(?,?)", (did, v))
        for uid in list(user_ids.values()) + [judge]:
            db.execute("INSERT INTO notifications(user_id,text,link,created_at) VALUES(?,?,?,?)",
                       (uid, f"📺 Live demo {'now' if offset <= 0 else 'soon'}: {TEAMS[ti][2]} — {title}", "#/demos", t - 600))
    # Sponsor support: credits, office hours, API access.
    perks = [("nimbus", 0, "credits", "$500 GPU credits per team", "Auto-applied when you sign up with your team email."),
             ("nimbus", 0, "office_hours", "Office hours: Tue & Thu 5pm UTC", "Drop in on Zoom with Nimbus engineers."),
             ("vectorly", 1, "api_access", "Vectorly Pro key — free for the challenge", "Unlimited collections, 10M vectors."),
             ("sensei", 2, "mentorship", "1:1 with a voice-AI engineer", "Book a 20-minute slot before you start."),
             ("paypilot", 3, "swag", "Sandbox + hoodie for every finisher", "")]
    for key, ci, kind, title, details in perks:
        pid = db.execute("INSERT INTO perks(sponsor_id,challenge_id,kind,title,details,link,created_at) VALUES(?,?,?,?,?,?,?)",
                         (sponsor_ids[key], challenge_ids[ci], kind, title, details, f"https://example.com/{key}/perk", t)).lastrowid
        for v in rng.sample(list(user_ids.values()), rng.randint(2, 7)):
            db.execute("INSERT INTO perk_claims(perk_id,user_id,created_at) VALUES(?,?,?)", (pid, v, t - rng.randint(0, 5 * DAY)))
    db.execute("INSERT INTO notifications(user_id,text,link,created_at) VALUES(?,?,?,?)",
               (user_ids["ben"], "@ada invited you to join Agent Smiths", "#/inbox", t - 7200))
    # The floor: ship-log updates and help requests (one solved, so karma shows up).
    floor = [("ada", "update", "Agent can now open PRs on its own 🤖 — next: making it write tests.", [], 5 * 3600, None),
             ("fatima", "help", "Anyone know how to chunk 3-hour transcripts without losing speaker turns?", ["nlp", "rag"], 4 * 3600, "lena"),
             ("hana", "update", "SplitSmart demo video is up. 90 seconds, no jump cuts.", [], 3 * 3600, None),
             ("eli", "help", "Getting a 401 from the speech API on iOS only — works in curl.", ["swift", "ios", "voice"], 40 * 60, None)]
    for handle, kind, body, tags, ago, helper in floor:
        team = db.execute("SELECT m.team_id FROM members m WHERE m.user_id=? LIMIT 1", (user_ids[handle],)).fetchone()
        pid = db.execute("INSERT INTO posts(user_id,kind,text,tags,team_id,resolved_by,created_at) VALUES(?,?,?,?,?,?,?)",
                         (user_ids[handle], kind, body, json.dumps(tags), team[0] if team else None,
                          user_ids[helper] if helper else None, t - ago)).lastrowid
        if helper:
            db.execute("INSERT INTO replies(post_id,user_id,text,created_at) VALUES(?,?,?,?)",
                       (pid, user_ids[helper], "Split on speaker changes first, then window to ~500 tokens with 1 turn of overlap.", t - ago + 600))
        for v in rng.sample(list(user_ids.values()), rng.randint(1, 6)):
            db.execute("INSERT OR IGNORE INTO highfives(post_id,user_id) VALUES(?,?)", (pid, v))
    db.execute("INSERT INTO replies(post_id,user_id,text,created_at) VALUES(?,?,?,?)",
               (pid, sponsor_user(db, "sensei"), "Sensei DevRel here — iOS needs the key in a header, not the query string. Hop in office hours?", t - 20 * 60))
    ensure_open_sprint(db)
    db.commit()
    db.close()


def seed_live_ritual(db_path, occ):
    """Demo mode: give a ritual that's live right now some people and activity, so it doesn't open empty."""
    db = connect(db_path)
    t = now()
    users = {r["handle"]: r["id"] for r in db.execute("SELECT id, handle FROM users")}
    for h in ["ada", "chen", "fatima", "hana", "ivan", "lena", "kofi", "nimbus"]:
        if h in users:
            db.execute("INSERT OR REPLACE INTO ritual_presence(occ_id,user_id,last_seen) VALUES(?,?,?)", (occ["id"], users[h], t + 600))
    if occ["key"] == "kickoff":
        for author, idea, fans in [("lena", "A voice tutor that corrects your accent in real time", ["kofi", "eli"]),
                                   ("mo", "Agent that turns meeting notes into GitHub issues", ["ivan"]),
                                   ("nora", "Map every public bench in your city from street-view photos", [])]:
            iid = db.execute("INSERT INTO ideas(occ_id,user_id,text,created_at) VALUES(?,?,?,?)",
                             (occ["id"], users[author], idea, t - 120)).lastrowid
            for f in fans:
                db.execute("INSERT OR IGNORE INTO idea_fans(idea_id,user_id) VALUES(?,?)", (iid, users[f]))
    elif occ["key"] == "checkin":
        for i, (h, msg) in enumerate([("ada", "Agent now writes its own tests — 14 passing"), ("hana", "Receipt OCR works on crumpled receipts"),
                                      ("fatima", "Indexed 1,200 hours of council meetings")]):
            db.execute("INSERT INTO posts(user_id,kind,text,tags,ritual,created_at) VALUES(?,?,?,?,?,?)",
                       (users[h], "update", msg, "[]", occ["id"], t - 90 + i * 20))
            for d in range(1, 3 + i):  # earlier nights, so streaks show up
                db.execute("INSERT INTO posts(user_id,kind,text,tags,ritual,created_at) VALUES(?,?,?,?,?,?)",
                           (users[h], "update", "Shipped a little more", "[]", f"checkin-emea-{t - d * DAY}", t - d * DAY))
    elif occ["key"] == "closing":
        teams = db.execute("SELECT s.team_id FROM submissions s ORDER BY s.created_at").fetchall()
        for pos, r in enumerate(teams):
            db.execute("INSERT OR IGNORE INTO lineup(occ_id,team_id,position,zoom_url,created_at) VALUES(?,?,?,?,?)",
                       (occ["id"], r["team_id"], pos, "https://us02web.zoom.us/j/5550001111", t))
    db.commit()
    db.close()


# ---------- builders directory data (ported from the companion "Always-On Hackathon" Next.js demo) ----------

BUILDER_PEOPLE = [
    ("Maya Chen", "San Francisco", "United States"), ("Arjun Mehta", "Bengaluru", "India"), ("Sofia Costa", "Lisbon", "Portugal"),
    ("James Okafor", "Lagos", "Nigeria"), ("Yuki Tanaka", "Tokyo", "Japan"), ("Lena Fischer", "Berlin", "Germany"),
    ("Mateo Rivera", "Mexico City", "Mexico"), ("Amara Mensah", "Accra", "Ghana"), ("Noah Williams", "Toronto", "Canada"),
    ("Priya Shah", "Mumbai", "India"), ("Oliver Hughes", "London", "United Kingdom"), ("Isabella Silva", "São Paulo", "Brazil"),
    ("Minji Park", "Seoul", "South Korea"), ("Ahmed Hassan", "Cairo", "Egypt"), ("Emma Dubois", "Paris", "France"),
    ("Luca Rossi", "Milan", "Italy"), ("Aisha Khan", "Karachi", "Pakistan"), ("Ethan Brooks", "Austin", "United States"),
    ("Chloe Nguyen", "Sydney", "Australia"), ("Daniel Kim", "Vancouver", "Canada"), ("Fatima Alami", "Casablanca", "Morocco"),
    ("Hugo Martins", "Porto", "Portugal"), ("Zara Patel", "Nairobi", "Kenya"), ("Lucas Berg", "Stockholm", "Sweden"),
    ("Anika Weber", "Munich", "Germany"), ("Samuel Adeyemi", "Abuja", "Nigeria"), ("Valentina Cruz", "Buenos Aires", "Argentina"),
    ("Wei Zhang", "Singapore", "Singapore"), ("Elena Popova", "Tallinn", "Estonia"), ("Rafael Santos", "Rio de Janeiro", "Brazil"),
    ("Grace Mwangi", "Mombasa", "Kenya"), ("Theo Wilson", "Melbourne", "Australia"), ("Nadia Rahman", "Dhaka", "Bangladesh"),
    ("Alex Morgan", "New York", "United States"), ("Camila Torres", "Bogotá", "Colombia"), ("Omar Said", "Dubai", "United Arab Emirates"),
    ("Eva Novak", "Prague", "Czech Republic"), ("Ben Taylor", "Manchester", "United Kingdom"), ("Leila Haddad", "Tunis", "Tunisia"),
    ("Finn Jensen", "Copenhagen", "Denmark"),
]
B_ROLES = ["Full-stack engineer", "AI / ML engineer", "Product designer", "Backend engineer", "Frontend engineer"]
B_STACKS = [["React", "TypeScript", "Next.js"], ["Python", "PyTorch", "AI"], ["Figma", "UX research", "Design systems"],
            ["Go", "PostgreSQL", "Docker"], ["React", "CSS", "Accessibility"]]
B_DOMAINS = ["AI for good", "Climate tech", "Developer tools", "Healthcare", "Education"]
B_OFFSETS = {"United States": -7, "India": 5.5, "Portugal": 1, "Nigeria": 1, "Japan": 9, "Germany": 2, "Mexico": -6, "Ghana": 0,
             "Canada": -4, "United Kingdom": 1, "Brazil": -3, "South Korea": 9, "Egypt": 3, "France": 2, "Italy": 2, "Pakistan": 5,
             "Australia": 10, "Morocco": 1, "Kenya": 3, "Sweden": 2, "Argentina": -3, "Singapore": 8, "Estonia": 3, "Bangladesh": 6,
             "Colombia": -5, "United Arab Emirates": 4, "Czech Republic": 2, "Tunisia": 1, "Denmark": 2}
B_TEAMS = ["Carbon Collective", "Neural Neighbors", "Open Garden", "CareLoop Crew", "Learning Lab", "Signal Studio",
           "Civic Stack", "Ocean Watch", "Access All", "Local Loop", "Bright Grid", "Paper Plane"]
B_TEAM_DESC = ["Making climate action accessible to everyone.", "Building useful AI with a human perspective.",
               "Turning a weekend idea into lasting impact."]
B_PROJECTS = ["Carbon Compass", "CareLoop", "Signal Studio", "LearnLocal", "Open Garden", "Ocean Lens", "Access Kit", "Civic Voice"]
B_PROJECT_DESC = ["Your personal guide to a lighter footprint.", "Connecting communities with the care they need.",
                  "A calmer way to find the signal in the noise.", "Small tools. Meaningful everyday impact."]
B_SPONSORS = [  # name, challenge title, prize, tech, colour, domain the challenge serves
    ("Nova AI", "Build AI that gives back", "$12,000", "AI SDK", "#5b5ef0", "AI for good"),
    ("Orbit Cloud", "Connect the next billion", "$8,000", "Edge functions", "#2f9fd8", "Healthcare"),
    ("Verdant", "Code for a cooler planet", "$10,000", "Climate API", "#2fa37a", "Climate tech"),
    ("Pixel Forge", "Make the web more accessible", "$5,000", "Design toolkit", "#d0629b", "Education"),
    ("Relay Labs", "Reimagine developer workflows", "$15,000", "Workflow SDK", "#e08a3a", "Developer tools"),
]
B_HACKATHONS = ["Build a Better Tomorrow", "The AI Frontier", "Climate / Code", "Berlin Build Weekend", "Design for Everyone",
                "Bengaluru Builders Jam", "Open Source Odyssey", "New York Zero to One"]
B_HACK_THEMES = ["AI for good", "AI for good", "Climate tech", "Developer tools", "Education", "Healthcare", "Developer tools", "AI for good"]

# Profile details for the original demo hackers, so they appear properly in the directory.
ORIGINAL_PROFILES = {
    "ada": ("AI / ML engineer", "London", "United Kingdom", "Mid-level", 20, "Remote", "Teammates"),
    "ben": ("Frontend engineer", "New York", "United States", "Mid-level", 15, "Remote", "Teammates"),
    "chen": ("Backend engineer", "Shanghai", "China", "Senior", 10, "Remote", "Teammates"),
    "dani": ("Product designer", "Chicago", "United States", "Senior", 15, "Hybrid", "Co-founders"),
    "eli": ("Frontend engineer", "Berlin", "Germany", "Mid-level", 20, "Remote", "Teammates"),
    "fatima": ("Backend engineer", "Lisbon", "Portugal", "Mid-level", 20, "Remote", "Teammates"),
    "gus": ("Backend engineer", "Stockholm", "Sweden", "Senior", 10, "Remote", "Teammates"),
    "hana": ("Full-stack engineer", "Seoul", "South Korea", "Early career", 30, "Hybrid", "Co-founders"),
    "ivan": ("Backend engineer", "Moscow", "Russia", "Mid-level", 15, "Remote", "Teammates"),
    "jules": ("Product designer", "Paris", "France", "Early career", 10, "Local", "Teammates"),
    "kofi": ("Frontend engineer", "Accra", "Ghana", "Mid-level", 20, "Remote", "Teammates"),
    "lena": ("AI / ML engineer", "Berlin", "Germany", "Early career", 20, "Remote", "Teammates"),
    "mo": ("Full-stack engineer", "Austin", "United States", "Early career", 30, "Remote", "Co-founders"),
    "nora": ("Frontend engineer", "Toronto", "Canada", "Mid-level", 15, "Hybrid", "Teammates"),
}


def _handle(db, name):
    first = re.sub(r"[^a-z]", "", name.split()[0].lower())
    full = re.sub(r"[^a-z]", "", name.lower())
    for h in (first, full):
        if not db.execute("SELECT 1 FROM users WHERE handle=?", (h,)).fetchone():
            return h
    return full + "x"


def seed_builders(db_path):
    """Add the builders-directory demo data. Idempotent, and safe to run on an existing database."""
    db = connect(db_path)
    if db.execute("SELECT 1 FROM users WHERE handle='alex'").fetchone():
        db.close()
        return False
    t = now()
    day = lambda y, m, d: int(datetime(y, m, d, 17, tzinfo=timezone.utc).timestamp())
    for handle, prof in ORIGINAL_PROFILES.items():
        db.execute("UPDATE users SET title=?,city=?,country=?,experience=?,hours=?,collab=?,seeking=? WHERE handle=?", prof + (handle,))
    # The demo identity from the other app, so you can try it as "Alex Rivers".
    db.execute("INSERT INTO users(handle,name,bio,skills,interests,tz,looking,role,created_at,title,city,country,experience,hours,collab,seeking)"
               " VALUES('alex','Alex Rivers',?,?,?,-4,1,'hacker',?,'Full-stack engineer','New York','United States','Mid-level',20,'Remote','Teammates')",
               ("Building thoughtful products with curious people.", json.dumps(["React", "TypeScript", "Next.js"]),
                json.dumps(["AI for good", "Climate tech"]), t))
    ids = []
    for i, (name, city, country) in enumerate(BUILDER_PEOPLE):
        existing = db.execute("SELECT id FROM users WHERE name=?", (name,)).fetchone()
        if existing:  # e.g. our own Lena Fischer: keep her, she's a separate demo persona
            ids.append(None)
            continue
        dom = B_DOMAINS[i % 5]
        bio = [f"I turn ambitious ideas into useful products. Currently exploring {dom.lower()} and looking for thoughtful people to ship with.",
               f"Curious builder with a love for small experiments and big problems. I bring {B_STACKS[i % 5][0]} expertise and a collaborative mindset.",
               f"From weekend prototypes to shipped products, I care about making technology useful. Let's build something in {dom.lower()}."][i % 3]
        ids.append(db.execute(
            "INSERT INTO users(handle,name,bio,skills,interests,tz,looking,role,created_at,title,city,country,experience,hours,collab,seeking)"
            " VALUES(?,?,?,?,?,?,1,'hacker',?,?,?,?,?,?,?,?)",
            (_handle(db, name), name, bio, json.dumps(B_STACKS[i % 5]), json.dumps([dom, B_DOMAINS[(i + 2) % 5]]),
             round(B_OFFSETS.get(country, 0)), t - (40 - i) * 3600, B_ROLES[i % 5], city, country,
             ["Senior", "Mid-level", "Early career"][i % 3], [15, 20, 10, 30][i % 4], ["Remote", "Hybrid", "Local"][i % 3],
             "Co-founders" if i % 2 == 0 else "Teammates")).lastrowid)
    # Five sponsors, each with a live challenge for one problem domain.
    by_domain = {}
    for name, title, prize, tech, color, dom in B_SPONSORS:
        sid = db.execute("INSERT INTO sponsors(name,tagline,website,product_url,color,created_at) VALUES(?,?,?,?,?,?)",
                         (name, f"The fictional {tech} for builders.", "https://example.com/" + name.lower().replace(" ", ""),
                          "https://example.com/" + name.lower().replace(" ", "") + "/start", color, t)).lastrowid
        db.execute("INSERT INTO users(handle,name,role,sponsor_id,looking,created_at) VALUES(?,?,?,?,0,?)",
                   (_handle(db, name.replace(" ", "")), f"{name} DevRel", "sponsor", sid, t))
        by_domain[dom] = db.execute(
            "INSERT INTO challenges(sponsor_id,title,summary,description,prize,tags,resource_url,max_team,starts_at,ends_at,created_at,format,location)"
            " VALUES(?,?,?,?,?,?,?,4,?,?,?,'Online','Worldwide')",
            (sid, title, f"Build an inventive prototype using the fictional {tech}.",
             f"Build an inventive prototype using the fictional {tech}. Bring a team, a fresh perspective, and a willingness to "
             "experiment. Judging: usefulness, craft and demo.", prize, json.dumps([dom.lower(), tech.lower()]),
             "https://example.com/docs", t - 2 * DAY, t + 12 * DAY, t)).lastrowid
    # Eight scheduled hackathons (online and in person).
    sponsor_ids = {n: db.execute("SELECT id FROM sponsors WHERE name=?", (n,)).fetchone()[0] for n, *_ in B_SPONSORS}
    for i, title in enumerate(B_HACKATHONS):
        start = day(2026, 11, 7 + i * 2)
        in_person = i in (3, 5, 7)
        db.execute("INSERT INTO challenges(sponsor_id,title,summary,description,prize,tags,max_team,starts_at,ends_at,created_at,format,location)"
                   " VALUES(?,?,?,?,?,?,4,?,?,?,?,?)",
                   (sponsor_ids[["Nova AI", "Orbit Cloud", "Verdant", "Pixel Forge"][i % 4]], title,
                    f"A weekend hackathon for {B_HACK_THEMES[i].lower()} · 2–4 builders.",
                    "A fictional demo event. Form a team, build over the weekend, and demo on Sunday.",
                    ["$25,000", "$50,000", "$15,000", "$10,000"][i % 4], json.dumps([B_HACK_THEMES[i].lower()]),
                    start, start + 2 * DAY, t, "In person" if in_person else "Online",
                    {3: "Berlin", 5: "Bengaluru", 7: "New York"}.get(i, "Worldwide")))
    # Twelve teams on the domain challenges; the first eight have shipped projects.
    for i, name in enumerate(B_TEAMS):
        cid = by_domain[B_DOMAINS[i % 5]]
        members = [m for m in (ids[i], ids[i + 10] if i + 10 < len(ids) else None) if m]
        members = [m for m in members if not db.execute(
            "SELECT 1 FROM members mm JOIN teams tt ON tt.id=mm.team_id WHERE mm.user_id=? AND tt.challenge_id=?", (m, cid)).fetchone()]
        if not members:
            continue
        tid = db.execute("INSERT INTO teams(challenge_id,name,idea,looking_for,max_size,owner_id,created_at) VALUES(?,?,?,?,4,?,?)",
                         (cid, name, B_TEAM_DESC[i % 3], json.dumps(B_STACKS[(i + 2) % 5][:2]), members[0], t - (12 - i) * 3600)).lastrowid
        for k, m in enumerate(members):
            db.execute("INSERT INTO members(team_id,user_id,joined_at) VALUES(?,?,?)", (tid, m, t - 3600 + k))
            db.execute("UPDATE users SET looking=0 WHERE id=?", (m,))
        if i < len(B_PROJECTS):
            db.execute("INSERT INTO submissions(team_id,challenge_id,title,description,repo_url,demo_url,created_at,stack)"
                       " VALUES(?,?,?,?,?,?,?,?)",
                       (tid, cid, B_PROJECTS[i], B_PROJECT_DESC[i % 4], "https://github.com/example/" + B_PROJECTS[i].lower().replace(" ", "-"),
                        "", t - (8 - i) * 1800, json.dumps(B_STACKS[i % 5][:2])))
    db.commit()
    db.close()
    return True


# ---------- hackathon pages: a real Luma event, partner sponsors, practical info ----------

# Partner offers transcribed from MLH sponsor flyers. Links are the ones printed on the cards.
FLYER_SPONSORS = [  # sponsor, colour, tier, offer, details, link
    ("Major League Hacking", "#2b4c9b", "Organizer partner", "Global Hack Week",
     "A monthly, week-long hacker festival: workshops, mini-events and live demos to level up your skills by building.",
     "https://ghw.mlh.io"),
    ("Major League Hacking", "#2b4c9b", "Organizer partner", "Host a Hack Day for your community",
     "Get up to $350 in funding for food, snacks and drinks for hacker club events. Apply, secure a venue, and MLH and partners send prizes, stickers and swag.",
     "https://mlh.link/hack-day-application"),
    ("Snowflake", "#29b5e8", "Data partner", "A Data Playground for Your Next Hack",
     "Start a free 120-day Snowflake trial, build a chat app in minutes, and explore Snowflake's AI features.",
     "https://mlh.link/snowflake"),
    ("Google · Gemma", "#4285f4", "Prize challenge", "Best Use of Gemma 4",
     "Build with Gemma 4, Google's open-weight model family. Details and judging on the MLH hack page.",
     "https://hack.mlh.com"),
    ("DigitalOcean", "#0069ff", "Cloud partner", "Open Source AI Hackerfest",
     "Ship an open-source AI project on DigitalOcean for the Hackerfest challenge.",
     "https://mlh.link/hf26-digitalocean"),
    ("DEV Community", "#1a1a1a", "Community partner", "Share what you built",
     "Write up your project on DEV so other builders can learn from it.",
     "https://dev.to"),
]

IN_PERSON_INFO = """Doors open 9:00 · Opening ceremony 9:30 · Hacking starts 10:00 · Demos 17:00 · Awards 18:30.
Bring a laptop, charger and photo ID. Wi-Fi details are shared at check-in.
Teams of up to 4. Code you submit must be written during the event.
Mentors walk the floor every hour — raise your hand on The Floor if you're stuck.
Code of conduct: be kind, be inclusive, and look after each other."""
ONLINE_INFO = """Kickoff stream on day one, then build from anywhere.
Teams of up to 4, across any time zones — use your Team Room for calls and the build lab.
Post progress on The Floor and raise your hand when you're stuck; mentors and sponsor engineers watch it.
Submit a repo or demo link before the deadline, then demo live on your team's stage.
Code of conduct: be kind, be inclusive, and look after each other."""
IN_PERSON_FOOD = [
    {"time": "9:00", "item": "Breakfast", "detail": "Bagels, fruit, oatmeal, coffee and tea"},
    {"time": "12:30", "item": "Lunch", "detail": "Build-your-own bowls · vegan, vegetarian and gluten-free options"},
    {"time": "15:30", "item": "Snack break", "detail": "Fruit, granola bars, cold brew"},
    {"time": "18:30", "item": "Dinner at awards", "detail": "Pizza (incl. vegan & GF) and soft drinks"},
]
ONLINE_FOOD = [{"time": "All weekend", "item": "Snack stipend", "detail": "Hack Day-style food funding for hacker clubs that host a watch party"}]


def seed_hackathons(db_path):
    """Hackathon-page demo content. Idempotent; safe on an existing database."""
    db = connect(db_path)
    if db.execute("SELECT 1 FROM challenges WHERE title='AI Engineer New York Hackathon'").fetchone():
        db.close()
        return False
    t = now()
    # A real event (listing from the organizer's Luma page). Only facts from that listing — no invented logistics.
    host = db.execute("INSERT INTO sponsors(name,tagline,website,product_url,color,created_at) VALUES(?,?,?,?,?,?)",
                      ("AI Engineer & Major League Hacking", "Organizers of the AI Engineer New York Hackathon",
                       "https://ai.engineer", "", "#6750eb", t)).lastrowid
    start = int(datetime(2026, 10, 11, 13, 0, tzinfo=timezone.utc).timestamp())  # 9 AM EDT
    db.execute("INSERT INTO challenges(sponsor_id,title,summary,description,prize,tags,max_team,starts_at,ends_at,created_at,format,location,"
               "luma_url,luma_status,time_label,is_real,verified_at,info) VALUES(?,?,?,?,?,?,4,?,?,?,?,?,?,?,?,1,?,?)",
               (host, "AI Engineer New York Hackathon", "Build with fellow AI engineers, get mentor support, and demo your project.",
                "Build with fellow AI engineers, get mentor support, and demo your project. The exact address is shared through organizer registration.",
                "Free admission", json.dumps(["ai engineering"]), start, start + 12 * 3600, t, "In person", "New York",
                "https://luma.com/AIEngineerNYHackathon", "Waitlist", "9 AM–9 PM EDT", "Oct 11, 2026",
                "Registration, the venue address, schedule and food are managed by the organizers on Luma — check there for current details."))
    # Partner sponsors from the flyers, attached to the fictional hackathons and this week's Open Sprint.
    sponsor_ids = {}
    for name, color, *_ in FLYER_SPONSORS:
        if name not in sponsor_ids:
            row = db.execute("SELECT id FROM sponsors WHERE name=?", (name,)).fetchone()
            sponsor_ids[name] = row[0] if row else db.execute(
                "INSERT INTO sponsors(name,tagline,website,product_url,color,created_at) VALUES(?,?,?,?,?,?)",
                (name, "", "", "", color, t)).lastrowid
    targets = [r[0] for r in db.execute("SELECT id FROM challenges WHERE is_real=0 AND ends_at>? AND (sponsor_id IS NULL OR title IN (?,?,?,?,?,?,?,?))",
                                        (t, *["Build a Better Tomorrow", "The AI Frontier", "Climate / Code", "Berlin Build Weekend",
                                              "Design for Everyone", "Bengaluru Builders Jam", "Open Source Odyssey", "New York Zero to One"]))]
    for cid in targets:
        for k, (name, _color, tier, offer, details, link) in enumerate(FLYER_SPONSORS):
            db.execute("INSERT OR IGNORE INTO hackathon_sponsors(challenge_id,sponsor_id,tier,offer,details,link,sort) VALUES(?,?,?,?,?,?,?)",
                       (cid, sponsor_ids[name], tier, offer, details, link, k + 1))
    # Practical info and food for every fictional hackathon.
    for r in db.execute("SELECT id, format, location FROM challenges WHERE is_real=0").fetchall():
        in_person = r["format"] == "In person"
        db.execute("UPDATE challenges SET info=?, food=?, venue=?, time_label=? WHERE id=? AND info=''",
                   (IN_PERSON_INFO if in_person else ONLINE_INFO, json.dumps(IN_PERSON_FOOD if in_person else ONLINE_FOOD),
                    f"Demo venue, {r['location']} (fictional)" if in_person else "", "9 AM–7 PM local" if in_person else "", r["id"]))
    # Fictional attendees for the fictional hackathons, so each one has people to meet.
    looking = [r[0] for r in db.execute("SELECT id FROM users WHERE role='hacker' AND looking=1 AND handle!='alex' ORDER BY id")]
    rng = random.Random(7)
    for cid in [r[0] for r in db.execute("SELECT id FROM challenges WHERE is_real=0 AND ends_at>?", (t,))]:
        for uid in rng.sample(looking, min(8, len(looking))):
            db.execute("INSERT OR IGNORE INTO attendees(challenge_id,user_id,created_at) VALUES(?,?,?)", (cid, uid, t - rng.randint(1, 72) * 3600))
    # A finished hackathon gets a recorded demo, so its page has demos to browse.
    past = db.execute("SELECT s.team_id, s.title, ch.ends_at FROM submissions s JOIN challenges ch ON ch.id=s.challenge_id"
                      " WHERE ch.ends_at<? ORDER BY s.id LIMIT 1", (t,)).fetchone()
    if past:
        db.execute("INSERT INTO demos(team_id,title,zoom_url,starts_at,duration_min,created_by,created_at,stage,ended_at,peak)"
                   " VALUES(?,?,?,?,?,NULL,?,1,?,?)", (past["team_id"], f"{past['title']} — final demo", "",
                                                       past["ends_at"] - 3600, 20, past["ends_at"] - 3600, past["ends_at"] - 2400, 23))
    db.commit()
    db.close()
    return True


def seed_all(target):
    """Load all demo data that isn't there yet. Safe to call from several processes at once (serverless cold starts):
    on Postgres they take turns behind an advisory lock, and each step checks its own marker."""
    lock = connect(target)
    try:
        if is_postgres(target):
            lock.execute("SELECT pg_advisory_lock(424243)")
        fresh = not lock.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        lock.commit()
        if fresh:
            seed(target)
        seed_builders(target)
        seed_hackathons(target)
        return fresh
    finally:
        if is_postgres(target):
            lock.execute("SELECT pg_advisory_unlock(424243)")
            lock.commit()
        lock.close()


if __name__ == "__main__":
    # One-off: python3 seed.py "$DATABASE_URL"   (or a SQLite path)
    import os
    import sys

    from server import init_db

    from server import ROOT

    target = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DATABASE_URL") or os.path.join(ROOT, "data", "aoh.db")
    init_db(target)
    print("Seeded a fresh database." if seed_all(target) else "Topped up demo data (the database already had users).")
