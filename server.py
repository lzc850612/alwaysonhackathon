#!/usr/bin/env python3
"""Always-On Hackathon — a zero-dependency server (Python 3.8+ stdlib only).

Run:  python3 server.py [--port 8000] [--db data/aoh.db] [--no-seed]
"""
import argparse
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import traceback
from collections import Counter
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
DAY = 86400
COOKIE = "aoh_session"
# Judges sign up with a shared code the organizers hand out (set AOH_JUDGE_CODE in production).
JUDGE_CODE = os.environ.get("AOH_JUDGE_CODE", "judge-demo")
SCORE_FIELDS = ("innovation", "technical", "design", "impact")
ROOM_WINDOW = 10  # seconds; room clients heartbeat every ~1.5s
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,40}$")
HERE_WINDOW = 120  # seconds since last heartbeat that still counts as "on the floor"
PERK_KINDS = ("credits", "mentorship", "office_hours", "api_access", "swag")
HOUSE = {"id": None, "name": "Always-On HQ", "tagline": "The weekly open sprint — build anything.",
         "color": "#7c5cff", "website": "", "product_url": ""}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sponsors(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, tagline TEXT DEFAULT '', website TEXT DEFAULT '',
  product_url TEXT DEFAULT '', color TEXT DEFAULT '#7c5cff', created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, handle TEXT UNIQUE NOT NULL, name TEXT NOT NULL, bio TEXT DEFAULT '',
  skills TEXT DEFAULT '[]', interests TEXT DEFAULT '[]', tz INTEGER DEFAULT 0, looking INTEGER DEFAULT 1,
  role TEXT DEFAULT 'hacker', sponsor_id INTEGER REFERENCES sponsors(id), created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS challenges(
  id INTEGER PRIMARY KEY, sponsor_id INTEGER REFERENCES sponsors(id), title TEXT NOT NULL, summary TEXT DEFAULT '',
  description TEXT DEFAULT '', prize TEXT DEFAULT '', tags TEXT DEFAULT '[]', resource_url TEXT DEFAULT '',
  max_team INTEGER DEFAULT 4, starts_at INTEGER NOT NULL, ends_at INTEGER NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS teams(
  id INTEGER PRIMARY KEY, challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
  name TEXT NOT NULL, idea TEXT DEFAULT '', looking_for TEXT DEFAULT '[]', max_size INTEGER DEFAULT 4,
  owner_id INTEGER NOT NULL REFERENCES users(id), created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS members(
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id),
  joined_at INTEGER NOT NULL, PRIMARY KEY(team_id, user_id));
CREATE TABLE IF NOT EXISTS requests(
  id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL, message TEXT DEFAULT '',
  status TEXT DEFAULT 'pending', created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS submissions(
  id INTEGER PRIMARY KEY, team_id INTEGER UNIQUE NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE, title TEXT NOT NULL,
  description TEXT DEFAULT '', repo_url TEXT DEFAULT '', demo_url TEXT DEFAULT '', created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS votes(
  submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id),
  PRIMARY KEY(submission_id, user_id));
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, user_id INTEGER, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS demos(
  id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE, title TEXT NOT NULL,
  zoom_url TEXT NOT NULL, starts_at INTEGER NOT NULL, duration_min INTEGER DEFAULT 15, created_by INTEGER,
  created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS demo_watchers(
  demo_id INTEGER NOT NULL REFERENCES demos(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id),
  PRIMARY KEY(demo_id, user_id));
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, text TEXT NOT NULL,
  link TEXT DEFAULT '', read INTEGER DEFAULT 0, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS scores(
  submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE, judge_id INTEGER NOT NULL REFERENCES users(id),
  innovation INTEGER NOT NULL, technical INTEGER NOT NULL, design INTEGER NOT NULL, impact INTEGER NOT NULL,
  comment TEXT DEFAULT '', created_at INTEGER NOT NULL, PRIMARY KEY(submission_id, judge_id));
CREATE TABLE IF NOT EXISTS perks(
  id INTEGER PRIMARY KEY, sponsor_id INTEGER NOT NULL REFERENCES sponsors(id), challenge_id INTEGER REFERENCES challenges(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, title TEXT NOT NULL, details TEXT DEFAULT '', link TEXT DEFAULT '', created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS perk_claims(
  perk_id INTEGER NOT NULL REFERENCES perks(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id),
  created_at INTEGER NOT NULL, PRIMARY KEY(perk_id, user_id));
CREATE TABLE IF NOT EXISTS presence(
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, status TEXT DEFAULT '',
  since INTEGER NOT NULL, last_seen INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS posts(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL, text TEXT NOT NULL,
  tags TEXT DEFAULT '[]', team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL, resolved_by INTEGER REFERENCES users(id),
  created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS replies(
  id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id), text TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS highfives(
  post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id),
  PRIMARY KEY(post_id, user_id));
CREATE TABLE IF NOT EXISTS team_log(
  id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id), text TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS room_presence(
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE, session TEXT NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id), cam INTEGER DEFAULT 0, talking INTEGER DEFAULT 0,
  last_seen INTEGER NOT NULL, PRIMARY KEY(team_id, session));
CREATE TABLE IF NOT EXISTS signals(
  id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  from_session TEXT NOT NULL, to_session TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS transcripts(
  id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id), text TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS ritual_presence(
  occ_id TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, last_seen INTEGER NOT NULL,
  PRIMARY KEY(occ_id, user_id));
CREATE TABLE IF NOT EXISTS reactions(
  occ_id TEXT NOT NULL, slot INTEGER NOT NULL, emoji TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(occ_id, slot, emoji));
CREATE TABLE IF NOT EXISTS ideas(
  id INTEGER PRIMARY KEY, occ_id TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id), text TEXT NOT NULL,
  team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS idea_fans(
  idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id),
  PRIMARY KEY(idea_id, user_id));
CREATE TABLE IF NOT EXISTS lineup(
  occ_id TEXT NOT NULL, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE, position INTEGER NOT NULL,
  zoom_url TEXT NOT NULL, created_at INTEGER NOT NULL, PRIMARY KEY(occ_id, team_id), UNIQUE(occ_id, position));
CREATE TABLE IF NOT EXISTS stage_presence(
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE, session TEXT NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id), role TEXT NOT NULL, screen INTEGER DEFAULT 0, cam INTEGER DEFAULT 0,
  mic INTEGER DEFAULT 0, last_seen INTEGER NOT NULL, PRIMARY KEY(team_id, session));
CREATE TABLE IF NOT EXISTS stage_questions(
  id INTEGER PRIMARY KEY, demo_id INTEGER NOT NULL REFERENCES demos(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id), text TEXT NOT NULL, answered INTEGER DEFAULT 0, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS build_versions(
  id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE, note TEXT NOT NULL,
  files TEXT NOT NULL, user_id INTEGER REFERENCES users(id), created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS agent_runs(
  id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id), prompt TEXT NOT NULL, status TEXT NOT NULL, mode TEXT NOT NULL,
  summary TEXT DEFAULT '', files TEXT, error TEXT DEFAULT '', base_version INTEGER, created_at INTEGER NOT NULL,
  finished_at INTEGER);
CREATE INDEX IF NOT EXISTS idx_build_versions_team ON build_versions(team_id, id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_team ON agent_runs(team_id, id);
CREATE TABLE IF NOT EXISTS saved_builders(
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, builder_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL, PRIMARY KEY(user_id, builder_id));
CREATE TABLE IF NOT EXISTS connections(
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, other_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL, PRIMARY KEY(user_id, other_id));
CREATE TABLE IF NOT EXISTS onboarding(
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  steps TEXT NOT NULL DEFAULT '[]', PRIMARY KEY(team_id, user_id));
CREATE TABLE IF NOT EXISTS hackathon_sponsors(
  challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE, sponsor_id INTEGER NOT NULL REFERENCES sponsors(id),
  tier TEXT DEFAULT 'Partner', offer TEXT NOT NULL DEFAULT '', details TEXT DEFAULT '', link TEXT DEFAULT '', sort INTEGER DEFAULT 0,
  PRIMARY KEY(challenge_id, sponsor_id, offer));
CREATE TABLE IF NOT EXISTS attendees(
  challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL, PRIMARY KEY(challenge_id, user_id));
CREATE TABLE IF NOT EXISTS ritual_notices(occ_id TEXT NOT NULL, phase TEXT NOT NULL, PRIMARY KEY(occ_id, phase));
CREATE INDEX IF NOT EXISTS idx_transcripts_team ON transcripts(team_id, id);
CREATE INDEX IF NOT EXISTS idx_signals_to ON signals(team_id, to_session, id);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, read);
CREATE INDEX IF NOT EXISTS idx_events_challenge ON events(challenge_id, kind, created_at);
CREATE INDEX IF NOT EXISTS idx_teams_challenge ON teams(challenge_id);
"""


def now():
    return int(time.time())


class Raw:
    """A non-JSON response body (e.g. a calendar file)."""
    def __init__(self, data, content_type, filename=None):
        self.data, self.content_type, self.filename = data, content_type, filename


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


# Columns added after the first release; ALTER is a no-op error on databases that already have them.
MIGRATIONS = [
    "ALTER TABLE teams ADD COLUMN preview_url TEXT DEFAULT ''",
    "ALTER TABLE teams ADD COLUMN preview_by INTEGER",
    "ALTER TABLE teams ADD COLUMN preview_at INTEGER",
    "ALTER TABLE members ADD COLUMN doing TEXT DEFAULT ''",
    "ALTER TABLE members ADD COLUMN doing_at INTEGER",
    "ALTER TABLE room_presence ADD COLUMN caption TEXT DEFAULT ''",
    "ALTER TABLE posts ADD COLUMN ritual TEXT",
    "ALTER TABLE teams ADD COLUMN status TEXT DEFAULT 'building'",
    "ALTER TABLE teams ADD COLUMN shipped_at INTEGER",
    "ALTER TABLE demos ADD COLUMN stage INTEGER DEFAULT 0",
    "ALTER TABLE demos ADD COLUMN ended_at INTEGER",
    "ALTER TABLE demos ADD COLUMN peak INTEGER DEFAULT 0",
    # Builder profile fields (the directory and Buildmate filter on these).
    "ALTER TABLE users ADD COLUMN title TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN city TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN country TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN experience TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN hours INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN collab TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN seeking TEXT DEFAULT ''",
    "ALTER TABLE challenges ADD COLUMN format TEXT DEFAULT 'Online'",
    "ALTER TABLE challenges ADD COLUMN location TEXT DEFAULT 'Worldwide'",
    "ALTER TABLE submissions ADD COLUMN stack TEXT DEFAULT '[]'",
    # Hackathon details: Luma for in-person events, practical info, food, the opening video.
    "ALTER TABLE challenges ADD COLUMN luma_url TEXT DEFAULT ''",
    "ALTER TABLE challenges ADD COLUMN luma_status TEXT DEFAULT ''",
    "ALTER TABLE challenges ADD COLUMN time_label TEXT DEFAULT ''",
    "ALTER TABLE challenges ADD COLUMN venue TEXT DEFAULT ''",
    "ALTER TABLE challenges ADD COLUMN info TEXT DEFAULT ''",
    "ALTER TABLE challenges ADD COLUMN food TEXT DEFAULT '[]'",
    "ALTER TABLE challenges ADD COLUMN video_url TEXT DEFAULT ''",
    "ALTER TABLE challenges ADD COLUMN is_real INTEGER DEFAULT 0",
    "ALTER TABLE challenges ADD COLUMN verified_at TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN linkedin TEXT DEFAULT ''",
    "ALTER TABLE presence ADD COLUMN challenge_id INTEGER",
    "ALTER TABLE posts ADD COLUMN challenge_id INTEGER",
]
ROLE_TITLES = ("Full-stack engineer", "AI / ML engineer", "Product designer", "Backend engineer", "Frontend engineer")
EXPERIENCE = ("Early career", "Mid-level", "Senior")
COLLAB = ("Remote", "Hybrid", "Local")
SEEKING = ("Teammates", "Co-founders")


def init_db(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    db = connect(path)
    db.executescript(SCHEMA)
    for sql in MIGRATIONS:
        try:
            db.execute(sql)
        except sqlite3.OperationalError:
            pass
    ensure_open_sprint(db)
    db.commit()
    db.close()


def ensure_open_sprint(db, t=None):
    """The 'always-on' guarantee: a house Open Sprint runs every ISO week (Mon 00:00 UTC → next Mon)."""
    t = t or now()
    d = datetime.fromtimestamp(t, timezone.utc)
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - timedelta(days=d.weekday())
    starts_at = int(start.timestamp())
    if db.execute("SELECT 1 FROM challenges WHERE sponsor_id IS NULL AND starts_at=?", (starts_at,)).fetchone():
        return
    db.execute(
        "INSERT INTO challenges(sponsor_id,title,summary,description,prize,tags,max_team,starts_at,ends_at,created_at)"
        " VALUES(NULL,?,?,?,?,?,4,?,?,?)",
        (f"Open Sprint — week of {start.strftime('%b %d')}",
         "Build anything in 7 days. New sprint every Monday.",
         "No theme, no gatekeeping. Form a team (or go solo), ship something real by Sunday night UTC, "
         "and post it for the community vote. The top three projects get featured on the home page.",
         "Featured project + swag pack", json.dumps(["open", "anything", "beginner-friendly"]),
         starts_at, starts_at + 7 * DAY, now()))
    new_id = db.execute("SELECT id FROM challenges WHERE sponsor_id IS NULL AND starts_at=?", (starts_at,)).fetchone()[0]
    prev = db.execute("SELECT id FROM challenges WHERE sponsor_id IS NULL AND starts_at<? ORDER BY starts_at DESC LIMIT 1",
                      (starts_at,)).fetchone()
    if prev and db.execute("SELECT name FROM sqlite_master WHERE name='hackathon_sponsors'").fetchone():
        db.execute("INSERT OR IGNORE INTO hackathon_sponsors(challenge_id,sponsor_id,tier,offer,details,link,sort)"
                   " SELECT ?,sponsor_id,tier,offer,details,link,sort FROM hackathon_sponsors WHERE challenge_id=?", (new_id, prev[0]))


# ---------- input helpers ----------

HANDLE_RE = re.compile(r"^[a-z0-9_-]{2,24}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def text(body, key, required=False, max_len=2000):
    v = body.get(key)
    v = "" if v is None else str(v).strip()
    if required and not v:
        raise ApiError(400, f"{key.replace('_', ' ')} is required")
    return v[:max_len]


def url_field(body, key):
    v = text(body, key, max_len=500)
    if v and not re.match(r"^https?://", v, re.I):
        raise ApiError(400, f"{key.replace('_', ' ')} must start with http:// or https://")
    return v


def int_field(body, key, default, lo, hi):
    try:
        v = int(body.get(key, default))
    except (TypeError, ValueError):
        raise ApiError(400, f"{key} must be a number")
    if not lo <= v <= hi:
        raise ApiError(400, f"{key} must be between {lo} and {hi}")
    return v


def clean_list(v, limit=12):
    if v is None:
        return []
    if isinstance(v, str):
        v = v.split(",")
    if not isinstance(v, list):
        raise ApiError(400, "expected a list")
    out, seen = [], set()
    for x in v:
        x = str(x).strip()[:32]
        if x and x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out[:limit]


def jl(s):
    return json.loads(s or "[]")


def lower_set(xs):
    return {x.lower() for x in xs}


def notify(db, user_ids, message, link=""):
    t = now()
    db.executemany("INSERT INTO notifications(user_id,text,link,created_at) VALUES(?,?,?,?)",
                   [(u, message, link, t) for u in set(user_ids) if u])


def zoom_url(body, key):
    v = url_field(body, key)
    host = (urlparse(v).hostname or "").lower()
    if not v.lower().startswith("https://") or not re.search(r"(^|\.)zoom\.(us|com)$", host):
        raise ApiError(400, "Use a Zoom meeting link (https://…zoom.us/j/…)")
    return v


# ---------- serializers ----------

def user_out(r):
    return {"id": r["id"], "handle": r["handle"], "name": r["name"], "bio": r["bio"],
            "skills": jl(r["skills"]), "interests": jl(r["interests"]), "tz": r["tz"],
            "looking": bool(r["looking"]), "role": r["role"], "sponsor_id": r["sponsor_id"],
            "title": r["title"] or "", "city": r["city"] or "", "country": r["country"] or "",
            "experience": r["experience"] or "", "hours": r["hours"] or 0, "collab": r["collab"] or "",
            "seeking": r["seeking"] or "", "linkedin": r["linkedin"] or ""}


def linkedin_url(b, current=""):
    if "linkedin" not in b:
        return current or ""
    v = text(b, "linkedin", max_len=200)
    if v and not re.match(r"^https://([a-z]{2,3}\.)?(www\.)?linkedin\.com/(in|company)/[A-Za-z0-9_%-]+/?$", v):
        raise ApiError(400, "LinkedIn must look like https://www.linkedin.com/in/your-name")
    return v


def luma_link(b):
    v = url_field(b, "luma_url")
    host = (urlparse(v).hostname or "").lower()
    if v and (not v.lower().startswith("https://") or host not in ("luma.com", "lu.ma", "www.luma.com")):
        raise ApiError(400, "Luma link must be an https://luma.com/… or https://lu.ma/… event page")
    return v


def profile_fields(b, current=None):
    """Optional builder-profile fields; each must be one of the known values (or blank)."""
    cur = current or {}
    def pick(key, options):
        v = text(b, key, max_len=40) if key in b else (cur[key] if key in cur.keys() else "") or ""
        if v and v not in options:
            raise ApiError(400, f"{key} must be one of: {', '.join(options)}")
        return v
    hours = int_field(b, "hours", (cur["hours"] if "hours" in cur.keys() else 0) or 0, 0, 80)
    return (text(b, "title", max_len=60) if "title" in b else (cur["title"] if "title" in cur.keys() else "") or "",
            text(b, "city", max_len=60) if "city" in b else (cur["city"] if "city" in cur.keys() else "") or "",
            text(b, "country", max_len=60) if "country" in b else (cur["country"] if "country" in cur.keys() else "") or "",
            pick("experience", EXPERIENCE), hours, pick("collab", COLLAB), pick("seeking", SEEKING))


def status_of(starts_at, ends_at, t):
    return "upcoming" if t < starts_at else "live" if t < ends_at else "past"


CHALLENGE_SQL = """
SELECT c.*, s.name AS s_name, s.tagline AS s_tagline, s.color AS s_color, s.website AS s_website,
  s.product_url AS s_product_url,
  (SELECT COUNT(*) FROM teams t WHERE t.challenge_id=c.id) AS team_count,
  (SELECT COUNT(*) FROM members m JOIN teams t ON t.id=m.team_id WHERE t.challenge_id=c.id) AS hacker_count,
  (SELECT COUNT(*) FROM submissions x WHERE x.challenge_id=c.id) AS submission_count
FROM challenges c LEFT JOIN sponsors s ON s.id=c.sponsor_id
"""


def challenge_out(r, t=None):
    t = t or now()
    sponsor = dict(HOUSE) if r["sponsor_id"] is None else {
        "id": r["sponsor_id"], "name": r["s_name"], "tagline": r["s_tagline"], "color": r["s_color"],
        "website": r["s_website"], "product_url": r["s_product_url"]}
    return {"id": r["id"], "title": r["title"], "summary": r["summary"], "description": r["description"],
            "prize": r["prize"], "tags": jl(r["tags"]), "resource_url": r["resource_url"],
            "max_team": r["max_team"], "starts_at": r["starts_at"], "ends_at": r["ends_at"],
            "status": status_of(r["starts_at"], r["ends_at"], t), "sponsor": sponsor,
            "team_count": r["team_count"], "hacker_count": r["hacker_count"],
            "submission_count": r["submission_count"], "format": r["format"] or "Online",
            "location": r["location"] or "Worldwide", "luma_url": r["luma_url"] or "", "luma_status": r["luma_status"] or "",
            "time_label": r["time_label"] or "", "venue": r["venue"] or "", "info": r["info"] or "",
            "food": jl(r["food"]), "video_url": r["video_url"] or "", "is_real": bool(r["is_real"]),
            "verified_at": r["verified_at"] or ""}


def get_challenge(db, cid):
    r = db.execute(CHALLENGE_SQL + " WHERE c.id=?", (cid,)).fetchone()
    if not r:
        raise ApiError(404, "Challenge not found")
    return r


TEAM_SQL = """
SELECT t.*, c.title AS challenge_title, c.tags AS challenge_tags, c.starts_at AS c_starts, c.ends_at AS c_ends
FROM teams t JOIN challenges c ON c.id=t.challenge_id
"""


def team_members(db, team_id):
    return [user_out(m) for m in db.execute(
        "SELECT u.* FROM members mm JOIN users u ON u.id=mm.user_id WHERE mm.team_id=? ORDER BY mm.joined_at, u.id",
        (team_id,))]


def team_out(db, r, t=None):
    members = team_members(db, r["id"])
    return {"id": r["id"], "challenge_id": r["challenge_id"], "challenge_title": r["challenge_title"],
            "challenge_tags": jl(r["challenge_tags"]),
            "challenge_status": status_of(r["c_starts"], r["c_ends"], t or now()),
            "challenge_starts_at": r["c_starts"], "challenge_ends_at": r["c_ends"],
            "name": r["name"], "idea": r["idea"], "looking_for": jl(r["looking_for"]),
            "max_size": r["max_size"], "owner_id": r["owner_id"], "members": members,
            "status": r["status"] or "building", "shipped_at": r["shipped_at"],
            "open": len(members) < r["max_size"] and r["status"] != "shipped"}


def get_team(db, tid):
    r = db.execute(TEAM_SQL + " WHERE t.id=?", (tid,)).fetchone()
    if not r:
        raise ApiError(404, "Team not found")
    return r


def pending_team_ids(db, uid):
    return {r["team_id"] for r in db.execute(
        "SELECT team_id FROM requests WHERE user_id=? AND kind='join' AND status='pending'", (uid or -1,))}


def team_for_user_in_challenge(db, uid, cid):
    r = db.execute("SELECT t.id FROM members m JOIN teams t ON t.id=m.team_id WHERE m.user_id=? AND t.challenge_id=?",
                   (uid, cid)).fetchone()
    return r["id"] if r else None


# ---------- matching ----------

def fit(user, team, members, challenge_tags):
    """Score 0–100 for how well `user` fits `team`, plus human-readable reasons."""
    skills = lower_set(user["skills"])
    need = lower_set(team["looking_for"])
    have = set()
    for m in members:
        have |= lower_set(m["skills"])
    reasons = []

    covered = skills & need
    role = len(covered) / len(need) if need else 0.3
    if covered:
        reasons.append("Fills open role: " + ", ".join(sorted(covered)))

    fresh = skills - have
    comp = len(fresh) / len(skills) if skills else 0
    if fresh and not covered and comp >= 0.5:
        reasons.append("Adds skills the team lacks: " + ", ".join(sorted(fresh)[:3]))

    shared = lower_set(user["interests"]) & lower_set(challenge_tags)
    interest = min(1.0, len(shared) / 2)
    if shared:
        reasons.append("Into " + ", ".join(sorted(shared)))

    if members:
        avg = sum(m["tz"] for m in members) / len(members)
        diff = abs(user["tz"] - avg)
        diff = min(diff, 24 - diff)
        tz = 1 - min(diff, 12) / 12
        if diff <= 3:
            reasons.append("Overlapping timezones")
    else:
        tz = 0.5

    score = 0.5 * role + 0.2 * comp + 0.15 * interest + 0.15 * tz
    return round(score * 100), reasons


# ---------- routing ----------

ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


class Ctx:
    def __init__(self, db, user, body, query, srv=None):
        self.db, self.user, self.body, self.query, self.srv = db, user, body, query, srv
        self.after_commit = []  # callables to run once this request's writes are committed
        self.set_cookie = None  # token string, or "" to clear

    def me(self):
        if not self.user:
            raise ApiError(401, "Sign in first")
        return self.user

    def q(self, key, default=""):
        return self.query.get(key, [default])[0]


def new_session(c, uid):
    token = secrets.token_urlsafe(24)
    c.db.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)", (token, uid, now()))
    c.set_cookie = token


# --- auth & profile ---

@route("POST", "/api/signup")
def signup(c):
    b = c.body
    handle = text(b, "handle", True, 24).lower()
    if not HANDLE_RE.match(handle):
        raise ApiError(400, "Handle must be 2–24 characters: a–z, 0–9, _ or -")
    if c.db.execute("SELECT 1 FROM users WHERE handle=?", (handle,)).fetchone():
        raise ApiError(409, "That handle is taken")
    name = text(b, "name", True, 60)
    role = b.get("role") if b.get("role") in ("sponsor", "judge") else "hacker"
    if role == "judge" and not secrets.compare_digest(str(b.get("judge_code", "")), JUDGE_CODE):
        raise ApiError(403, "That judge code isn't right — ask the organizers for one")
    sponsor_id = None
    if role == "sponsor":
        color = text(b, "color", max_len=7) or "#ff6b35"
        if not COLOR_RE.match(color):
            raise ApiError(400, "color must look like #ff6b35")
        sponsor_id = c.db.execute(
            "INSERT INTO sponsors(name,tagline,website,product_url,color,created_at) VALUES(?,?,?,?,?,?)",
            (text(b, "org", True, 60), text(b, "tagline", max_len=140), url_field(b, "website"),
             url_field(b, "product_url"), color, now())).lastrowid
    uid = c.db.execute(
        "INSERT INTO users(handle,name,bio,skills,interests,tz,looking,role,sponsor_id,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (handle, name, text(b, "bio", max_len=280), json.dumps(clean_list(b.get("skills"))),
         json.dumps(clean_list(b.get("interests"))), int_field(b, "tz", 0, -12, 14),
         1 if role == "hacker" else 0, role, sponsor_id, now())).lastrowid
    c.db.execute("UPDATE users SET title=?,city=?,country=?,experience=?,hours=?,collab=?,seeking=? WHERE id=?",
                 profile_fields(b) + (uid,))
    new_session(c, uid)
    return 201, {"user": user_out(c.db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())}


@route("POST", "/api/login")
def login(c):
    # Demo auth: handle only. Production would use MyMLH OAuth (see README).
    handle = text(c.body, "handle", True, 24).lower().lstrip("@")
    r = c.db.execute("SELECT * FROM users WHERE handle=?", (handle,)).fetchone()
    if not r:
        raise ApiError(404, "No hacker with that handle — sign up instead?")
    new_session(c, r["id"])
    return 200, {"user": user_out(r)}


@route("POST", "/api/logout")
def logout(c):
    if c.user:
        c.db.execute("DELETE FROM sessions WHERE user_id=?", (c.user["id"],))
    c.set_cookie = ""
    return 200, {"ok": True}


@route("GET", "/api/me")
def me(c):
    if not c.user:
        return 200, {"user": None}
    u = user_out(c.user)
    u["inbox"] = c.db.execute(
        "SELECT COUNT(*) FROM requests r JOIN teams t ON t.id=r.team_id WHERE r.status='pending' AND "
        "((r.kind='join' AND t.owner_id=?) OR (r.kind='invite' AND r.user_id=?))",
        (u["id"], u["id"])).fetchone()[0]
    c.db.execute("UPDATE presence SET last_seen=? WHERE user_id=? AND last_seen>?", (now(), u["id"], now() - HERE_WINDOW))
    u["on_floor"] = c.db.execute("SELECT 1 FROM presence WHERE user_id=? AND last_seen>?",
                                 (u["id"], now() - HERE_WINDOW)).fetchone() is not None
    u["unread"] = c.db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0", (u["id"],)).fetchone()[0]
    # Teams in challenges that haven't ended, newest first: powers the "My team" nav link.
    u["teams"] = [{"id": r["id"], "name": r["name"], "challenge_title": r["challenge_title"]} for r in c.db.execute(
        "SELECT tm.id, tm.name, ch.title AS challenge_title FROM members m JOIN teams tm ON tm.id=m.team_id"
        " JOIN challenges ch ON ch.id=tm.challenge_id WHERE m.user_id=? AND ch.ends_at>? ORDER BY m.joined_at DESC",
        (u["id"], now()))]
    if u["sponsor_id"]:
        s = c.db.execute("SELECT * FROM sponsors WHERE id=?", (u["sponsor_id"],)).fetchone()
        u["sponsor"] = dict(s)
    return 200, {"user": u}


@route("POST", "/api/me")
def update_me(c):
    u, b = c.me(), c.body
    c.db.execute("UPDATE users SET name=?,bio=?,skills=?,interests=?,tz=?,looking=?,"
                 "title=?,city=?,country=?,experience=?,hours=?,collab=?,seeking=?,linkedin=? WHERE id=?",
                 (text(b, "name", True, 60), text(b, "bio", max_len=280), json.dumps(clean_list(b.get("skills"))),
                  json.dumps(clean_list(b.get("interests"))), int_field(b, "tz", u["tz"], -12, 14),
                  1 if b.get("looking") else 0) + profile_fields(b, u) + (linkedin_url(b, u["linkedin"]), u["id"]))
    return 200, {"user": user_out(c.db.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone())}


# --- discovery ---

@route("GET", "/api/stats")
def stats(c):
    t = now()
    one = lambda sql, *a: c.db.execute(sql, a).fetchone()[0]
    return 200, {
        "hackers": one("SELECT COUNT(*) FROM users WHERE role='hacker'"),
        "looking": one("SELECT COUNT(*) FROM users WHERE role='hacker' AND looking=1"),
        "teams": one("SELECT COUNT(*) FROM teams"),
        "live": one("SELECT COUNT(*) FROM challenges WHERE starts_at<=? AND ends_at>?", t, t),
        "submissions": one("SELECT COUNT(*) FROM submissions"),
        "sponsors": one("SELECT COUNT(*) FROM sponsors"),
        "here_now": one("SELECT COUNT(*) FROM presence WHERE last_seen>?", t - HERE_WINDOW),
        "open_help": one("SELECT COUNT(*) FROM posts WHERE kind='help' AND resolved_by IS NULL AND created_at>?", t - 2 * DAY),
    }


@route("GET", "/api/challenges")
def list_challenges(c):
    ensure_open_sprint(c.db)
    t = now()
    want = c.q("status")
    rows = [challenge_out(r, t) for r in c.db.execute(CHALLENGE_SQL + " ORDER BY c.ends_at")]
    if want:
        rows = [r for r in rows if r["status"] == want]
    if want == "past":
        rows.reverse()
    return 200, {"challenges": rows}


@route("GET", r"/api/challenges/(\d+)")
def challenge_detail(c, cid):
    cid = int(cid)
    ch = challenge_out(get_challenge(c.db, cid))
    uid = c.user["id"] if c.user else None
    c.db.execute("INSERT INTO events(challenge_id,kind,user_id,created_at) VALUES(?,?,?,?)", (cid, "view", uid, now()))
    teams = [team_out(c.db, r) for r in c.db.execute(TEAM_SQL + " WHERE t.challenge_id=? ORDER BY t.created_at DESC", (cid,))]
    subs = []
    for r in c.db.execute(
            "SELECT s.*, t.name AS team_name, (SELECT COUNT(*) FROM votes v WHERE v.submission_id=s.id) AS votes,"
            " EXISTS(SELECT 1 FROM votes v WHERE v.submission_id=s.id AND v.user_id=?) AS voted,"
            " (SELECT ROUND(AVG((x.innovation+x.technical+x.design+x.impact)/4.0),1) FROM scores x WHERE x.submission_id=s.id) AS judge_score,"
            " (SELECT COUNT(*) FROM scores x WHERE x.submission_id=s.id) AS judge_count"
            " FROM submissions s JOIN teams t ON t.id=s.team_id WHERE s.challenge_id=? ORDER BY votes DESC, s.created_at",
            (uid or -1, cid)):
        d = dict(r)
        d["voted"] = bool(d["voted"])
        subs.append(d)
    my_team = team_for_user_in_challenge(c.db, uid, cid) if uid else None
    pending = sorted(pending_team_ids(c.db, uid))
    perks = perks_for(c.db, ch, uid)
    demos = demo_rows(c.db, uid, "WHERE t.challenge_id=?", (cid,))
    # People: everyone who joined the hackathon or is on one of its teams.
    on_team = {}
    for t in teams:
        for m in t["members"]:
            on_team[m["id"]] = {"id": t["id"], "name": t["name"]}
    people = []
    for r in c.db.execute("SELECT u.* FROM users u WHERE u.id IN (SELECT user_id FROM attendees WHERE challenge_id=?"
                          " UNION SELECT m.user_id FROM members m JOIN teams t ON t.id=m.team_id WHERE t.challenge_id=?)"
                          " ORDER BY u.name", (cid, cid)):
        p = user_out(r)
        p["team"] = on_team.get(r["id"])
        people.append(p)
    sponsors = [dict(r) for r in c.db.execute(
        "SELECT s.id, s.name, s.color, s.tagline, s.website, hs.tier, hs.offer, hs.details, hs.link FROM hackathon_sponsors hs"
        " JOIN sponsors s ON s.id=hs.sponsor_id WHERE hs.challenge_id=? ORDER BY hs.sort, s.name", (cid,))]
    attending = bool(uid and c.db.execute("SELECT 1 FROM attendees WHERE challenge_id=? AND user_id=?", (cid, uid)).fetchone())
    return 200, {"challenge": ch, "teams": teams, "submissions": subs, "my_team_id": my_team,
                 "pending_team_ids": pending, "perks": perks, "demos": demos, "people": people,
                 "sponsors": sponsors, "attending": attending or bool(my_team)}


@route("POST", r"/api/challenges/(\d+)/attend")
def attend(c, cid):
    """Join (or leave) a hackathon's participant list. Team members are always counted as attending."""
    u = c.me()
    ch = get_challenge(c.db, int(cid))
    if u["role"] != "hacker":
        raise ApiError(403, "Only hacker accounts join hackathons")
    if ch["ends_at"] <= now():
        raise ApiError(400, "This hackathon has ended")
    if c.db.execute("DELETE FROM attendees WHERE challenge_id=? AND user_id=?", (ch["id"], u["id"])).rowcount:
        return 200, {"attending": False}
    c.db.execute("INSERT INTO attendees(challenge_id,user_id,created_at) VALUES(?,?,?)", (ch["id"], u["id"], now()))
    return 200, {"attending": True}


@route("POST", r"/api/challenges/(\d+)/click")
def challenge_click(c, cid):
    ch = challenge_out(get_challenge(c.db, int(cid)))
    c.db.execute("INSERT INTO events(challenge_id,kind,user_id,created_at) VALUES(?,?,?,?)",
                 (ch["id"], "click", c.user["id"] if c.user else None, now()))
    return 200, {"url": ch["sponsor"]["product_url"] or ch["resource_url"] or ch["sponsor"]["website"]}


@route("GET", "/api/sponsors")
def list_sponsors(c):
    rows = c.db.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM challenges c WHERE c.sponsor_id=s.id) AS challenge_count"
        " FROM sponsors s ORDER BY s.name").fetchall()
    return 200, {"sponsors": [dict(r) for r in rows]}


@route("GET", "/api/people")
def people(c):
    q, skill = c.q("q").lower(), c.q("skill").lower()
    rows = []
    for r in c.db.execute("SELECT * FROM users WHERE role='hacker' ORDER BY looking DESC, created_at DESC"):
        u = user_out(r)
        if c.q("looking") == "1" and not u["looking"]:
            continue
        if skill and skill not in lower_set(u["skills"]):
            continue
        if q and q not in (u["name"] + " " + u["handle"] + " " + u["bio"] + " " + " ".join(u["skills"])).lower():
            continue
        rows.append(u)
    return 200, {"people": rows[:100]}


@route("GET", r"/api/people/([a-z0-9_-]+)")
def person(c, handle):
    r = c.db.execute("SELECT * FROM users WHERE handle=?", (handle,)).fetchone()
    if not r:
        raise ApiError(404, "Hacker not found")
    teams = [team_out(c.db, t) for t in c.db.execute(
        TEAM_SQL + " JOIN members m ON m.team_id=t.id WHERE m.user_id=? ORDER BY t.created_at DESC", (r["id"],))]
    person = user_out(r)
    person["helped"] = helped_count(c.db, r["id"])
    return 200, {"person": person, "teams": teams}


# --- teams ---

@route("GET", "/api/teams")
def list_teams(c):
    t = now()
    sql, args = TEAM_SQL + " WHERE c.ends_at>?", [t]
    if c.q("challenge_id"):
        sql += " AND t.challenge_id=?"
        args.append(int(c.q("challenge_id")))
    teams = [team_out(c.db, r, t) for r in c.db.execute(sql + " ORDER BY t.created_at DESC", args)]
    if c.q("open") == "1":
        teams = [x for x in teams if x["open"]]
    pending = pending_team_ids(c.db, c.user["id"] if c.user else None)
    for x in teams:
        x["requested"] = x["id"] in pending
    return 200, {"teams": teams}


@route("GET", r"/api/teams/(\d+)")
def team_detail(c, tid):
    r = get_team(c.db, int(tid))
    team = team_out(c.db, r)
    out = {"team": team, "submission": None, "requests": [], "my_request": None}
    s = c.db.execute("SELECT * FROM submissions WHERE team_id=?", (r["id"],)).fetchone()
    if s:
        out["submission"] = dict(s)
    out["demos"] = demo_rows(c.db, c.user["id"] if c.user else None, "WHERE d.team_id=?", (r["id"],))
    if c.user:
        uid = c.user["id"]
        if uid == r["owner_id"]:
            out["requests"] = [{"id": x["rid"], "kind": x["kind"], "message": x["message"], "user": user_out(x)}
                               for x in c.db.execute(
                "SELECT rq.id AS rid, rq.kind, rq.message, u.* FROM requests rq JOIN users u ON u.id=rq.user_id"
                " WHERE rq.team_id=? AND rq.status='pending' ORDER BY rq.created_at", (r["id"],))]
        mr = c.db.execute("SELECT id, kind, status FROM requests WHERE team_id=? AND user_id=? AND status='pending'",
                          (r["id"], uid)).fetchone()
        out["my_request"] = dict(mr) if mr else None
        out["my_team_in_challenge"] = team_for_user_in_challenge(c.db, uid, r["challenge_id"])
    return 200, out


@route("POST", "/api/teams")
def create_team(c):
    tid = make_team(c.db, c.me(), c.body)
    return 201, {"team": team_out(c.db, get_team(c.db, tid))}


def make_team(db, u, b):
    if u["role"] != "hacker":
        raise ApiError(403, "Only hacker accounts can form teams")
    ch = get_challenge(db, int_field(b, "challenge_id", 0, 1, 10 ** 9))
    if ch["ends_at"] <= now():
        raise ApiError(400, "That challenge has ended")
    if team_for_user_in_challenge(db, u["id"], ch["id"]):
        raise ApiError(409, "You're already on a team for this challenge")
    tid = db.execute(
        "INSERT INTO teams(challenge_id,name,idea,looking_for,max_size,owner_id,created_at) VALUES(?,?,?,?,?,?,?)",
        (ch["id"], text(b, "name", True, 50), text(b, "idea", max_len=600), json.dumps(clean_list(b.get("looking_for"), 6)),
         int_field(b, "max_size", ch["max_team"], 1, ch["max_team"]), u["id"], now())).lastrowid
    db.execute("INSERT INTO members(team_id,user_id,joined_at) VALUES(?,?,?)", (tid, u["id"], now()))
    return tid


@route("POST", r"/api/teams/(\d+)")
def update_team(c, tid):
    u, b = c.me(), c.body
    r = get_team(c.db, int(tid))
    if r["owner_id"] != u["id"]:
        raise ApiError(403, "Only the team owner can edit the team")
    count = len(team_members(c.db, r["id"]))
    max_team = c.db.execute("SELECT max_team FROM challenges WHERE id=?", (r["challenge_id"],)).fetchone()[0]
    c.db.execute("UPDATE teams SET name=?, idea=?, looking_for=?, max_size=? WHERE id=?",
                 (text(b, "name", True, 50), text(b, "idea", max_len=600), json.dumps(clean_list(b.get("looking_for"), 6)),
                  int_field(b, "max_size", r["max_size"], max(1, count), max_team), r["id"]))
    return 200, {"team": team_out(c.db, get_team(c.db, r["id"]))}


def check_can_join(db, team_row, uid):
    if db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()[0] != "hacker":
        raise ApiError(403, "Only hacker accounts can join teams")
    if team_row["status"] == "shipped":
        raise ApiError(409, "This team has shipped its project — the roster is closed")
    if team_row["c_ends"] <= now():
        raise ApiError(400, "That challenge has ended")
    if team_for_user_in_challenge(db, uid, team_row["challenge_id"]):
        raise ApiError(409, "Already on a team for this challenge")
    if len(team_members(db, team_row["id"])) >= team_row["max_size"]:
        raise ApiError(409, "Team is full")


def accept_request(db, rq, team, auto=False):
    """Add the requester/invitee to the team. Callers have already checked who may decide."""
    # Take the write lock before checking capacity, so two simultaneous approvals can't both see a free spot.
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    team = get_team(db, team["id"])
    check_can_join(db, team, rq["user_id"])
    db.execute("INSERT INTO members(team_id,user_id,joined_at) VALUES(?,?,?)", (team["id"], rq["user_id"], now()))
    db.execute("UPDATE requests SET status='accepted' WHERE id=?", (rq["id"],))
    # Joining one team withdraws the user's other pending requests in the same challenge.
    db.execute("UPDATE requests SET status='withdrawn' WHERE user_id=? AND status='pending' AND team_id IN"
               " (SELECT id FROM teams WHERE challenge_id=?)", (rq["user_id"], team["challenge_id"]))
    handle = db.execute("SELECT handle FROM users WHERE id=?", (rq["user_id"],)).fetchone()[0]
    log_team(db, team["id"], rq["user_id"], "joined the team" + (" (auto-approved)" if auto else ""))
    if rq["kind"] == "join":
        notify(db, [rq["user_id"]], f"You're in! {team['name']} accepted your request", f"#/t/{team['id']}/room")
        if auto:
            notify(db, [team["owner_id"]], f"@{handle} joined {team['name']} (auto-approved in demo mode)", f"#/t/{team['id']}")
    else:
        notify(db, [team["owner_id"]], f"@{handle} accepted your invite to {team['name']}", f"#/t/{team['id']}")


def auto_approve(db_path, rid):
    """Demo mode: approve a join request on the owner's behalf, if it's still valid."""
    db = connect(db_path)
    try:
        rq = db.execute("SELECT * FROM requests WHERE id=? AND kind='join' AND status='pending'", (rid,)).fetchone()
        if rq:
            accept_request(db, rq, get_team(db, rq["team_id"]), auto=True)
            db.commit()
    except ApiError:
        db.rollback()  # e.g. the team filled up meanwhile; the request stays pending for the owner
    finally:
        db.close()


@route("POST", r"/api/teams/(\d+)/join")
def request_join(c, tid):
    u = c.me()
    r = get_team(c.db, int(tid))
    check_can_join(c.db, r, u["id"])
    if c.db.execute("SELECT 1 FROM requests WHERE team_id=? AND user_id=? AND status='pending'", (r["id"], u["id"])).fetchone():
        raise ApiError(409, "You already have a pending request or invite for this team")
    rid = c.db.execute("INSERT INTO requests(team_id,user_id,kind,message,created_at) VALUES(?,?,?,?,?)",
                       (r["id"], u["id"], "join", text(c.body, "message", max_len=400), now())).lastrowid
    delay = c.srv.auto_approve
    if delay:
        c.after_commit.append(lambda: threading.Timer(delay, auto_approve, (c.srv.db_path, rid)).start())
        return 201, {"request_id": rid, "auto_approve_in": delay}
    notify(c.db, [r["owner_id"]], f"@{u['handle']} asked to join {r['name']}", f"#/t/{r['id']}")
    return 201, {"request_id": rid}


@route("POST", r"/api/teams/(\d+)/invite")
def invite(c, tid):
    u = c.me()
    r = get_team(c.db, int(tid))
    if r["owner_id"] != u["id"]:
        raise ApiError(403, "Only the team owner can invite")
    target = c.db.execute("SELECT * FROM users WHERE id=? AND role='hacker'",
                          (int_field(c.body, "user_id", 0, 1, 10 ** 9),)).fetchone()
    if not target:
        raise ApiError(404, "Hacker not found")
    check_can_join(c.db, r, target["id"])
    if c.db.execute("SELECT 1 FROM requests WHERE team_id=? AND user_id=? AND status='pending'", (r["id"], target["id"])).fetchone():
        raise ApiError(409, "There's already a pending request or invite between you")
    rid = c.db.execute("INSERT INTO requests(team_id,user_id,kind,message,created_at) VALUES(?,?,?,?,?)",
                       (r["id"], target["id"], "invite", text(c.body, "message", max_len=400), now())).lastrowid
    notify(c.db, [target["id"]], f"@{u['handle']} invited you to join {r['name']}", "#/inbox")
    return 201, {"request_id": rid}


@route("POST", r"/api/requests/(\d+)")
def decide_request(c, rid):
    u = c.me()
    rq = c.db.execute("SELECT * FROM requests WHERE id=?", (int(rid),)).fetchone()
    if not rq or rq["status"] != "pending":
        raise ApiError(404, "Request not found or already handled")
    team = get_team(c.db, rq["team_id"])
    decider = team["owner_id"] if rq["kind"] == "join" else rq["user_id"]
    action = c.body.get("action")
    if action == "cancel":
        decider = rq["user_id"] if rq["kind"] == "join" else team["owner_id"]
    if u["id"] != decider:
        raise ApiError(403, "This isn't yours to decide")
    if action == "accept":
        accept_request(c.db, rq, team)
    elif action in ("decline", "cancel"):
        c.db.execute("UPDATE requests SET status=? WHERE id=?",
                     ("declined" if action == "decline" else "withdrawn", rq["id"]))
    else:
        raise ApiError(400, "action must be accept, decline or cancel")
    return 200, {"ok": True, "team_id": team["id"]}


@route("POST", r"/api/teams/(\d+)/leave")
def leave_team(c, tid):
    u = c.me()
    r = get_team(c.db, int(tid))
    members = team_members(c.db, r["id"])
    if u["id"] not in [m["id"] for m in members]:
        raise ApiError(400, "You're not on this team")
    if len(members) == 1:
        c.db.execute("DELETE FROM teams WHERE id=?", (r["id"],))
        return 200, {"deleted": True}
    c.db.execute("DELETE FROM members WHERE team_id=? AND user_id=?", (r["id"], u["id"]))
    if r["owner_id"] == u["id"]:
        heir = next(m for m in members if m["id"] != u["id"])
        c.db.execute("UPDATE teams SET owner_id=? WHERE id=?", (heir["id"], r["id"]))
    return 200, {"deleted": False}


@route("GET", "/api/inbox")
def inbox(c):
    u = c.me()
    sql = ("SELECT rq.*, t.name AS team_name, t.challenge_id, c.title AS challenge_title FROM requests rq"
           " JOIN teams t ON t.id=rq.team_id JOIN challenges c ON c.id=t.challenge_id")
    def rows(where, args):
        out = []
        for r in c.db.execute(sql + " WHERE " + where + " ORDER BY rq.created_at DESC", args):
            d = dict(r)
            d["user"] = user_out(c.db.execute("SELECT * FROM users WHERE id=?", (r["user_id"],)).fetchone())
            out.append(d)
        return out
    return 200, {
        "invites": rows("rq.kind='invite' AND rq.user_id=? AND rq.status='pending'", (u["id"],)),
        "join_requests": rows("rq.kind='join' AND t.owner_id=? AND rq.status='pending'", (u["id"],)),
        "outgoing": rows("((rq.kind='join' AND rq.user_id=?) OR (rq.kind='invite' AND t.owner_id=?))"
                         " AND rq.created_at>?", (u["id"], u["id"], now() - 30 * DAY)),
    }


# --- matching ---

@route("GET", "/api/match/teams")
def match_teams(c):
    u = user_out(c.me())
    t = now()
    taken = {r["challenge_id"] for r in c.db.execute(
        "SELECT t.challenge_id FROM members m JOIN teams t ON t.id=m.team_id WHERE m.user_id=?", (u["id"],))}
    out = []
    for r in c.db.execute(TEAM_SQL + " WHERE c.ends_at>?", (t,)):
        if r["challenge_id"] in taken:
            continue
        team = team_out(c.db, r, t)
        if not team["open"]:
            continue
        team["score"], team["reasons"] = fit(u, team, team["members"], jl(r["challenge_tags"]))
        out.append(team)
    pending = pending_team_ids(c.db, u["id"])
    for x in out:
        x["requested"] = x["id"] in pending
    out.sort(key=lambda x: -x["score"])
    return 200, {"teams": out[:12]}


@route("GET", r"/api/teams/(\d+)/suggestions")
def suggest_people(c, tid):
    u = c.me()
    r = get_team(c.db, int(tid))
    team = team_out(c.db, r)
    if u["id"] not in [m["id"] for m in team["members"]]:
        raise ApiError(403, "Only team members can see suggestions")
    busy = {x["user_id"] for x in c.db.execute(
        "SELECT m.user_id FROM members m JOIN teams t ON t.id=m.team_id WHERE t.challenge_id=?", (r["challenge_id"],))}
    pending = {x["user_id"] for x in c.db.execute(
        "SELECT user_id FROM requests WHERE team_id=? AND status='pending'", (r["id"],))}
    out = []
    for p in c.db.execute("SELECT * FROM users WHERE role='hacker' AND looking=1"):
        if p["id"] in busy:
            continue
        person = user_out(p)
        person["score"], person["reasons"] = fit(person, team, team["members"], jl(r["challenge_tags"]))
        person["pending"] = p["id"] in pending
        out.append(person)
    out.sort(key=lambda x: -x["score"])
    return 200, {"people": out[:8]}


# --- submissions ---

@route("POST", "/api/submissions")
def submit(c):
    u, b = c.me(), c.body
    r = get_team(c.db, int_field(b, "team_id", 0, 1, 10 ** 9))
    sid = save_submission(c.db, r, u, b)
    return 201, {"submission": dict(c.db.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone())}


def save_submission(db, r, u, b):
    if u["id"] not in [m["id"] for m in team_members(db, r["id"])]:
        raise ApiError(403, "Only team members can submit")
    if status_of(r["c_starts"], r["c_ends"], now()) != "live":
        raise ApiError(400, "Submissions are only open while the challenge is live")
    fields = (text(b, "title", True, 80), text(b, "description", max_len=1200), url_field(b, "repo_url"), url_field(b, "demo_url"))
    if not (fields[2] or fields[3]):
        raise ApiError(400, "Add a repo or demo link")
    existing = db.execute("SELECT id FROM submissions WHERE team_id=?", (r["id"],)).fetchone()
    if existing:
        db.execute("UPDATE submissions SET title=?,description=?,repo_url=?,demo_url=? WHERE id=?", fields + (existing["id"],))
        sid = existing["id"]
    else:
        sid = db.execute("INSERT INTO submissions(team_id,challenge_id,title,description,repo_url,demo_url,created_at)"
                           " VALUES(?,?,?,?,?,?,?)", (r["id"], r["challenge_id"]) + fields + (now(),)).lastrowid
        notify(db, [j["id"] for j in db.execute("SELECT id FROM users WHERE role='judge'")],
               f"New project to judge: {fields[0]} ({r['challenge_title']})", "#/judge")
    return sid


@route("POST", r"/api/submissions/(\d+)/vote")
def vote(c, sid):
    u = c.me()
    s = c.db.execute("SELECT * FROM submissions WHERE id=?", (int(sid),)).fetchone()
    if not s:
        raise ApiError(404, "Project not found")
    if c.db.execute("SELECT 1 FROM members WHERE team_id=? AND user_id=?", (s["team_id"], u["id"])).fetchone():
        raise ApiError(400, "You can't vote for your own team")
    if c.db.execute("SELECT 1 FROM votes WHERE submission_id=? AND user_id=?", (s["id"], u["id"])).fetchone():
        c.db.execute("DELETE FROM votes WHERE submission_id=? AND user_id=?", (s["id"], u["id"]))
        voted = False
    else:
        c.db.execute("INSERT INTO votes(submission_id,user_id) VALUES(?,?)", (s["id"], u["id"]))
        voted = True
    votes = c.db.execute("SELECT COUNT(*) FROM votes WHERE submission_id=?", (s["id"],)).fetchone()[0]
    return 200, {"voted": voted, "votes": votes}


@route("GET", "/api/showcase")
def showcase(c):
    rows = c.db.execute(
        "SELECT s.*, t.name AS team_name, ch.title AS challenge_title,"
        " (SELECT COUNT(*) FROM votes v WHERE v.submission_id=s.id) AS votes"
        " FROM submissions s JOIN teams t ON t.id=s.team_id JOIN challenges ch ON ch.id=s.challenge_id"
        " ORDER BY votes DESC, s.created_at DESC LIMIT 6").fetchall()
    return 200, {"projects": [dict(r) for r in rows]}


# --- sponsors ---

def require_sponsor(c):
    u = c.me()
    if u["role"] != "sponsor" or not u["sponsor_id"]:
        raise ApiError(403, "Sponsor accounts only")
    return u


@route("POST", "/api/challenges")
def create_challenge(c):
    u, b = require_sponsor(c), c.body
    starts = int_field(b, "starts_at", now(), now() - DAY, now() + 365 * DAY)
    ends = int_field(b, "ends_at", starts + 7 * DAY, starts + 3600, starts + 60 * DAY)
    cid = c.db.execute(
        "INSERT INTO challenges(sponsor_id,title,summary,description,prize,tags,resource_url,max_team,starts_at,ends_at,created_at,"
        "format,location,luma_url,venue,info)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (u["sponsor_id"], text(b, "title", True, 80), text(b, "summary", max_len=160), text(b, "description", max_len=4000),
         text(b, "prize", max_len=120), json.dumps(clean_list(b.get("tags"), 8)), url_field(b, "resource_url"),
         int_field(b, "max_team", 4, 1, 8), starts, ends, now(),
         "In person" if b.get("format") == "In person" else "Online",
         text(b, "location", max_len=60) or ("Worldwide" if b.get("format") != "In person" else ""),
         luma_link(b), text(b, "venue", max_len=120), text(b, "info", max_len=4000))).lastrowid
    return 201, {"challenge": challenge_out(get_challenge(c.db, cid))}


@route("GET", "/api/sponsor/analytics")
def analytics(c):
    u = require_sponsor(c)
    t = now()
    days = 14
    day0 = t - t % DAY - (days - 1) * DAY
    rows, skills = [], Counter()
    totals = Counter()
    daily = [0] * days
    for r in c.db.execute(CHALLENGE_SQL + " WHERE c.sponsor_id=? ORDER BY c.starts_at DESC", (u["sponsor_id"],)):
        ch = challenge_out(r, t)
        ev = {k: n for k, n in c.db.execute(
            "SELECT kind, COUNT(*) FROM events WHERE challenge_id=? GROUP BY kind", (ch["id"],))}
        uniq = c.db.execute("SELECT COUNT(DISTINCT user_id) FROM events WHERE challenge_id=? AND kind='view' AND user_id IS NOT NULL",
                            (ch["id"],)).fetchone()[0]
        for (ts,) in c.db.execute("SELECT created_at FROM events WHERE challenge_id=? AND kind='view' AND created_at>=?",
                                  (ch["id"], day0)):
            daily[min(days - 1, (ts - day0) // DAY)] += 1
        for m in c.db.execute("SELECT u.skills FROM members m JOIN teams tm ON tm.id=m.team_id JOIN users u ON u.id=m.user_id"
                              " WHERE tm.challenge_id=?", (ch["id"],)):
            skills.update(s.lower() for s in jl(m["skills"]))
        views, clicks = ev.get("view", 0), ev.get("click", 0)
        ch.update(views=views, clicks=clicks, signed_in_viewers=uniq, ctr=round(100 * clicks / views, 1) if views else 0)
        totals.update(views=views, clicks=clicks, teams=ch["team_count"], hackers=ch["hacker_count"],
                      submissions=ch["submission_count"])
        rows.append(ch)
    totals = dict(totals)
    totals["ctr"] = round(100 * totals.get("clicks", 0) / totals["views"], 1) if totals.get("views") else 0
    perks = [dict(r) for r in c.db.execute(
        "SELECT p.*, c.title AS challenge_title, (SELECT COUNT(*) FROM perk_claims k WHERE k.perk_id=p.id) AS claims"
        " FROM perks p LEFT JOIN challenges c ON c.id=p.challenge_id WHERE p.sponsor_id=? ORDER BY p.created_at DESC",
        (u["sponsor_id"],))]
    totals["perk_claims"] = sum(p["claims"] for p in perks)
    return 200, {"perks": perks, "sponsor": dict(c.db.execute("SELECT * FROM sponsors WHERE id=?", (u["sponsor_id"],)).fetchone()),
                 "totals": totals, "challenges": rows, "top_skills": skills.most_common(10),
                 "daily_views": [{"day": day0 + i * DAY, "views": v} for i, v in enumerate(daily)]}


# --- demos (Zoom) & notifications ---

def demo_status(d, t):
    end = d["ended_at"] or d["starts_at"] + d["duration_min"] * 60
    return "upcoming" if t < d["starts_at"] else "live" if t < end else "past"


def demo_rows(db, uid, where, args):
    t = now()
    out = []
    for r in db.execute(
            "SELECT d.*, t.name AS team_name, t.challenge_id, c.title AS challenge_title,"
            " (SELECT COUNT(*) FROM demo_watchers w WHERE w.demo_id=d.id) AS watchers,"
            " EXISTS(SELECT 1 FROM demo_watchers w WHERE w.demo_id=d.id AND w.user_id=?) AS watching"
            " FROM demos d JOIN teams t ON t.id=d.team_id JOIN challenges c ON c.id=t.challenge_id "
            + where + " ORDER BY d.starts_at", (uid or -1,) + tuple(args)):
        d = dict(r)
        d["status"], d["watching"] = demo_status(d, t), bool(d["watching"])
        out.append(d)
    return out


@route("GET", "/api/demos")
def list_demos(c):
    uid = c.user["id"] if c.user else None
    # Anything still running or scheduled, plus the last day's demos for context.
    return 200, {"demos": demo_rows(c.db, uid, "WHERE d.starts_at + d.duration_min*60 > ?", (now() - DAY,))}


@route("POST", r"/api/teams/(\d+)/demos")
def schedule_demo(c, tid):
    u, b = c.me(), c.body
    r = get_team(c.db, int(tid))
    members = team_members(c.db, r["id"])
    if u["id"] not in [m["id"] for m in members]:
        raise ApiError(403, "Only team members can schedule a demo")
    t = now()
    if t > r["c_ends"] + 7 * DAY:
        raise ApiError(400, "Demos close a week after the challenge ends")
    starts = int_field(b, "starts_at", t, t - 600, t + 30 * DAY)
    title = text(b, "title", max_len=80) or f"{r['name']} demo"
    did = c.db.execute(
        "INSERT INTO demos(team_id,title,zoom_url,starts_at,duration_min,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
        (r["id"], title, zoom_url(b, "zoom_url"), starts, int_field(b, "duration_min", 15, 5, 120), u["id"], t)).lastrowid
    when = "now" if starts <= t + 300 else "soon"
    others = [x["id"] for x in c.db.execute("SELECT id FROM users")
              if x["id"] not in {m["id"] for m in members}]
    notify(c.db, others, f"📺 Live demo {when}: {r['name']} — {title}", "#/demos")
    return 201, {"demo": demo_rows(c.db, u["id"], "WHERE d.id=?", (did,))[0]}


@route("POST", r"/api/demos/(\d+)/watch")
def watch_demo(c, did):
    u = c.me()
    d = c.db.execute("SELECT * FROM demos WHERE id=?", (int(did),)).fetchone()
    if not d:
        raise ApiError(404, "Demo not found")
    c.db.execute("INSERT OR IGNORE INTO demo_watchers(demo_id,user_id) VALUES(?,?)", (d["id"], u["id"]))
    return 200, {"zoom_url": d["zoom_url"], "status": demo_status(d, now())}


@route("POST", r"/api/demos/(\d+)/cancel")
def cancel_demo(c, did):
    u = c.me()
    d = c.db.execute("SELECT * FROM demos WHERE id=?", (int(did),)).fetchone()
    if not d:
        raise ApiError(404, "Demo not found")
    if not c.db.execute("SELECT 1 FROM members WHERE team_id=? AND user_id=?", (d["team_id"], u["id"])).fetchone():
        raise ApiError(403, "Only team members can cancel")
    watchers = [w["user_id"] for w in c.db.execute("SELECT user_id FROM demo_watchers WHERE demo_id=?", (d["id"],))]
    notify(c.db, watchers, f"Demo cancelled: {d['title']}", "#/demos")
    c.db.execute("DELETE FROM demos WHERE id=?", (d["id"],))
    return 200, {"ok": True}


@route("GET", "/api/notifications")
def notifications(c):
    u = c.me()
    rows = [dict(r, read=bool(r["read"])) for r in c.db.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC, id DESC LIMIT 50", (u["id"],))]
    return 200, {"notifications": rows}


@route("POST", "/api/notifications/read")
def read_notifications(c):
    c.db.execute("UPDATE notifications SET read=1 WHERE user_id=?", (c.me()["id"],))
    return 200, {"ok": True}


# --- judging ---

def require_judge(c):
    u = c.me()
    if u["role"] != "judge":
        raise ApiError(403, "Judge accounts only")
    return u


@route("GET", "/api/judge/queue")
def judge_queue(c):
    u = require_judge(c)
    t = now()
    rows = []
    for r in c.db.execute(
            "SELECT s.*, tm.name AS team_name, ch.title AS challenge_title, ch.starts_at AS c_starts, ch.ends_at AS c_ends,"
            " (SELECT COUNT(*) FROM votes v WHERE v.submission_id=s.id) AS votes,"
            " (SELECT ROUND(AVG((x.innovation+x.technical+x.design+x.impact)/4.0),1) FROM scores x WHERE x.submission_id=s.id) AS judge_score,"
            " (SELECT COUNT(*) FROM scores x WHERE x.submission_id=s.id) AS judge_count"
            " FROM submissions s JOIN teams tm ON tm.id=s.team_id JOIN challenges ch ON ch.id=s.challenge_id"
            " ORDER BY ch.ends_at, s.created_at"):
        d = dict(r)
        d["challenge_status"] = status_of(d.pop("c_starts"), d.pop("c_ends"), t)
        mine = c.db.execute("SELECT * FROM scores WHERE submission_id=? AND judge_id=?", (r["id"], u["id"])).fetchone()
        d["my_score"] = dict(mine) if mine else None
        d["members"] = team_members(c.db, r["team_id"])
        rows.append(d)
    rows.sort(key=lambda d: d["my_score"] is not None)
    return 200, {"submissions": rows, "rubric": list(SCORE_FIELDS)}


@route("POST", r"/api/submissions/(\d+)/score")
def score_submission(c, sid):
    u, b = require_judge(c), c.body
    s = c.db.execute("SELECT * FROM submissions WHERE id=?", (int(sid),)).fetchone()
    if not s:
        raise ApiError(404, "Project not found")
    vals = [int_field(b, f, None, 1, 10) for f in SCORE_FIELDS]
    c.db.execute("INSERT OR REPLACE INTO scores(submission_id,judge_id,innovation,technical,design,impact,comment,created_at)"
                 " VALUES(?,?,?,?,?,?,?,?)", (s["id"], u["id"], *vals, text(b, "comment", max_len=1000), now()))
    members = [m["user_id"] for m in c.db.execute("SELECT user_id FROM members WHERE team_id=?", (s["team_id"],))]
    notify(c.db, members, f"A judge scored {s['title']}", f"#/t/{s['team_id']}")
    avg = c.db.execute("SELECT ROUND(AVG((innovation+technical+design+impact)/4.0),1), COUNT(*) FROM scores WHERE submission_id=?",
                       (s["id"],)).fetchone()
    return 200, {"judge_score": avg[0], "judge_count": avg[1]}


# --- sponsor support (perks) ---

def perks_for(db, ch, uid):
    if ch["sponsor"]["id"] is None:
        where, args = "p.challenge_id=?", (ch["id"],)
    else:
        where, args = "(p.challenge_id=? OR (p.challenge_id IS NULL AND p.sponsor_id=?))", (ch["id"], ch["sponsor"]["id"])
    return [dict(r, claimed=bool(r["claimed"])) for r in db.execute(
        "SELECT p.id, p.kind, p.title, p.details, p.sponsor_id, s.name AS sponsor_name,"
        " (SELECT COUNT(*) FROM perk_claims k WHERE k.perk_id=p.id) AS claims,"
        " EXISTS(SELECT 1 FROM perk_claims k WHERE k.perk_id=p.id AND k.user_id=?) AS claimed"
        " FROM perks p JOIN sponsors s ON s.id=p.sponsor_id WHERE " + where + " ORDER BY p.created_at", (uid or -1,) + args)]


@route("POST", "/api/perks")
def create_perk(c):
    u, b = require_sponsor(c), c.body
    cid = b.get("challenge_id") or None
    if cid is not None:
        cid = int_field(b, "challenge_id", None, 1, 10 ** 9)
        if get_challenge(c.db, cid)["sponsor_id"] != u["sponsor_id"]:
            raise ApiError(403, "You can only attach support to your own challenges")
    kind = b.get("kind")
    if kind not in PERK_KINDS:
        raise ApiError(400, "kind must be one of " + ", ".join(PERK_KINDS))
    pid = c.db.execute("INSERT INTO perks(sponsor_id,challenge_id,kind,title,details,link,created_at) VALUES(?,?,?,?,?,?,?)",
                       (u["sponsor_id"], cid, kind, text(b, "title", True, 80), text(b, "details", max_len=600),
                        url_field(b, "link"), now())).lastrowid
    return 201, {"perk_id": pid}


@route("POST", r"/api/perks/(\d+)/claim")
def claim_perk(c, pid):
    u = c.me()
    if u["role"] != "hacker":
        raise ApiError(403, "Perks are for hackers")
    p = c.db.execute("SELECT * FROM perks WHERE id=?", (int(pid),)).fetchone()
    if not p:
        raise ApiError(404, "Perk not found")
    c.db.execute("INSERT OR IGNORE INTO perk_claims(perk_id,user_id,created_at) VALUES(?,?,?)", (p["id"], u["id"], now()))
    return 200, {"link": p["link"], "details": p["details"]}


# --- the floor: presence, ship log, raise-your-hand help ---

def helped_count(db, uid):
    return db.execute("SELECT COUNT(*) FROM posts WHERE resolved_by=?", (uid,)).fetchone()[0]


def current_team(db, uid):
    """The user's team in a live challenge, if any (most recently joined)."""
    t = now()
    return db.execute(
        "SELECT tm.id, tm.name FROM members m JOIN teams tm ON tm.id=m.team_id JOIN challenges c ON c.id=tm.challenge_id"
        " WHERE m.user_id=? AND c.starts_at<=? AND c.ends_at>? ORDER BY m.joined_at DESC LIMIT 1", (uid, t, t)).fetchone()


def floor_user(db, r):
    u = user_out(r)
    team = current_team(db, r["id"])
    u["team"] = dict(team) if team else None
    if r["sponsor_id"]:
        u["org"] = db.execute("SELECT name FROM sponsors WHERE id=?", (r["sponsor_id"],)).fetchone()[0]
    return u


@route("GET", "/api/floor")
def floor(c):
    """The Floor, optionally scoped to one hackathon (?challenge_id=)."""
    t = now()
    uid = c.user["id"] if c.user else None
    cid = int(c.q("challenge_id")) if c.q("challenge_id").isdigit() else None
    if uid:
        c.db.execute("UPDATE presence SET last_seen=? WHERE user_id=? AND last_seen>?", (t, uid, t - HERE_WINDOW))
    here = []
    scope_here, scope_args = ("", ()) if cid is None else (" AND p.challenge_id=?", (cid,))
    for r in c.db.execute("SELECT u.*, p.status AS p_status, p.since AS p_since FROM presence p JOIN users u ON u.id=p.user_id"
                          " WHERE p.last_seen>?" + scope_here + " ORDER BY p.since", (t - HERE_WINDOW,) + scope_args):
        u = floor_user(c.db, r)
        u.update(status=r["p_status"], since=r["p_since"], helped=helped_count(c.db, r["id"]))
        here.append(u)
    users = {}

    def author(user_id):
        if user_id not in users:
            users[user_id] = floor_user(c.db, c.db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
        return users[user_id]

    posts = []
    for r in c.db.execute(
            "SELECT p.*, tm.name AS team_name, (SELECT COUNT(*) FROM highfives h WHERE h.post_id=p.id) AS highfives,"
            " EXISTS(SELECT 1 FROM highfives h WHERE h.post_id=p.id AND h.user_id=?) AS highfived"
            " FROM posts p LEFT JOIN teams tm ON tm.id=p.team_id"
            + ("" if cid is None else " WHERE COALESCE(p.challenge_id, tm.challenge_id)=?")
            + " ORDER BY p.created_at DESC, p.id DESC LIMIT 60", (uid or -1,) + (() if cid is None else (cid,))):
        d = dict(r)
        d["tags"], d["highfived"], d["author"] = jl(r["tags"]), bool(r["highfived"]), author(r["user_id"])
        d["resolved_by"] = author(r["resolved_by"]) if r["resolved_by"] else None
        d["replies"] = [dict(x, author=author(x["user_id"])) for x in c.db.execute(
            "SELECT * FROM replies WHERE post_id=? ORDER BY created_at, id", (r["id"],))]
        posts.append(d)
    return 200, {"here": here, "posts": posts, "me_here": any(h["id"] == uid for h in here)}


@route("POST", "/api/floor/checkin")
def checkin(c):
    u = c.me()
    t = now()
    status = text(c.body, "status", max_len=120)
    fresh = not c.db.execute("SELECT 1 FROM presence WHERE user_id=? AND last_seen>?", (u["id"], t - HERE_WINDOW)).fetchone()
    cid = c.body.get("challenge_id")
    cid = get_challenge(c.db, int_field(c.body, "challenge_id", 0, 1, 10 ** 9))["id"] if cid else None
    c.db.execute("INSERT INTO presence(user_id,status,since,last_seen,challenge_id) VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET"
                 " status=excluded.status, last_seen=excluded.last_seen, challenge_id=excluded.challenge_id"
                 + (", since=excluded.since" if fresh else ""), (u["id"], status, t, t, cid))
    return 200, {"ok": True}


@route("POST", "/api/floor/leave")
def leave_floor(c):
    c.db.execute("DELETE FROM presence WHERE user_id=?", (c.me()["id"],))
    return 200, {"ok": True}


@route("POST", "/api/posts")
def create_post(c):
    u, b = c.me(), c.body
    kind = b.get("kind")
    if kind not in ("update", "help"):
        raise ApiError(400, "kind must be update or help")
    body = text(b, "text", True, 500)
    tags = clean_list(b.get("tags"), 5)
    team = current_team(c.db, u["id"])
    cid = get_challenge(c.db, int_field(b, "challenge_id", 0, 1, 10 ** 9))["id"] if b.get("challenge_id") else None
    pid = c.db.execute("INSERT INTO posts(user_id,kind,text,tags,team_id,challenge_id,created_at) VALUES(?,?,?,?,?,?,?)",
                       (u["id"], kind, body, json.dumps(tags), team["id"] if team else None, cid, now())).lastrowid
    if kind == "help":
        # Tap the right shoulders: people on the floor with a matching skill, and sponsors whose live challenges match.
        want, t = lower_set(tags), now()
        helpers = [r["id"] for r in c.db.execute(
            "SELECT u.* FROM presence p JOIN users u ON u.id=p.user_id WHERE p.last_seen>? AND u.id!=?", (t - HERE_WINDOW, u["id"]))
            if want & lower_set(jl(r["skills"]))]
        for r in c.db.execute("SELECT DISTINCT u.id, c.tags FROM users u JOIN challenges c ON c.sponsor_id=u.sponsor_id"
                              " WHERE u.role='sponsor' AND c.starts_at<=? AND c.ends_at>?", (t, t)):
            if want & lower_set(jl(r["tags"])):
                helpers.append(r["id"])
        tag_text = f" ({', '.join(tags)})" if tags else ""
        notify(c.db, helpers[:50], f"🙋 @{u['handle']} needs a hand{tag_text}: {body[:80]}", "#/floor")
    return 201, {"post_id": pid}


def get_post(db, pid):
    p = db.execute("SELECT * FROM posts WHERE id=?", (int(pid),)).fetchone()
    if not p:
        raise ApiError(404, "Post not found")
    return p


@route("POST", r"/api/posts/(\d+)/reply")
def reply(c, pid):
    u = c.me()
    p = get_post(c.db, pid)
    c.db.execute("INSERT INTO replies(post_id,user_id,text,created_at) VALUES(?,?,?,?)",
                 (p["id"], u["id"], text(c.body, "text", True, 500), now()))
    if p["user_id"] != u["id"]:
        verb = "offered to help" if p["kind"] == "help" else "replied to your update"
        notify(c.db, [p["user_id"]], f"@{u['handle']} {verb}: {text(c.body, 'text', max_len=80)}", "#/floor")
    return 201, {"ok": True}


@route("POST", r"/api/posts/(\d+)/highfive")
def highfive(c, pid):
    u = c.me()
    p = get_post(c.db, pid)
    if c.db.execute("DELETE FROM highfives WHERE post_id=? AND user_id=?", (p["id"], u["id"])).rowcount == 0:
        c.db.execute("INSERT INTO highfives(post_id,user_id) VALUES(?,?)", (p["id"], u["id"]))
        on = True
    else:
        on = False
    n = c.db.execute("SELECT COUNT(*) FROM highfives WHERE post_id=?", (p["id"],)).fetchone()[0]
    return 200, {"on": on, "count": n}


@route("POST", r"/api/posts/(\d+)/resolve")
def resolve(c, pid):
    u = c.me()
    p = get_post(c.db, pid)
    if p["user_id"] != u["id"] or p["kind"] != "help":
        raise ApiError(403, "Only the person who asked can mark this solved")
    if p["resolved_by"]:
        raise ApiError(409, "Already solved")
    helper = int_field(c.body, "helper_id", 0, 1, 10 ** 9)
    if helper == u["id"] or not c.db.execute("SELECT 1 FROM replies WHERE post_id=? AND user_id=?", (p["id"], helper)).fetchone():
        raise ApiError(400, "Credit someone who replied")
    c.db.execute("UPDATE posts SET resolved_by=? WHERE id=?", (helper, p["id"]))
    notify(c.db, [helper], f"🙌 @{u['handle']} says you got them unstuck. +1 helper karma", "#/floor")
    return 200, {"helped": helped_count(c.db, helper)}


# --- team room: product preview, doing-now, video/voice signaling ---

def require_member(c, tid):
    u = c.me()
    r = get_team(c.db, int(tid))
    if not c.db.execute("SELECT 1 FROM members WHERE team_id=? AND user_id=?", (r["id"], u["id"])).fetchone():
        raise ApiError(403, "The team room is for team members only")
    return u, r


def log_team(db, team_id, user_id, message):
    db.execute("INSERT INTO team_log(team_id,user_id,text,created_at) VALUES(?,?,?,?)", (team_id, user_id, message, now()))


def transcript_lines(db, team_id, since=0, limit=200):
    rows = db.execute("SELECT x.*, u.handle, u.name FROM transcripts x JOIN users u ON u.id=x.user_id"
                      " WHERE x.team_id=? AND x.id>? ORDER BY x.id DESC LIMIT ?", (team_id, since, limit)).fetchall()
    return [{"id": r["id"], "user_id": r["user_id"], "handle": r["handle"], "name": r["name"], "text": r["text"],
             "created_at": r["created_at"]} for r in reversed(rows)]


def room_participants(db, team_id):
    return [{"session": r["session"], "user_id": r["user_id"], "cam": bool(r["cam"]), "talking": bool(r["talking"]),
             "caption": r["caption"] or ""}
            for r in db.execute("SELECT * FROM room_presence WHERE team_id=? AND last_seen>? ORDER BY user_id, session",
                                (team_id, now() - ROOM_WINDOW))]


@route("GET", r"/api/teams/(\d+)/room")
def team_room(c, tid):
    u, r = require_member(c, tid)
    t = now()
    in_room = {p["user_id"] for p in room_participants(c.db, r["id"])}
    on_floor = {x["user_id"] for x in c.db.execute("SELECT user_id FROM presence WHERE last_seen>?", (t - HERE_WINDOW,))}
    members = []
    for m in c.db.execute("SELECT u.*, mm.doing, mm.doing_at FROM members mm JOIN users u ON u.id=mm.user_id"
                          " WHERE mm.team_id=? ORDER BY mm.joined_at, u.id", (r["id"],)):
        d = user_out(m)
        d.update(doing=m["doing"] or "", doing_at=m["doing_at"],
                 where="room" if m["id"] in in_room else "floor" if m["id"] in on_floor else "away")
        members.append(d)
    names = {m["id"]: m for m in members}
    log = []
    for x in c.db.execute("SELECT * FROM team_log WHERE team_id=? ORDER BY created_at DESC, id DESC LIMIT 40", (r["id"],)):
        d = dict(x)
        who = names.get(x["user_id"]) or user_out(c.db.execute("SELECT * FROM users WHERE id=?", (x["user_id"],)).fetchone())
        d["user"] = {"id": who["id"], "name": who["name"], "handle": who["handle"]}
        log.append(d)
    by = names.get(r["preview_by"])
    row = c.db.execute("SELECT steps FROM onboarding WHERE team_id=? AND user_id=?", (r["id"], u["id"])).fetchone()
    steps = set(json.loads(row["steps"])) if row else set()
    if any(m["id"] == u["id"] and m["doing"] for m in members):
        steps.add("status")
    head = ensure_build(c.db, r)
    return 200, {"team": team_out(c.db, r), "members": members, "log": log, "transcript": transcript_lines(c.db, r["id"]),
                 "onboarding": sorted(steps), "build": {"version": head["id"], "note": head["note"], "at": head["created_at"]} if head else None,
                 "submission": dict(sub) if (sub := c.db.execute("SELECT title, description FROM submissions WHERE team_id=?", (r["id"],)).fetchone()) else None,
                 "preview": {"url": r["preview_url"] or "", "at": r["preview_at"], "by": by["handle"] if by else None}}


@route("POST", r"/api/teams/(\d+)/preview")
def set_preview(c, tid):
    u, r = require_member(c, tid)
    url = url_field(c.body, "url")
    c.db.execute("UPDATE teams SET preview_url=?, preview_by=?, preview_at=? WHERE id=?", (url, u["id"], now(), r["id"]))
    log_team(c.db, r["id"], u["id"], f"pushed a new preview: {url}" if url else "cleared the preview")
    others = [m["user_id"] for m in c.db.execute("SELECT user_id FROM members WHERE team_id=? AND user_id!=?", (r["id"], u["id"]))]
    if url:
        notify(c.db, others, f"🚀 @{u['handle']} pushed a new build of {r['name']}", f"#/t/{r['id']}/room")
    return 200, {"ok": True}


@route("POST", r"/api/teams/(\d+)/doing")
def set_doing(c, tid):
    u, r = require_member(c, tid)
    doing = text(c.body, "doing", max_len=140)
    c.db.execute("UPDATE members SET doing=?, doing_at=? WHERE team_id=? AND user_id=?", (doing, now(), r["id"], u["id"]))
    if doing:
        log_team(c.db, r["id"], u["id"], f"is now on: {doing}")
    return 200, {"ok": True}


def session_field(body, key):
    v = str(body.get(key) or "")
    if not SESSION_RE.match(v):
        raise ApiError(400, f"{key} is invalid")
    return v


@route("POST", r"/api/teams/(\d+)/room/heartbeat")
def room_heartbeat(c, tid):
    """Called ~every 1.5s by each open room: refreshes presence and delivers WebRTC signals addressed to this session."""
    u, r = require_member(c, tid)
    b, t = c.body, now()
    session = session_field(b, "session")
    c.db.execute("INSERT INTO room_presence(team_id,session,user_id,cam,talking,caption,last_seen) VALUES(?,?,?,?,?,?,?)"
                 " ON CONFLICT(team_id,session) DO UPDATE SET cam=excluded.cam, talking=excluded.talking,"
                 " caption=excluded.caption, last_seen=excluded.last_seen",
                 (r["id"], session, u["id"], 1 if b.get("cam") else 0, 1 if b.get("talking") else 0,
                  text(b, "caption", max_len=200), t))
    c.db.execute("DELETE FROM room_presence WHERE last_seen<?", (t - 5 * ROOM_WINDOW,))
    c.db.execute("DELETE FROM signals WHERE created_at<?", (t - 60,))
    since = int_field(b, "since", 0, 0, 10 ** 12)
    signals = [{"id": x["id"], "from": x["from_session"], "kind": x["kind"], "payload": json.loads(x["payload"])}
               for x in c.db.execute("SELECT * FROM signals WHERE team_id=? AND to_session=? AND id>? ORDER BY id",
                                     (r["id"], session, since))]
    # Clients send the last transcript id they have (0 = none yet); omitting it skips the lookup.
    transcript = []
    if b.get("transcript_since") is not None:
        transcript = transcript_lines(c.db, r["id"], int_field(b, "transcript_since", 0, 0, 10 ** 12), 50)
    return 200, {"participants": room_participants(c.db, r["id"]), "signals": signals, "transcript": transcript}


@route("POST", r"/api/teams/(\d+)/room/signal")
def room_signal(c, tid):
    u, r = require_member(c, tid)
    b = c.body
    frm, to = session_field(b, "session"), session_field(b, "to")
    if not c.db.execute("SELECT 1 FROM room_presence WHERE team_id=? AND session=? AND user_id=?", (r["id"], frm, u["id"])).fetchone():
        raise ApiError(403, "Join the room first")
    if not c.db.execute("SELECT 1 FROM room_presence WHERE team_id=? AND session=?", (r["id"], to)).fetchone():
        raise ApiError(404, "That teammate left the room")
    kind = b.get("kind")
    if kind not in ("offer", "answer", "bye"):
        raise ApiError(400, "kind must be offer, answer or bye")
    payload = json.dumps(b.get("payload"))
    if len(payload) > 20_000:
        raise ApiError(413, "Signal too large")
    c.db.execute("INSERT INTO signals(team_id,from_session,to_session,kind,payload,created_at) VALUES(?,?,?,?,?,?)",
                 (r["id"], frm, to, kind, payload, now()))
    return 201, {"ok": True}


@route("POST", r"/api/teams/(\d+)/transcript")
def add_transcript(c, tid):
    """A finished phrase from the speaker's own browser speech-to-text. Audio itself never reaches the server."""
    u, r = require_member(c, tid)
    line = text(c.body, "text", True, 500)
    lid = c.db.execute("INSERT INTO transcripts(team_id,user_id,text,created_at) VALUES(?,?,?,?)",
                       (r["id"], u["id"], line, now())).lastrowid
    return 201, {"line": transcript_lines(c.db, r["id"], lid - 1, 1)[0]}


@route("POST", r"/api/teams/(\d+)/transcript/clear")
def clear_transcript(c, tid):
    u, r = require_member(c, tid)
    n = c.db.execute("DELETE FROM transcripts WHERE team_id=?", (r["id"],)).rowcount
    if n:
        log_team(c.db, r["id"], u["id"], f"cleared the call transcript ({n} lines)")
    return 200, {"cleared": n}


@route("POST", r"/api/teams/(\d+)/room/leave")
def room_leave(c, tid):
    u, r = require_member(c, tid)
    session = session_field(c.body, "session")
    c.db.execute("DELETE FROM room_presence WHERE team_id=? AND session=? AND user_id=?", (r["id"], session, u["id"]))
    return 200, {"ok": True}


# --- the shared clock: weekly rituals everyone joins at the same moment ---

REGIONS = {"americas": "Americas", "emea": "Europe & Africa", "apac": "Asia-Pacific"}
RITUALS = {
    "kickoff": {"title": "Monday Kickoff", "weekday": 0, "at": (17, 0), "minutes": 45,
                "blurb": "This week's challenges go live. Pitch an idea in one line, tap “I'm in” on others, and turn ideas into teams."},
    # 8-9pm local-ish in each region, expressed in UTC.
    "checkin": {"title": "Nightly check-in", "daily": {"apac": (12, 0), "emea": (19, 0), "americas": (1, 0)}, "minutes": 30,
                "blurb": "Everyone in your region posts what they shipped today, in the same half hour. Keep your streak alive."},
    "closing": {"title": "Sunday Closing Ceremony", "weekday": 6, "at": (18, 0), "minutes": 60,
                "blurb": "Live demos on a 3-minute clock, reactions from the crowd, awards at the end."},
}
CLOSING_INTRO, CLOSING_SLOT, CLOSING_AWARDS = 300, 180, 600  # seconds; teams present from their own Zoom, so no changeover gap
EMOJIS = ("🔥", "👏", "🚀", "😂", "❤️")
OCC_RE = re.compile(r"^(kickoff|checkin|closing)(?:-(americas|emea|apac))?-(\d{9,11})$")
RITUAL_HERE = 20  # seconds since the last poll that still counts as "here"


def region_of(tz):
    return "americas" if tz <= -3 else "apac" if tz >= 5 else "emea"


def make_occ(key, start, region=None):
    spec = RITUALS[key]
    return {"id": f"{key}-{region}-{start}" if region else f"{key}-{start}", "key": key, "region": region,
            "title": spec["title"] + (f" · {REGIONS[region]}" if region else ""), "blurb": spec["blurb"],
            "starts_at": start, "ends_at": start + spec["minutes"] * 60}


def occurrences(t0, t1, demo=None):
    """Every ritual overlapping [t0, t1), computed from the fixed weekly schedule (plus a demo-mode extra)."""
    out = []
    day = t0 - t0 % DAY - DAY
    while day < t1 + DAY:
        weekday = datetime.fromtimestamp(day, timezone.utc).weekday()
        for key, spec in RITUALS.items():
            if "daily" in spec:
                slots = list(spec["daily"].items())
            else:
                slots = [(None, spec["at"])] if spec["weekday"] == weekday else []
            for region, (h, m) in slots:
                o = make_occ(key, day + h * 3600 + m * 60, region)
                if o["ends_at"] > t0 and o["starts_at"] < t1:
                    out.append(o)
        day += DAY
    if demo:
        o = make_occ(demo["key"], demo["starts_at"])
        if o["ends_at"] > t0 and o["starts_at"] < t1:
            out.append(o)
    return sorted(out, key=lambda o: o["starts_at"])


def relevant(o, region):
    return o["region"] is None or region is None or o["region"] == region


def find_occ(c, occ_id):
    m = OCC_RE.match(occ_id)
    if m:
        start = int(m.group(3))
        for o in occurrences(start - 1, start + 1, c.srv.demo_ritual):
            if o["id"] == occ_id:
                return o
    raise ApiError(404, "No such ritual")


def is_live(o, t=None):
    t = t or now()
    return o["starts_at"] <= t < o["ends_at"]


def require_live(o):
    if not is_live(o):
        raise ApiError(400, "This isn't live right now — check the schedule")


@route("GET", "/api/clock")
def clock(c):
    """The shared clock: server time (clients sync to it), live/next rituals, and your team's deadline."""
    t = now()
    region = region_of(c.user["tz"]) if c.user else None
    week = [dict(o, live=is_live(o, t)) for o in occurrences(t - 2 * 3600, t + 7 * DAY, c.srv.demo_ritual)
            if relevant(o, region)]
    deadline = None
    if c.user:
        r = c.db.execute(
            "SELECT tm.id, tm.name, ch.title, ch.ends_at FROM members m JOIN teams tm ON tm.id=m.team_id"
            " JOIN challenges ch ON ch.id=tm.challenge_id WHERE m.user_id=? AND ch.starts_at<=? AND ch.ends_at>?"
            " ORDER BY ch.ends_at LIMIT 1", (c.user["id"], t, t)).fetchone()
        if r:
            deadline = {"team_id": r["id"], "team_name": r["name"], "challenge_title": r["title"], "ends_at": r["ends_at"]}
    return 200, {"now": time.time(), "region": region, "region_label": REGIONS.get(region),
                 "live": [o for o in week if o["live"]], "next": next((o for o in week if o["starts_at"] > t), None),
                 "week": [o for o in week if o["ends_at"] > t], "deadline": deadline}


@route("GET", "/api/clock.ics")
def clock_ics(c):
    t = now()
    region = region_of(c.user["tz"]) if c.user else None
    stamp = datetime.fromtimestamp(t, timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Always-On Hackathon//Rituals//EN", "CALSCALE:GREGORIAN"]
    seen = set()
    for o in occurrences(t, t + 8 * DAY):
        series = (o["key"], o["region"])
        if series in seen or not relevant(o, region):
            continue
        seen.add(series)
        spec = RITUALS[o["key"]]
        lines += ["BEGIN:VEVENT", f"UID:{o['key']}-{o['region'] or 'all'}@always-on-hackathon", f"DTSTAMP:{stamp}",
                  "DTSTART:" + datetime.fromtimestamp(o["starts_at"], timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                  f"DURATION:PT{spec['minutes']}M", "RRULE:FREQ=" + ("DAILY" if "daily" in spec else "WEEKLY"),
                  f"SUMMARY:Always-On Hackathon · {o['title']}", f"DESCRIPTION:{o['blurb']}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return 200, Raw("\r\n".join(lines) + "\r\n", "text/calendar; charset=utf-8", "always-on-hackathon.ics")


def closing_phase(o, t):
    """The ceremony runs on the clock alone: intro, then a 3-minute slot per lineup position, then awards."""
    s, awards_at = o["starts_at"], o["ends_at"] - CLOSING_AWARDS
    if t < s:
        return "upcoming", None
    if t < s + CLOSING_INTRO:
        return "intro", None
    if t < awards_at:
        return "demos", (t - s - CLOSING_INTRO) // CLOSING_SLOT
    return ("awards" if t < o["ends_at"] else "ended"), None


def slot_window(o, position):
    start = o["starts_at"] + CLOSING_INTRO + position * CLOSING_SLOT
    return start, start + CLOSING_SLOT


def max_slots(o):
    return (o["ends_at"] - CLOSING_AWARDS - o["starts_at"] - CLOSING_INTRO) // CLOSING_SLOT


def reaction_counts(db, occ_id):
    out = {}
    for r in db.execute("SELECT slot, emoji, n FROM reactions WHERE occ_id=?", (occ_id,)):
        out.setdefault(r["slot"], {})[r["emoji"]] = r["n"]
    return out


def checkin_streak(db, uid, t=None):
    t = t or now()
    days = {ts // DAY for (ts,) in db.execute(
        "SELECT created_at FROM posts WHERE user_id=? AND ritual LIKE 'checkin-%'", (uid,))}
    day = t // DAY if t // DAY in days else t // DAY - 1
    streak = 0
    while day in days:
        streak += 1
        day -= 1
    return streak


def lineup_rows(c, o, t):
    reacts = reaction_counts(c.db, o["id"])
    rows = []
    for r in c.db.execute(
            "SELECT l.*, tm.name AS team_name, s.title AS project, s.description, s.repo_url, s.demo_url,"
            " (SELECT COUNT(*) FROM votes v WHERE v.submission_id=s.id) AS votes,"
            " (SELECT ROUND(AVG((x.innovation+x.technical+x.design+x.impact)/4.0),1) FROM scores x WHERE x.submission_id=s.id) AS judge_score"
            " FROM lineup l JOIN teams tm ON tm.id=l.team_id LEFT JOIN submissions s ON s.team_id=l.team_id"
            " WHERE l.occ_id=? ORDER BY l.position", (o["id"],)):
        start, end = slot_window(o, r["position"])
        d = dict(r)
        d.update(slot_start=start, slot_end=end, members=team_members(c.db, r["team_id"]),
                 reactions=reacts.get(r["position"], {}), applause=sum(reacts.get(r["position"], {}).values()),
                 state="done" if t >= end else "now" if t >= start else "next")
        rows.append(d)
    return rows


def closing_awards(rows):
    awards = []
    for title, key, fmt in [("Crowd favorite", "applause", "{} reactions"), ("Judges' pick", "judge_score", "{}/10 from judges"),
                            ("Community vote", "votes", "{} votes")]:
        best = max((r for r in rows if r[key]), key=lambda r: r[key], default=None)
        if best:
            awards.append({"title": title, "team_id": best["team_id"], "team_name": best["team_name"],
                           "project": best["project"], "detail": fmt.format(best[key])})
    return awards


@route("GET", r"/api/live/([a-z0-9-]+)")
def live_state(c, occ_id):
    o = find_occ(c, occ_id)
    t = now()
    uid = c.user["id"] if c.user else None
    live = is_live(o, t)
    if uid and live:
        c.db.execute("INSERT INTO ritual_presence(occ_id,user_id,last_seen) VALUES(?,?,?)"
                     " ON CONFLICT(occ_id,user_id) DO UPDATE SET last_seen=excluded.last_seen", (o["id"], uid, t))
    here = [user_out(r) for r in c.db.execute(
        "SELECT u.* FROM ritual_presence p JOIN users u ON u.id=p.user_id WHERE p.occ_id=? AND p.last_seen>? ORDER BY p.last_seen DESC",
        (o["id"], t - RITUAL_HERE))]
    out = {"ritual": dict(o, live=live), "now": time.time(), "here": len(here), "here_people": here[:24],
           "reactions": reaction_counts(c.db, o["id"]).get(-1, {}), "emojis": EMOJIS}

    if o["key"] == "kickoff":
        ideas = []
        for r in c.db.execute("SELECT i.*, tm.name AS team_name FROM ideas i LEFT JOIN teams tm ON tm.id=i.team_id"
                              " WHERE i.occ_id=? ORDER BY i.created_at", (o["id"],)):
            fans = [user_out(f) for f in c.db.execute(
                "SELECT u.* FROM idea_fans f JOIN users u ON u.id=f.user_id WHERE f.idea_id=?", (r["id"],))]
            ideas.append({"id": r["id"], "text": r["text"], "team_id": r["team_id"], "team_name": r["team_name"],
                          "author": user_out(c.db.execute("SELECT * FROM users WHERE id=?", (r["user_id"],)).fetchone()),
                          "fans": fans, "mine": r["user_id"] == uid, "in": any(f["id"] == uid for f in fans),
                          "created_at": r["created_at"]})
        ideas.sort(key=lambda i: (-len(i["fans"]), i["created_at"]))
        out["ideas"] = ideas
        out["challenges"] = [challenge_out(r, t) for r in c.db.execute(CHALLENGE_SQL + " WHERE c.ends_at>? ORDER BY c.starts_at", (t,))]

    elif o["key"] == "checkin":
        posts = []
        for r in c.db.execute("SELECT * FROM posts WHERE ritual=? ORDER BY created_at DESC, id DESC", (o["id"],)):
            posts.append({"id": r["id"], "text": r["text"], "created_at": r["created_at"],
                          "author": floor_user(c.db, c.db.execute("SELECT * FROM users WHERE id=?", (r["user_id"],)).fetchone()),
                          "streak": checkin_streak(c.db, r["user_id"], t)})
        out["checkins"] = posts
        out["checked_in"] = any(p["author"]["id"] == uid for p in posts)
        out["streak"] = checkin_streak(c.db, uid, t) if uid else 0

    else:
        phase, slot = closing_phase(o, t)
        rows = lineup_rows(c, o, t)
        out.update(phase=phase, slot=slot, max_slots=max_slots(o), lineup=rows,
                   presenter=next((r for r in rows if r["state"] == "now"), None),
                   awards_at=o["ends_at"] - CLOSING_AWARDS, demos_at=o["starts_at"] + CLOSING_INTRO,
                   awards=closing_awards(rows) if phase in ("awards", "ended") else [])
        eligible = []
        if uid and phase in ("upcoming", "intro", "demos"):
            on_stage = {r["team_id"] for r in rows}
            for r in c.db.execute(
                    "SELECT tm.id, tm.name, s.title AS project, (SELECT d.zoom_url FROM demos d WHERE d.team_id=tm.id"
                    " ORDER BY d.created_at DESC LIMIT 1) AS zoom_url FROM members m JOIN teams tm ON tm.id=m.team_id"
                    " JOIN submissions s ON s.team_id=tm.id WHERE m.user_id=?", (uid,)):
                if r["id"] not in on_stage:
                    eligible.append(dict(r))
        out["eligible_teams"] = eligible
        out["my_team_ids"] = [r["team_id"] for r in rows if uid and any(m["id"] == uid for m in r["members"])]
    return 200, out


@route("POST", r"/api/live/([a-z0-9-]+)/react")
def react(c, occ_id):
    u = c.me()
    o = find_occ(c, occ_id)
    require_live(o)
    emoji = c.body.get("emoji")
    if emoji not in EMOJIS:
        raise ApiError(400, "Unknown reaction")
    # Rapid tapping is welcome, but not a firehose: at most ~5 reactions a second per person.
    key, t = (u["id"], o["id"]), time.time()
    if t - c.srv.react_times.get(key, 0) < 0.2:
        raise ApiError(429, "Easy there")
    c.srv.react_times[key] = t
    slot = -1
    if o["key"] == "closing":
        phase, current = closing_phase(o, now())
        if phase == "demos" and c.db.execute("SELECT 1 FROM lineup WHERE occ_id=? AND position=?", (o["id"], current)).fetchone():
            slot = current  # applause goes to whoever is on stage right now
    c.db.execute("INSERT INTO reactions(occ_id,slot,emoji,n) VALUES(?,?,?,1)"
                 " ON CONFLICT(occ_id,slot,emoji) DO UPDATE SET n=n+1", (o["id"], slot, emoji))
    return 200, {"slot": slot}


@route("POST", r"/api/live/([a-z0-9-]+)/ideas")
def pitch_idea(c, occ_id):
    u = c.me()
    o = find_occ(c, occ_id)
    if o["key"] != "kickoff":
        raise ApiError(400, "Ideas are pitched at the Monday Kickoff")
    require_live(o)
    if u["role"] != "hacker":
        raise ApiError(403, "Only hackers pitch ideas")
    if c.db.execute("SELECT COUNT(*) FROM ideas WHERE occ_id=? AND user_id=?", (o["id"], u["id"])).fetchone()[0] >= 3:
        raise ApiError(409, "Three ideas max — rally people around one")
    iid = c.db.execute("INSERT INTO ideas(occ_id,user_id,text,created_at) VALUES(?,?,?,?)",
                       (o["id"], u["id"], text(c.body, "text", True, 140), now())).lastrowid
    return 201, {"idea_id": iid}


def get_idea(db, iid):
    r = db.execute("SELECT * FROM ideas WHERE id=?", (int(iid),)).fetchone()
    if not r:
        raise ApiError(404, "Idea not found")
    return r


@route("POST", r"/api/ideas/(\d+)/fan")
def fan_idea(c, iid):
    u = c.me()
    idea = get_idea(c.db, iid)
    if idea["user_id"] == u["id"]:
        raise ApiError(400, "That's your own idea")
    if u["role"] != "hacker":
        raise ApiError(403, "Only hackers can join ideas")
    if c.db.execute("DELETE FROM idea_fans WHERE idea_id=? AND user_id=?", (idea["id"], u["id"])).rowcount == 0:
        c.db.execute("INSERT INTO idea_fans(idea_id,user_id) VALUES(?,?)", (idea["id"], u["id"]))
        notify(c.db, [idea["user_id"]], f"🙋 @{u['handle']} is in on your idea: {idea['text'][:60]}", f"#/live/{idea['occ_id']}")
        return 200, {"in": True}
    return 200, {"in": False}


@route("POST", r"/api/ideas/(\d+)/form-team")
def idea_to_team(c, iid):
    """One click from a pitched idea to a real team: create it, then invite everyone who tapped “I'm in”."""
    u = c.me()
    idea = get_idea(c.db, iid)
    if idea["user_id"] != u["id"]:
        raise ApiError(403, "Only the person who pitched it can form the team")
    if idea["team_id"]:
        raise ApiError(409, "This idea already became a team")
    tid = make_team(c.db, u, dict(c.body, idea=idea["text"]))
    team = get_team(c.db, tid)
    invited, busy = 0, 0
    for f in c.db.execute("SELECT user_id FROM idea_fans WHERE idea_id=?", (idea["id"],)).fetchall():
        if team_for_user_in_challenge(c.db, f["user_id"], team["challenge_id"]):
            busy += 1  # already on a team for this challenge
            continue
        c.db.execute("INSERT INTO requests(team_id,user_id,kind,message,created_at) VALUES(?,?,?,?,?)",
                     (tid, f["user_id"], "invite", f"You tapped “I'm in” on: {idea['text']}", now()))
        notify(c.db, [f["user_id"]], f"🎉 Your Kickoff idea became a team: {team['name']} — accept to join", "#/inbox")
        invited += 1
    c.db.execute("UPDATE ideas SET team_id=? WHERE id=?", (tid, idea["id"]))
    return 201, {"team_id": tid, "invited": invited, "already_on_a_team": busy}


@route("POST", r"/api/live/([a-z0-9-]+)/checkin")
def ritual_checkin(c, occ_id):
    u = c.me()
    o = find_occ(c, occ_id)
    if o["key"] != "checkin":
        raise ApiError(400, "Not a check-in")
    require_live(o)
    if c.db.execute("SELECT 1 FROM posts WHERE ritual=? AND user_id=?", (o["id"], u["id"])).fetchone():
        raise ApiError(409, "You already checked in tonight")
    team = current_team(c.db, u["id"])
    # Check-ins are ship-log posts too, so they show up on the Floor.
    c.db.execute("INSERT INTO posts(user_id,kind,text,tags,team_id,ritual,created_at) VALUES(?,?,?,?,?,?,?)",
                 (u["id"], "update", text(c.body, "text", True, 280), "[]", team["id"] if team else None, o["id"], now()))
    return 201, {"streak": checkin_streak(c.db, u["id"])}


@route("POST", r"/api/live/([a-z0-9-]+)/lineup")
def join_lineup(c, occ_id):
    u = c.me()
    o = find_occ(c, occ_id)
    if o["key"] != "closing":
        raise ApiError(400, "The lineup is for the Closing Ceremony")
    t = now()
    phase, current = closing_phase(o, t)
    if phase not in ("upcoming", "intro", "demos"):
        raise ApiError(400, "The demo lineup is closed")
    if o["starts_at"] - t > 2 * DAY:
        raise ApiError(400, "The lineup opens two days before the ceremony")
    r = get_team(c.db, int_field(c.body, "team_id", 0, 1, 10 ** 9))
    if not c.db.execute("SELECT 1 FROM members WHERE team_id=? AND user_id=?", (r["id"], u["id"])).fetchone():
        raise ApiError(403, "Only team members can put the team on stage")
    if not c.db.execute("SELECT 1 FROM submissions WHERE team_id=?", (r["id"],)).fetchone():
        raise ApiError(400, "Submit your project first, then take the stage")
    zoom = zoom_url(c.body, "zoom_url") if c.body.get("zoom_url") else (c.db.execute(
        "SELECT zoom_url FROM demos WHERE team_id=? ORDER BY created_at DESC LIMIT 1", (r["id"],)).fetchone() or [None])[0]
    if not zoom:
        raise ApiError(400, "Add the Zoom link you'll present from")
    if c.db.execute("SELECT 1 FROM lineup WHERE occ_id=? AND team_id=?", (o["id"], r["id"])).fetchone():
        raise ApiError(409, "You're already in the lineup")
    # Take the next open slot that hasn't started yet; the write lock keeps two teams off the same slot.
    if not c.db.in_transaction:
        c.db.execute("BEGIN IMMEDIATE")
    taken = c.db.execute("SELECT MAX(position) FROM lineup WHERE occ_id=?", (o["id"],)).fetchone()[0]
    position = max(-1 if taken is None else taken, current if phase == "demos" else -1) + 1
    if position >= max_slots(o):
        raise ApiError(409, "The lineup is full this week — there's always next Sunday")
    c.db.execute("INSERT INTO lineup(occ_id,team_id,position,zoom_url,created_at) VALUES(?,?,?,?,?)",
                 (o["id"], r["id"], position, zoom, t))
    start, _ = slot_window(o, position)
    log_team(c.db, r["id"], u["id"], f"put the team on stage at the Closing Ceremony (slot {position + 1})")
    return 201, {"position": position, "slot_start": start}


@route("POST", r"/api/live/([a-z0-9-]+)/lineup/leave")
def leave_lineup(c, occ_id):
    u = c.me()
    o = find_occ(c, occ_id)
    tid = int_field(c.body, "team_id", 0, 1, 10 ** 9)
    row = c.db.execute("SELECT * FROM lineup WHERE occ_id=? AND team_id=?", (o["id"], tid)).fetchone()
    if not row:
        raise ApiError(404, "Not in the lineup")
    if not c.db.execute("SELECT 1 FROM members WHERE team_id=? AND user_id=?", (tid, u["id"])).fetchone():
        raise ApiError(403, "Only team members can do that")
    if now() >= slot_window(o, row["position"])[0]:
        raise ApiError(400, "Your slot has already started")
    c.db.execute("DELETE FROM lineup WHERE occ_id=? AND team_id=?", (o["id"], tid))
    return 200, {"ok": True}


def run_ritual_notices(db, demo=None, t=None):
    """Tell people a ritual is about to start / has started. Idempotent per (ritual, phase)."""
    t = t or now()
    sent = 0
    for o in occurrences(t - 180, t + 600, demo):
        phases = []
        if o["key"] != "checkin" and o["starts_at"] - 600 <= t < o["starts_at"]:
            phases.append(("soon", f"⏰ {o['title']} starts in {max(1, (o['starts_at'] - t + 59) // 60)} min"))
        if o["starts_at"] <= t < o["starts_at"] + 180:
            phases.append(("live", f"🔴 {o['title']} is live — come join"))
        for phase, message in phases:
            if db.execute("INSERT OR IGNORE INTO ritual_notices(occ_id,phase) VALUES(?,?)", (o["id"], phase)).rowcount:
                users = [r["id"] for r in db.execute("SELECT id, tz FROM users")
                         if o["region"] is None or region_of(r["tz"]) == o["region"]]
                notify(db, users, message, f"#/live/{o['id']}")
                sent += 1
    return sent


def ritual_notice_loop(db_path, srv):
    while True:
        db = connect(db_path)
        try:
            run_ritual_notices(db, srv.demo_ritual)
            db.commit()
        except Exception:
            traceback.print_exc()
        finally:
            db.close()
        time.sleep(30)


# --- finishing a project, and its live Demo Stage ---

@route("POST", r"/api/teams/(\d+)/finish")
def finish_team(c, tid):
    """Close the roster, lock in the submission, and move the team to its demo stage. Any member can do it."""
    u = c.me()
    r = get_team(c.db, int(tid))
    if not is_member(c.db, r["id"], u["id"]):
        raise ApiError(403, "Only team members can finish the project")
    if r["status"] == "shipped":
        raise ApiError(409, "Already shipped")
    if c.body.get("title"):
        save_submission(c.db, r, u, c.body)
    elif not c.db.execute("SELECT 1 FROM submissions WHERE team_id=?", (r["id"],)).fetchone():
        raise ApiError(400, "Add your submission (title + repo or demo link) to finish")
    t = now()
    c.db.execute("UPDATE teams SET status='shipped', shipped_at=? WHERE id=?", (t, r["id"]))
    pending = c.db.execute("SELECT * FROM requests WHERE team_id=? AND status='pending'", (r["id"],)).fetchall()
    c.db.execute("UPDATE requests SET status='withdrawn' WHERE team_id=? AND status='pending'", (r["id"],))
    notify(c.db, [p["user_id"] for p in pending], f"{r['name']} shipped their project and closed the roster — find another team?", "#/teams")
    members = [m["id"] for m in team_members(c.db, r["id"])]
    notify(c.db, [m for m in members if m != u["id"]], f"🏁 @{u['handle']} finished {r['name']} — your demo stage is ready", f"#/t/{r['id']}/stage")
    log_team(c.db, r["id"], u["id"], "finished the project 🏁 — roster closed, on to the demo")
    return 200, {"ok": True, "withdrawn": len(pending)}


@route("POST", r"/api/teams/(\d+)/reopen")
def reopen_team(c, tid):
    u = c.me()
    r = get_team(c.db, int(tid))
    if not is_member(c.db, r["id"], u["id"]):
        raise ApiError(403, "Only team members can reopen the project")
    if r["status"] != "shipped":
        raise ApiError(409, "The team is still building")
    if r["c_ends"] <= now():
        raise ApiError(400, "The challenge is over — no reopening now")
    if stage_demo(c.db, r["id"]):
        raise ApiError(409, "End the live demo first")
    c.db.execute("UPDATE teams SET status='building', shipped_at=NULL WHERE id=?", (r["id"],))
    log_team(c.db, r["id"], u["id"], "reopened the project to keep building")
    return 200, {"ok": True}


STAGE_WINDOW = 10   # seconds; stage clients heartbeat every ~1.5s
STAGE_MAX_VIEWERS = 30  # each viewer is a direct connection from every presenter; beyond this, use an SFU


def stage_demo(db, team_id, include_ended=False):
    """The team's live stage demo, or with include_ended its most recent one."""
    where = "" if include_ended else " AND ended_at IS NULL AND starts_at + duration_min*60 > ?"
    args = (team_id,) if include_ended else (team_id, now())
    return db.execute("SELECT * FROM demos WHERE team_id=? AND stage=1" + where + " ORDER BY starts_at DESC LIMIT 1",
                      args).fetchone()


def stage_people(db, team_id):
    return db.execute("SELECT * FROM stage_presence WHERE team_id=? AND last_seen>? ORDER BY role DESC, session",
                      (team_id, now() - STAGE_WINDOW)).fetchall()


def is_member(db, team_id, uid):
    return uid is not None and db.execute("SELECT 1 FROM members WHERE team_id=? AND user_id=?", (team_id, uid)).fetchone() is not None


@route("GET", r"/api/teams/(\d+)/stage")
def stage(c, tid):
    r = get_team(c.db, int(tid))
    uid = c.user["id"] if c.user else None
    live = stage_demo(c.db, r["id"])
    shown = live or stage_demo(c.db, r["id"], include_ended=True)
    sub = c.db.execute("SELECT * FROM submissions WHERE team_id=?", (r["id"],)).fetchone()
    people = stage_people(c.db, r["id"])
    out = {"team": team_out(c.db, r), "submission": dict(sub) if sub else None, "presenter": is_member(c.db, r["id"], uid),
           "live": bool(live), "demo": None, "viewers": sum(1 for p in people if p["role"] == "viewer"),
           "presenters": [{"user": user_out(c.db.execute("SELECT * FROM users WHERE id=?", (p["user_id"],)).fetchone()),
                           "screen": bool(p["screen"]), "cam": bool(p["cam"]), "mic": bool(p["mic"])}
                          for p in people if p["role"] == "presenter"],
           "questions": [], "reactions": {}, "emojis": EMOJIS}
    if shown:
        d = dict(shown)
        d["status"] = demo_status(shown, now())
        out["demo"] = d
        out["reactions"] = reaction_counts(c.db, f"stage-{shown['id']}").get(-1, {})
        out["questions"] = [dict(q, user=user_out(q)) for q in c.db.execute(
            "SELECT q.id AS qid, q.text AS qtext, q.answered, q.created_at AS asked_at, u.* FROM stage_questions q"
            " JOIN users u ON u.id=q.user_id WHERE q.demo_id=? ORDER BY q.answered, q.created_at", (shown["id"],))]
        out["questions"] = [{"id": q["qid"], "text": q["qtext"], "answered": bool(q["answered"]), "created_at": q["asked_at"],
                             "user": q["user"]} for q in out["questions"]]
    return 200, out


@route("POST", r"/api/teams/(\d+)/stage/start")
def stage_start(c, tid):
    u = c.me()
    r = get_team(c.db, int(tid))
    if not is_member(c.db, r["id"], u["id"]):
        raise ApiError(403, "Only the team can go live")
    if r["status"] != "shipped":
        raise ApiError(400, "Finish the project first — then the stage is yours")
    if stage_demo(c.db, r["id"]):
        raise ApiError(409, "You're already live")
    sub = c.db.execute("SELECT title FROM submissions WHERE team_id=?", (r["id"],)).fetchone()
    title = text(c.body, "title", max_len=80) or (sub["title"] if sub else f"{r['name']} demo")
    t = now()
    did = c.db.execute("INSERT INTO demos(team_id,title,zoom_url,starts_at,duration_min,created_by,created_at,stage)"
                       " VALUES(?,?,?,?,?,?,?,1)", (r["id"], title, "", t, 60, u["id"], t)).lastrowid
    members = {m["id"] for m in team_members(c.db, r["id"])}
    notify(c.db, [x["id"] for x in c.db.execute("SELECT id FROM users") if x["id"] not in members],
           f"🎬 {r['name']} is demoing live now: {title}", f"#/t/{r['id']}/stage")
    log_team(c.db, r["id"], u["id"], "went live on the demo stage 🎬")
    return 201, {"demo_id": did}


@route("POST", r"/api/teams/(\d+)/stage/end")
def stage_end(c, tid):
    u = c.me()
    r = get_team(c.db, int(tid))
    if not is_member(c.db, r["id"], u["id"]):
        raise ApiError(403, "Only the team can end the demo")
    d = stage_demo(c.db, r["id"])
    if not d:
        raise ApiError(409, "Not live")
    t = now()
    c.db.execute("UPDATE demos SET ended_at=? WHERE id=?", (t, d["id"]))
    reacts = sum(reaction_counts(c.db, f"stage-{d['id']}").get(-1, {}).values())
    questions = c.db.execute("SELECT COUNT(*) FROM stage_questions WHERE demo_id=?", (d["id"],)).fetchone()[0]
    log_team(c.db, r["id"], u["id"], f"ended the demo — {d['peak']} watching at peak, {reacts} reactions, {questions} questions")
    return 200, {"minutes": max(1, (t - d["starts_at"]) // 60), "peak": d["peak"], "reactions": reacts, "questions": questions}


@route("POST", r"/api/teams/(\d+)/stage/heartbeat")
def stage_heartbeat(c, tid):
    """Presence + signaling for the stage. Presenters (team members) see every viewer so they can call them;
    viewers only see presenters. Viewers are admitted while the team is live, up to STAGE_MAX_VIEWERS."""
    u = c.me()
    r = get_team(c.db, int(tid))
    b, t = c.body, now()
    session = session_field(b, "session")
    presenter = is_member(c.db, r["id"], u["id"])
    live = stage_demo(c.db, r["id"])
    known = c.db.execute("SELECT 1 FROM stage_presence WHERE team_id=? AND session=? AND last_seen>?",
                         (r["id"], session, t - STAGE_WINDOW)).fetchone()
    if not presenter:
        if not live:
            c.db.execute("DELETE FROM stage_presence WHERE team_id=? AND session=?", (r["id"], session))
            return 200, {"live": False, "participants": [], "signals": [], "viewers": 0}
        viewers = c.db.execute("SELECT COUNT(*) FROM stage_presence WHERE team_id=? AND role='viewer' AND last_seen>?",
                               (r["id"], t - STAGE_WINDOW)).fetchone()[0]
        if not known and viewers >= STAGE_MAX_VIEWERS:
            return 200, {"live": True, "full": True, "participants": [], "signals": [], "viewers": viewers}
    c.db.execute("INSERT INTO stage_presence(team_id,session,user_id,role,screen,cam,mic,last_seen) VALUES(?,?,?,?,?,?,?,?)"
                 " ON CONFLICT(team_id,session) DO UPDATE SET screen=excluded.screen, cam=excluded.cam, mic=excluded.mic,"
                 " last_seen=excluded.last_seen",
                 (r["id"], session, u["id"], "presenter" if presenter else "viewer",
                  1 if presenter and b.get("screen") else 0, 1 if presenter and b.get("cam") else 0,
                  1 if presenter and b.get("mic") else 0, t))
    c.db.execute("DELETE FROM stage_presence WHERE last_seen<?", (t - 5 * STAGE_WINDOW,))
    people = stage_people(c.db, r["id"])
    viewers = sum(1 for p in people if p["role"] == "viewer")
    if live and viewers > live["peak"]:
        c.db.execute("UPDATE demos SET peak=? WHERE id=?", (viewers, live["id"]))
    since = int_field(b, "since", 0, 0, 10 ** 12)
    signals = [{"id": x["id"], "from": x["from_session"], "kind": x["kind"], "payload": json.loads(x["payload"])}
               for x in c.db.execute("SELECT * FROM signals WHERE team_id=? AND to_session=? AND id>? ORDER BY id",
                                     (r["id"], session, since))]
    visible = [p for p in people if presenter or p["role"] == "presenter"]
    return 200, {"live": bool(live), "viewers": viewers, "signals": signals,
                 "participants": [{"session": p["session"], "user_id": p["user_id"], "role": p["role"],
                                   "screen": bool(p["screen"]), "cam": bool(p["cam"]), "mic": bool(p["mic"])} for p in visible]}


@route("POST", r"/api/teams/(\d+)/stage/signal")
def stage_signal(c, tid):
    u = c.me()
    r = get_team(c.db, int(tid))
    b = c.body
    frm, to = session_field(b, "session"), session_field(b, "to")
    me_row = c.db.execute("SELECT role FROM stage_presence WHERE team_id=? AND session=? AND user_id=?", (r["id"], frm, u["id"])).fetchone()
    them = c.db.execute("SELECT role FROM stage_presence WHERE team_id=? AND session=?", (r["id"], to)).fetchone()
    if not me_row:
        raise ApiError(403, "Join the stage first")
    if not them:
        raise ApiError(404, "They left")
    if "presenter" not in (me_row["role"], them["role"]):
        raise ApiError(403, "Viewers only connect to presenters")
    if b.get("kind") not in ("offer", "answer", "bye"):
        raise ApiError(400, "kind must be offer, answer or bye")
    payload = json.dumps(b.get("payload"))
    if len(payload) > 20_000:
        raise ApiError(413, "Signal too large")
    c.db.execute("INSERT INTO signals(team_id,from_session,to_session,kind,payload,created_at) VALUES(?,?,?,?,?,?)",
                 (r["id"], frm, to, b["kind"], payload, now()))
    return 201, {"ok": True}


@route("POST", r"/api/teams/(\d+)/stage/leave")
def stage_leave(c, tid):
    u = c.me()
    c.db.execute("DELETE FROM stage_presence WHERE team_id=? AND session=? AND user_id=?",
                 (int(tid), session_field(c.body, "session"), u["id"]))
    return 200, {"ok": True}


def live_stage_demo(c, tid):
    d = stage_demo(c.db, int(tid))
    if not d:
        raise ApiError(400, "This team isn't live right now")
    return d


@route("POST", r"/api/teams/(\d+)/stage/react")
def stage_react(c, tid):
    u = c.me()
    d = live_stage_demo(c, tid)
    emoji = c.body.get("emoji")
    if emoji not in EMOJIS:
        raise ApiError(400, "Unknown reaction")
    key, t = (u["id"], f"stage-{d['id']}"), time.time()
    if t - c.srv.react_times.get(key, 0) < 0.2:
        raise ApiError(429, "Easy there")
    c.srv.react_times[key] = t
    c.db.execute("INSERT INTO reactions(occ_id,slot,emoji,n) VALUES(?,?,?,1) ON CONFLICT(occ_id,slot,emoji) DO UPDATE SET n=n+1",
                 (f"stage-{d['id']}", -1, emoji))
    return 200, {"ok": True}


@route("POST", r"/api/teams/(\d+)/stage/questions")
def stage_ask(c, tid):
    u = c.me()
    d = live_stage_demo(c, tid)
    if c.db.execute("SELECT COUNT(*) FROM stage_questions WHERE demo_id=? AND user_id=? AND answered=0",
                    (d["id"], u["id"])).fetchone()[0] >= 3:
        raise ApiError(429, "You have 3 open questions — let them answer first")
    qid = c.db.execute("INSERT INTO stage_questions(demo_id,user_id,text,created_at) VALUES(?,?,?,?)",
                       (d["id"], u["id"], text(c.body, "text", True, 280), now())).lastrowid
    return 201, {"question_id": qid}


@route("POST", r"/api/teams/(\d+)/stage/questions/(\d+)/answered")
def stage_answered(c, tid, qid):
    u = c.me()
    if not is_member(c.db, int(tid), u["id"]):
        raise ApiError(403, "Only presenters can mark questions answered")
    q = c.db.execute("SELECT q.* FROM stage_questions q JOIN demos d ON d.id=q.demo_id WHERE q.id=? AND d.team_id=?",
                     (int(qid), int(tid))).fetchone()
    if not q:
        raise ApiError(404, "Question not found")
    c.db.execute("UPDATE stage_questions SET answered=1-answered WHERE id=?", (q["id"],))
    return 200, {"answered": not q["answered"]}


# --- Build lab: the team's shared mini project + a coding agent ---
#
# Each team has three files (index.html / styles.css / app.js) stored as versioned snapshots. Teammates edit them by
# hand or ask the agent. The agent never writes files itself: it returns a proposal that a teammate applies or discards.
# With the Anthropic SDK installed and credentials configured it calls Claude; otherwise it falls back to a few
# built-in templates and says so.

BUILD_FILES = ("index.html", "styles.css", "app.js")
BUILD_MAX_FILE = 60_000
AGENT_MODEL = "claude-opus-5-5"
AGENT_HOURLY_LIMIT = 20
AGENT_SYSTEM = """You are the build agent inside a hackathon team's workspace. The team is building a small static web \
prototype made of exactly three files: index.html, styles.css and app.js. index.html links them with \
<link rel="stylesheet" href="styles.css"> and <script src="app.js"></script>.

The preview runs in a sandboxed iframe: scripts run, but there is no backend, no cookies or storage you can rely on, \
and network requests may fail. Keep the prototype self-contained (no build step, no frameworks, no CDN imports) and \
use realistic sample data where the idea needs data.

Make the change the teammate asks for, building on the current files rather than starting over unless they ask you \
to. Write accessible, responsive markup. Return every file you change with its complete new contents, and leave \
unchanged files out. In the summary, tell the team in two or three sentences what you changed and anything they \
should check."""
AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "files": {"type": "array", "items": {
            "type": "object",
            "properties": {"path": {"type": "string", "enum": list(BUILD_FILES)}, "content": {"type": "string"}},
            "required": ["path", "content"], "additionalProperties": False}},
    },
    "required": ["summary", "files"], "additionalProperties": False,
}


def agent_mode():
    """'claude' when the SDK is importable and credentials are configured, else 'simulated'. AOH_AGENT overrides."""
    forced = os.environ.get("AOH_AGENT", "").lower()
    if forced in ("claude", "simulated"):
        return forced
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return "simulated"
    has_creds = any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"))
    return "claude" if has_creds else "simulated"


def starter_files(name, idea):
    title = name.replace("<", "").replace(">", "")
    pitch = (idea or "A prototype we're building together.").replace("<", "").replace(">", "")
    return {
        "index.html": f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <main class="hero">
    <span class="kicker">Prototype · v0</span>
    <h1>{title}</h1>
    <p>{pitch}</p>
    <button id="cta">Try it</button>
    <p id="out" role="status"></p>
  </main>
  <script src="app.js"></script>
</body>
</html>
""",
        "styles.css": """body { margin: 0; font-family: system-ui, sans-serif; background: #f8faff; color: #18213d; }
.hero { max-width: 640px; margin: 12vh auto; padding: 0 24px; }
.kicker { font-size: 12px; letter-spacing: .12em; text-transform: uppercase; color: #6750eb; }
h1 { font-size: clamp(36px, 6vw, 56px); letter-spacing: -.03em; margin: 12px 0; }
p { color: #626e87; line-height: 1.7; }
button { font: inherit; font-weight: 600; color: #fff; border: 0; border-radius: 10px; padding: 12px 18px;
  background: linear-gradient(120deg, #2f65f4, #6750eb); cursor: pointer; }
button:focus-visible { outline: 3px solid #9b85ff; outline-offset: 3px; }
""",
        "app.js": """document.getElementById('cta').addEventListener('click', () => {
  document.getElementById('out').textContent = 'It works! Ask the build agent for the next step.';
});
""",
    }


def build_head(db, team_id):
    return db.execute("SELECT * FROM build_versions WHERE team_id=? ORDER BY id DESC LIMIT 1", (team_id,)).fetchone()


def ensure_build(db, team):
    head = build_head(db, team["id"])
    if head:
        return head
    db.execute("INSERT INTO build_versions(team_id,note,files,user_id,created_at) VALUES(?,?,?,?,?)",
               (team["id"], "Starter files", json.dumps(starter_files(team["name"], team["idea"])), None, now()))
    return build_head(db, team["id"])


def clean_files(raw, partial=False):
    """Validate a {path: content} map from a client or the agent."""
    if not isinstance(raw, dict):
        raise ApiError(400, "files must be an object of path → content")
    out = {}
    for path, content in raw.items():
        if path not in BUILD_FILES:
            raise ApiError(400, f"Unknown file {path!r} — the project has {', '.join(BUILD_FILES)}")
        if not isinstance(content, str) or len(content) > BUILD_MAX_FILE:
            raise ApiError(400, f"{path} must be text under {BUILD_MAX_FILE // 1000} KB")
        out[path] = content
    if not partial and set(out) != set(BUILD_FILES):
        raise ApiError(400, "Send all three files")
    return out


def save_version(db, team_id, files, note, uid):
    db.execute("INSERT INTO build_versions(team_id,note,files,user_id,created_at) VALUES(?,?,?,?,?)",
               (team_id, note[:200], json.dumps(files), uid, now()))
    # Keep the 40 most recent versions per team.
    db.execute("DELETE FROM build_versions WHERE team_id=? AND id NOT IN"
               " (SELECT id FROM build_versions WHERE team_id=? ORDER BY id DESC LIMIT 40)", (team_id, team_id))
    return build_head(db, team_id)


def run_out(db, r):
    who = db.execute("SELECT handle, name FROM users WHERE id=?", (r["user_id"],)).fetchone()
    return {"id": r["id"], "prompt": r["prompt"], "status": r["status"], "mode": r["mode"], "summary": r["summary"],
            "files": json.loads(r["files"]) if r["files"] else None, "error": r["error"], "base_version": r["base_version"],
            "created_at": r["created_at"], "finished_at": r["finished_at"],
            "user": {"id": r["user_id"], "handle": who["handle"], "name": who["name"]} if who else None}


@route("GET", r"/api/teams/(\d+)/build")
def build_state(c, tid):
    u, r = require_member(c, tid)
    head = ensure_build(c.db, r)
    names = {x["id"]: x["handle"] for x in c.db.execute("SELECT id, handle FROM users")}
    versions = [{"id": v["id"], "note": v["note"], "by": names.get(v["user_id"]), "created_at": v["created_at"]}
                for v in c.db.execute("SELECT id, note, user_id, created_at FROM build_versions WHERE team_id=?"
                                      " ORDER BY id DESC LIMIT 15", (r["id"],))]
    runs = [run_out(c.db, x) for x in c.db.execute(
        "SELECT * FROM (SELECT * FROM agent_runs WHERE team_id=? ORDER BY id DESC LIMIT 20) ORDER BY id", (r["id"],))]
    mode = agent_mode() if c.srv.agent_mode is None else c.srv.agent_mode
    return 200, {"files": json.loads(head["files"]), "version": head["id"], "versions": versions, "runs": runs,
                 "agent": {"mode": mode, "model": AGENT_MODEL if mode == "claude" else None},
                 "running": any(x["status"] == "running" for x in runs)}


@route("POST", r"/api/teams/(\d+)/build/files")
def build_save(c, tid):
    u, r = require_member(c, tid)
    head = ensure_build(c.db, r)
    files = dict(json.loads(head["files"]), **clean_files(c.body.get("files"), partial=True))
    v = save_version(c.db, r["id"], files, text(c.body, "note", max_len=200) or "Edited by hand", u["id"])
    return 201, {"version": v["id"]}


@route("POST", r"/api/teams/(\d+)/build/restore")
def build_restore(c, tid):
    u, r = require_member(c, tid)
    old = c.db.execute("SELECT * FROM build_versions WHERE id=? AND team_id=?",
                       (int_field(c.body, "version_id", 0, 1, 10 ** 9), r["id"])).fetchone()
    if not old:
        raise ApiError(404, "Version not found")
    v = save_version(c.db, r["id"], json.loads(old["files"]), f"Restored v{old['id']} ({old['note']})", u["id"])
    log_team(c.db, r["id"], u["id"], f"restored the build lab project to v{old['id']}")
    return 201, {"version": v["id"]}


@route("POST", r"/api/teams/(\d+)/agent")
def agent_start(c, tid):
    u, r = require_member(c, tid)
    prompt = text(c.body, "prompt", True, 2000)
    head = ensure_build(c.db, r)
    if c.db.execute("SELECT 1 FROM agent_runs WHERE team_id=? AND status='running'", (r["id"],)).fetchone():
        raise ApiError(409, "The agent is already working on a task for your team — wait for it to finish")
    if c.db.execute("SELECT COUNT(*) FROM agent_runs WHERE user_id=? AND created_at>?",
                    (u["id"], now() - 3600)).fetchone()[0] >= AGENT_HOURLY_LIMIT:
        raise ApiError(429, f"That's {AGENT_HOURLY_LIMIT} agent tasks this hour — take a breather")
    mode = agent_mode() if c.srv.agent_mode is None else c.srv.agent_mode
    rid = c.db.execute("INSERT INTO agent_runs(team_id,user_id,prompt,status,mode,base_version,created_at)"
                       " VALUES(?,?,?,?,?,?,?)", (r["id"], u["id"], prompt, "running", mode, head["id"], now())).lastrowid
    context = {"team": r["name"], "idea": r["idea"], "challenge": r["challenge_title"],
               "looking_for": jl(r["looking_for"])}
    sub = c.db.execute("SELECT title, description FROM submissions WHERE team_id=?", (r["id"],)).fetchone()
    if sub:
        context["submission"] = {"title": sub["title"], "description": sub["description"]}
    history = [{"prompt": x["prompt"], "summary": x["summary"], "status": x["status"]} for x in c.db.execute(
        "SELECT prompt, summary, status FROM agent_runs WHERE team_id=? AND id<? AND status IN ('applied','discarded')"
        " ORDER BY id DESC LIMIT 4", (r["id"], rid))][::-1]
    job = (c.srv.db_path, rid, mode, prompt, json.loads(head["files"]), context, history, c.srv.agent_delay)
    c.after_commit.append(lambda: threading.Thread(target=run_agent, args=job, daemon=True).start())
    log_team(c.db, r["id"], u["id"], f"asked the build agent: {prompt[:80]}")
    return 201, {"run": run_out(c.db, c.db.execute("SELECT * FROM agent_runs WHERE id=?", (rid,)).fetchone())}


def run_agent(db_path, rid, mode, prompt, files, context, history, delay):
    """Background worker: produce a proposal, then record it (or the failure) on the run."""
    status, summary, proposal, error = "ready", "", None, ""
    try:
        if mode == "claude":
            summary, proposal = call_claude(prompt, files, context, history)
        else:
            time.sleep(delay)  # lets the UI show its working state; the templates themselves are instant
            summary, proposal = simulated_agent(prompt, files, context)
        if not proposal:
            status, error = "failed", summary or "The agent didn't propose any file changes."
    except AgentError as e:
        status, error = "failed", str(e)
    except Exception:
        traceback.print_exc()
        status, error = "failed", "The agent hit an unexpected error. Try again in a moment."
    db = connect(db_path)
    try:
        db.execute("UPDATE agent_runs SET status=?, summary=?, files=?, error=?, finished_at=? WHERE id=?",
                   (status, summary, json.dumps(proposal) if proposal else None, error, now(), rid))
        db.commit()
    finally:
        db.close()


class AgentError(Exception):
    """A failure we can explain to the team."""


def call_claude(prompt, files, context, history):
    import anthropic

    client = anthropic.Anthropic()
    project = "\n\n".join(f'<file path="{p}">\n{files[p]}\n</file>' for p in BUILD_FILES)
    past = "\n".join(f"- {h['prompt']} → {h['status']}: {h['summary']}" for h in history) or "- (none yet)"
    content = (f"<team_context>\n{json.dumps(context, indent=2)}\n</team_context>\n\n"
               f"<earlier_tasks>\n{past}\n</earlier_tasks>\n\n<current_files>\n{project}\n</current_files>\n\n"
               f"<task>\n{prompt}\n</task>")
    try:
        with client.beta.messages.stream(
            model=AGENT_MODEL,
            max_tokens=64000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # on a safety decline, retry on Anthropic's recommended fallback model
            cache_control={"type": "ephemeral"},
            system=AGENT_SYSTEM,
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": AGENT_SCHEMA}},
            messages=[{"role": "user", "content": content}],
        ) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError:
        raise AgentError("The server's Anthropic credentials were rejected — ask whoever runs this server to check them.")
    except anthropic.RateLimitError:
        raise AgentError("The agent is rate-limited right now. Try again in a minute.")
    except anthropic.APIStatusError as e:
        raise AgentError(f"The Claude API returned an error ({e.status_code}). Try again shortly.")
    except anthropic.APIConnectionError:
        raise AgentError("Couldn't reach the Claude API from the server.")
    if message.stop_reason == "refusal":
        raise AgentError("Claude declined this task. Try rephrasing what you'd like built.")
    if message.stop_reason == "max_tokens":
        raise AgentError("The change was too large to finish in one go. Ask for a smaller step.")
    raw = next((b.text for b in message.content if b.type == "text"), "")
    try:
        data = json.loads(raw)
        changed = clean_files({f["path"]: f["content"] for f in data["files"]}, partial=True)
        return str(data["summary"])[:2000], changed
    except (ValueError, KeyError, TypeError, ApiError):
        raise AgentError("The agent's reply couldn't be read as file changes. Try again.")


def simulated_agent(prompt, files, context):
    """No model available: pick the closest built-in recipe and apply it to the team's real context."""
    p = prompt.lower()
    name, idea = context["team"], context.get("idea") or "Our hackathon prototype."
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    note = " (Simulated agent: no Claude API key is configured on this server, so this is a built-in template.)"
    if re.search(r"access|a11y|keyboard|contrast|screen reader", p):
        css = files["styles.css"].rstrip() + """

/* Accessibility pass */
:focus-visible { outline: 3px solid #6750eb; outline-offset: 3px; }
.skip { position: absolute; left: -999px; top: 8px; background: #fff; padding: 8px 12px; border-radius: 8px; }
.skip:focus { left: 8px; }
@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
"""
        html = files["index.html"]
        if 'class="skip"' not in html:
            html = re.sub(r"<body([^>]*)>", r'<body\1>\n  <a class="skip" href="#main">Skip to content</a>', html, count=1)
            html = re.sub(r"<main(?![^>]*\bid=)", '<main id="main"', html, count=1)
        return ("Added a skip link, visible keyboard focus and a reduced-motion rule, and gave the main region an id "
                "for the skip link. Tab through the preview to check the focus order." + note,
                {"index.html": html, "styles.css": css})
    if re.search(r"dashboard|progress|metric|stats|chart", p):
        html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(name)} · progress</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <main class="dash">
    <span class="kicker">Team dashboard · sample data</span>
    <h1>{esc(name)}</h1>
    <p>{esc(idea)}</p>
    <section class="cards" aria-label="Progress">
      <div class="card"><strong id="pct">0%</strong><span>milestone done</span></div>
      <div class="card"><strong id="open">0</strong><span>open tasks</span></div>
      <div class="card"><strong id="done">0</strong><span>shipped</span></div>
    </section>
    <div class="bar" aria-hidden="true"><span id="fill"></span></div>
    <ul id="tasks" class="tasks"></ul>
  </main>
  <script src="app.js"></script>
</body>
</html>
"""
        css = """body { margin: 0; font-family: system-ui, sans-serif; background: #f8faff; color: #18213d; }
.dash { max-width: 760px; margin: 8vh auto; padding: 0 24px; }
.kicker { font-size: 12px; letter-spacing: .12em; text-transform: uppercase; color: #6750eb; }
h1 { font-size: clamp(32px, 5vw, 48px); letter-spacing: -.03em; margin: 10px 0; }
p { color: #626e87; }
.cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 24px 0; }
.card { background: #fff; border: 1px solid #e1e6f1; border-radius: 14px; padding: 16px; }
.card strong { display: block; font-size: 28px; color: #2f65f4; }
.card span { color: #626e87; font-size: 13px; }
.bar { height: 8px; border-radius: 8px; background: #e7e9f6; overflow: hidden; }
#fill { display: block; height: 100%; width: 0; background: linear-gradient(90deg, #2f65f4, #8652e9); transition: width .4s; }
.tasks { list-style: none; padding: 0; margin: 20px 0; display: grid; gap: 8px; }
.tasks label { display: flex; gap: 10px; align-items: center; background: #fff; border: 1px solid #e1e6f1; border-radius: 10px; padding: 12px 14px; cursor: pointer; }
.tasks input { width: 18px; height: 18px; accent-color: #6750eb; }
@media (max-width: 560px) { .cards { grid-template-columns: 1fr; } }
"""
        js = """const tasks = [
  { title: 'Sketch the core user journey', done: true },
  { title: 'Build the first working screen', done: true },
  { title: 'Connect sample data', done: false },
  { title: 'Test with three people', done: false },
  { title: 'Record the demo', done: false },
];

function render() {
  const list = document.getElementById('tasks');
  list.innerHTML = '';
  tasks.forEach((t, i) => {
    const li = document.createElement('li');
    li.innerHTML = `<label><input type="checkbox" ${t.done ? 'checked' : ''}> <span></span></label>`;
    li.querySelector('span').textContent = t.title;
    li.querySelector('input').addEventListener('change', (e) => { tasks[i].done = e.target.checked; render(); });
    list.append(li);
  });
  const done = tasks.filter((t) => t.done).length;
  document.getElementById('pct').textContent = Math.round((done / tasks.length) * 100) + '%';
  document.getElementById('open').textContent = tasks.length - done;
  document.getElementById('done').textContent = done;
  document.getElementById('fill').style.width = (done / tasks.length) * 100 + '%';
}
render();
"""
        return ("Turned the page into a progress dashboard with sample tasks: tick a task and the metrics and "
                "progress bar update. Swap the sample tasks in app.js for your real ones." + note,
                {"index.html": html, "styles.css": css, "app.js": js})
    features = ["Start in seconds", "Built with real users", "Works on any device"]
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(name)}</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <header class="nav"><strong>{esc(name)}</strong><a href="#signup">Get early access</a></header>
  <main>
    <section class="hero">
      <span class="kicker">Built at the Always-On Hackathon</span>
      <h1>{esc(name)}</h1>
      <p>{esc(idea)}</p>
      <form id="signup" class="signup">
        <label for="email" class="sr">Email</label>
        <input id="email" type="email" required placeholder="you@example.com">
        <button>Join the waitlist</button>
      </form>
      <p id="thanks" role="status"></p>
    </section>
    <section class="features" aria-label="Why it matters">
      {''.join(f'<article><h2>{f}</h2><p>Replace this with what makes {esc(name)} different.</p></article>' for f in features)}
    </section>
  </main>
  <script src="app.js"></script>
</body>
</html>
"""
    css = """body { margin: 0; font-family: system-ui, sans-serif; background: radial-gradient(ellipse at 90% 0%, #ece8ff, #f8faff 45%); color: #18213d; }
.nav { display: flex; justify-content: space-between; align-items: center; max-width: 960px; margin: 0 auto; padding: 20px 24px; }
.nav a { color: #2f65f4; font-weight: 600; text-decoration: none; }
.hero { max-width: 960px; margin: 6vh auto; padding: 0 24px; }
.kicker { font-size: 12px; letter-spacing: .12em; text-transform: uppercase; color: #6750eb; }
h1 { font-size: clamp(40px, 7vw, 72px); letter-spacing: -.04em; margin: 12px 0; background: linear-gradient(100deg, #275ef5, #8652e9 65%, #c75bc6); -webkit-background-clip: text; background-clip: text; color: transparent; }
.hero p { max-width: 560px; color: #626e87; line-height: 1.7; font-size: 18px; }
.signup { display: flex; gap: 8px; margin-top: 24px; flex-wrap: wrap; }
.signup input { flex: 1; min-width: 200px; font: inherit; padding: 12px 14px; border: 1px solid #dce4f3; border-radius: 10px; }
.signup button { font: inherit; font-weight: 600; color: #fff; border: 0; border-radius: 10px; padding: 12px 18px; background: linear-gradient(120deg, #2f65f4, #6750eb); cursor: pointer; }
.features { max-width: 960px; margin: 0 auto 10vh; padding: 0 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }
.features article { background: #fff; border: 1px solid #e1e6f1; border-radius: 14px; padding: 20px; }
.features h2 { font-size: 17px; margin: 0 0 6px; }
.features p { color: #626e87; margin: 0; }
.sr { position: absolute; left: -999px; }
:focus-visible { outline: 3px solid #9b85ff; outline-offset: 3px; }
"""
    js = """document.getElementById('signup').addEventListener('submit', (e) => {
  e.preventDefault();
  const email = document.getElementById('email').value;
  document.getElementById('thanks').textContent = `Thanks! We'll write to ${email} when it's ready (demo only — nothing is sent).`;
  e.target.reset();
});
"""
    return ("Built a landing page from your team's idea: headline, waitlist form (demo only) and three feature "
            "cards to fill in." + note, {"index.html": html, "styles.css": css, "app.js": js})


def agent_run_row(c, tid, rid):
    u, r = require_member(c, tid)
    run = c.db.execute("SELECT * FROM agent_runs WHERE id=? AND team_id=?", (int(rid), r["id"])).fetchone()
    if not run:
        raise ApiError(404, "Agent task not found")
    if run["status"] != "ready":
        raise ApiError(409, "This proposal was already handled")
    return u, r, run


@route("POST", r"/api/teams/(\d+)/agent/(\d+)/apply")
def agent_apply(c, tid, rid):
    u, r, run = agent_run_row(c, tid, rid)
    head = ensure_build(c.db, r)
    if head["id"] != run["base_version"] and not c.body.get("force"):
        raise ApiError(409, "The files changed since the agent started — applying would overwrite those edits")
    files = dict(json.loads(head["files"]), **json.loads(run["files"]))
    v = save_version(c.db, r["id"], files, f"Agent: {run['prompt'][:120]}", u["id"])
    c.db.execute("UPDATE agent_runs SET status='applied' WHERE id=?", (run["id"],))
    log_team(c.db, r["id"], u["id"], f"applied the build agent's change (v{v['id']})")
    return 200, {"version": v["id"]}


@route("POST", r"/api/teams/(\d+)/agent/(\d+)/discard")
def agent_discard(c, tid, rid):
    u, r, run = agent_run_row(c, tid, rid)
    c.db.execute("UPDATE agent_runs SET status='discarded' WHERE id=?", (run["id"],))
    return 200, {"ok": True}


# --- builders directory: saved builders, connections, projects ---

@route("GET", "/api/saved")
def saved_list(c):
    u = c.me()
    return 200, {"saved": [r[0] for r in c.db.execute(
        "SELECT builder_id FROM saved_builders WHERE user_id=? ORDER BY created_at", (u["id"],))],
                 "connected": [r[0] for r in c.db.execute(
        "SELECT other_id FROM connections WHERE user_id=?", (u["id"],))]}


def builder_row(c, bid):
    r = c.db.execute("SELECT * FROM users WHERE id=? AND role='hacker'", (int(bid),)).fetchone()
    if not r:
        raise ApiError(404, "Builder not found")
    return r


@route("POST", r"/api/people/(\d+)/save")
def toggle_save(c, bid):
    u = c.me()
    b = builder_row(c, bid)
    if b["id"] == u["id"]:
        raise ApiError(400, "That's you")
    if c.db.execute("DELETE FROM saved_builders WHERE user_id=? AND builder_id=?", (u["id"], b["id"])).rowcount:
        return 200, {"saved": False}
    c.db.execute("INSERT INTO saved_builders(user_id,builder_id,created_at) VALUES(?,?,?)", (u["id"], b["id"], now()))
    return 200, {"saved": True}


@route("POST", r"/api/people/(\d+)/connect")
def connect_builder(c, bid):
    u = c.me()
    b = builder_row(c, bid)
    if b["id"] == u["id"]:
        raise ApiError(400, "That's you")
    if c.db.execute("SELECT 1 FROM connections WHERE user_id=? AND other_id=?", (u["id"], b["id"])).fetchone():
        return 200, {"connected": True, "already": True}
    c.db.execute("INSERT INTO connections(user_id,other_id,created_at) VALUES(?,?,?)", (u["id"], b["id"], now()))
    mutual = c.db.execute("SELECT 1 FROM connections WHERE user_id=? AND other_id=?", (b["id"], u["id"])).fetchone()
    notify(c.db, [b["id"]], f"🤝 @{u['handle']} {'connected back' if mutual else 'wants to connect'} — say hi?", f"#/u/{u['handle']}")
    return 200, {"connected": True, "mutual": bool(mutual)}


@route("GET", "/api/projects")
def projects(c):
    out = []
    for r in c.db.execute(
            "SELECT s.*, t.name AS team_name, ch.title AS challenge_title, ch.ends_at AS c_ends,"
            " (SELECT COUNT(*) FROM votes v WHERE v.submission_id=s.id) AS votes"
            " FROM submissions s JOIN teams t ON t.id=s.team_id JOIN challenges ch ON ch.id=s.challenge_id"
            " ORDER BY votes DESC, s.created_at DESC"):
        d = dict(r)
        d["stack"] = jl(r["stack"])
        d["members"] = team_members(c.db, r["team_id"])
        d["stage"] = "Shipped" if r["c_ends"] <= now() else "In progress"
        out.append(d)
    return 200, {"projects": out}


ONBOARDING_STEPS = ("brief", "catchup", "lab", "status")


@route("POST", r"/api/teams/(\d+)/onboarding")
def set_onboarding(c, tid):
    u, r = require_member(c, tid)
    step = c.body.get("step")
    if step not in ONBOARDING_STEPS:
        raise ApiError(400, "Unknown onboarding step")
    row = c.db.execute("SELECT steps FROM onboarding WHERE team_id=? AND user_id=?", (r["id"], u["id"])).fetchone()
    steps = set(json.loads(row["steps"])) if row else set()
    (steps.add if c.body.get("done") else steps.discard)(step)
    c.db.execute("INSERT INTO onboarding(team_id,user_id,steps) VALUES(?,?,?) ON CONFLICT(team_id,user_id) DO UPDATE SET"
                 " steps=excluded.steps", (r["id"], u["id"], json.dumps(sorted(steps))))
    return 200, {"steps": sorted(steps)}


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "AlwaysOnHackathon/0.1"

    def log_message(self, fmt, *args):
        if not getattr(self.server, "quiet", False):
            super().log_message(fmt, *args)

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def send_json(self, status, payload, cookie=None):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if cookie is not None:
            age = 30 * DAY if cookie else 0
            self.send_header("Set-Cookie", f"{COOKIE}={cookie}; Path=/; HttpOnly; SameSite=Lax; Max-Age={age}")
        self.end_headers()
        self.wfile.write(data)

    def send_raw(self, status, raw):
        data = raw.data.encode() if isinstance(raw.data, str) else raw.data
        self.send_response(status)
        self.send_header("Content-Type", raw.content_type)
        self.send_header("Content-Length", str(len(data)))
        if raw.filename:
            self.send_header("Content-Disposition", f'attachment; filename="{raw.filename}"')
        self.end_headers()
        self.wfile.write(data)

    def serve_static(self, path):
        rel = path.lstrip("/")
        target = os.path.realpath(os.path.join(STATIC, rel[len("static/"):] if rel.startswith("static/") else "index.html"))
        if not target.startswith(STATIC + os.sep) or not os.path.isfile(target):
            target = os.path.join(STATIC, "index.html")
        with open(target, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(target)[0] or "application/octet-stream") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def current_user(self, db):
        jar = SimpleCookie(self.headers.get("Cookie") or "")
        if COOKIE not in jar:
            return None
        return db.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
                          (jar[COOKIE].value,)).fetchone()

    def read_body(self, method):
        if method != "POST":
            return {}
        # Requiring a JSON content type blocks cross-site form posts (CSRF) without a token.
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            raise ApiError(415, "Send application/json")
        length = int(self.headers.get("Content-Length") or 0)
        if length > 256_000:  # room for three project files at 60 KB each
            raise ApiError(413, "Request too large")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            raise ApiError(400, "Invalid JSON")
        if not isinstance(body, dict):
            raise ApiError(400, "Expected a JSON object")
        return body

    def dispatch(self, method):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            if method != "GET":
                return self.send_json(405, {"error": "Method not allowed"})
            return self.serve_static(parsed.path)
        db = connect(self.server.db_path)
        try:
            ctx = Ctx(db, self.current_user(db), self.read_body(method), parse_qs(parsed.query), self.server)
            for m, rx, fn in ROUTES:
                match = rx.match(parsed.path)
                if m == method and match:
                    status, payload = fn(ctx, *match.groups())
                    db.commit()
                    for task in ctx.after_commit:
                        task()
                    if isinstance(payload, Raw):
                        return self.send_raw(status, payload)
                    return self.send_json(status, payload, ctx.set_cookie)
            raise ApiError(404, "Not found")
        except ApiError as e:
            db.rollback()
            self.send_json(e.status, {"error": e.message})
        except Exception:
            db.rollback()
            traceback.print_exc()
            self.send_json(500, {"error": "Something broke on our side"})
        finally:
            db.close()


def make_server(db_path, host="127.0.0.1", port=8000, quiet=False, auto_approve=0, live_ritual=None, ritual_notices=False):
    init_db(db_path)
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.db_path, srv.quiet = db_path, quiet
    srv.auto_approve = auto_approve  # seconds before join requests approve themselves; 0 = owners decide
    srv.react_times = {}
    srv.agent_mode = None   # None = detect (Claude when the SDK + credentials exist); tests pin "simulated"
    srv.agent_delay = 1.5   # simulated agent's pause, so its working state is visible
    srv.demo_ritual = None
    if live_ritual:
        # Demo mode: run one ritual right now. The ceremony starts just before its demos so the stage goes live in a minute.
        lead = CLOSING_INTRO - 60 if live_ritual == "closing" else 60
        srv.demo_ritual = {"key": live_ritual, "starts_at": now() - lead}
    if ritual_notices:
        threading.Thread(target=ritual_notice_loop, args=(db_path, srv), daemon=True).start()
    return srv


def main():
    ap = argparse.ArgumentParser(description="Always-On Hackathon server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "aoh.db"))
    ap.add_argument("--no-seed", action="store_true", help="don't load demo data into a fresh database")
    ap.add_argument("--auto-approve", type=float, default=float(os.environ.get("AOH_AUTO_APPROVE", 2)), metavar="SECONDS",
                    help="demo mode: approve join requests after this many seconds (default 2; 0 = owners approve)")
    ap.add_argument("--live-ritual", choices=sorted(RITUALS), default=os.environ.get("AOH_LIVE_RITUAL") or None,
                    help="demo mode: start this ritual right now instead of waiting for its scheduled time")
    args = ap.parse_args()
    fresh = not os.path.exists(args.db)
    srv = make_server(args.db, args.host, args.port, auto_approve=max(0.0, args.auto_approve),
                      live_ritual=args.live_ritual, ritual_notices=True)
    if fresh and not args.no_seed:
        import seed
        seed.seed(args.db)
        print("Seeded demo data.")
    if not args.no_seed:
        import seed
        if seed.seed_builders(args.db):
            print("Added the builders-directory demo data.")
        if seed.seed_hackathons(args.db):
            print("Added hackathon pages: AI Engineer NY (Luma), partner sponsors, info and food.")
    if srv.demo_ritual and not args.no_seed:
        import seed
        o = make_occ(srv.demo_ritual["key"], srv.demo_ritual["starts_at"])
        seed.seed_live_ritual(args.db, o)
        print(f"Demo mode: {o['title']} is live now → http://{args.host}:{args.port}/#/live/{o['id']}")
    print(f"Always-On Hackathon running at http://{args.host}:{args.port}")
    if srv.auto_approve:
        print(f"Demo mode: join requests auto-approve after {srv.auto_approve:g}s (--auto-approve 0 to turn off)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
