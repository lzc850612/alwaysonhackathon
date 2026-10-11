"""Demo data: fictional sponsors, hackers, teams and projects, with dates relative to now."""
import json
import random

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


if __name__ == "__main__":
    import os
    import sys
    from server import ROOT, init_db
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "aoh.db")
    if os.path.exists(path):
        sys.exit(f"{path} already exists — delete it first to reseed.")
    init_db(path)
    seed(path)
    print(f"Seeded {path}")


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
