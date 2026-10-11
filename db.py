"""Database access: SQLite locally and in tests, Postgres in production (e.g. Neon on Vercel).

The app's SQL is written once, in SQLite's dialect. connect() returns a sqlite3 connection for a file path,
or a thin Postgres wrapper for a postgres:// URL that translates the few dialect differences:
placeholders, INSERT OR IGNORE / OR REPLACE, the new row's id, the write lock, and schema types.
"""
import re
import sqlite3
from decimal import Decimal

PG_PREFIXES = ("postgres://", "postgresql://")

# Tables with an integer `id` primary key: inserts into these get RETURNING id so .lastrowid works.
ID_TABLES = {"sponsors", "users", "challenges", "teams", "requests", "submissions", "events", "demos", "notifications",
             "posts", "replies", "perks", "ideas", "stage_questions", "agent_runs", "build_versions", "transcripts",
             "team_log", "signals"}
# Primary keys used to turn INSERT OR REPLACE into an upsert.
REPLACE_KEYS = {"scores": ("submission_id", "judge_id"), "ritual_presence": ("occ_id", "user_id")}


def is_postgres(target):
    return isinstance(target, str) and target.startswith(PG_PREFIXES)


def connect(target):
    if is_postgres(target):
        return PgConnection(target)
    db = sqlite3.connect(target, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


# ---------- SQL translation (SQLite dialect → Postgres) ----------

_INSERT_RE = re.compile(r"^\s*INSERT\s+(OR\s+(IGNORE|REPLACE)\s+)?INTO\s+([a-z_]+)\s*\(([^)]*)\)", re.I)


def translate(sql, has_params=True):
    """Rewrite one statement for Postgres. Returns (sql, returns_id)."""
    s = sql.strip()
    if re.match(r"^BEGIN\s+IMMEDIATE$", s, re.I):
        # SQLite takes the write lock up front; Postgres gets the same serialisation from an advisory lock.
        return "SELECT pg_advisory_xact_lock(424242)", False
    returns_id = False
    m = _INSERT_RE.match(s)
    if m:
        mode, table, cols = (m.group(2) or "").upper(), m.group(3).lower(), [c.strip() for c in m.group(4).split(",")]
        s = re.sub(r"^\s*INSERT\s+OR\s+(IGNORE|REPLACE)\s+INTO", "INSERT INTO", s, flags=re.I)
        if mode == "IGNORE":
            s += " ON CONFLICT DO NOTHING"
        elif mode == "REPLACE":
            keys = REPLACE_KEYS[table]
            sets = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in keys)
            s += f" ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {sets}"
        if table in ID_TABLES and not re.search(r"\bRETURNING\b", s, re.I):
            s += " RETURNING id"
            returns_id = True
    # In an upsert, an unqualified column on the right-hand side is ambiguous in Postgres.
    s = re.sub(r"DO UPDATE SET n=n\+1", "DO UPDATE SET n=reactions.n+1", s)
    if has_params:
        s = s.replace("%", "%%").replace("?", "%s")
    return s, returns_id


def translate_schema(script):
    """SQLite DDL → Postgres DDL: serial ids and 64-bit integers."""
    out = []
    for stmt in script.split(";"):
        stmt = stmt.strip()
        if not stmt or stmt.upper().startswith("PRAGMA"):
            continue
        stmt = re.sub(r"\bINTEGER PRIMARY KEY\b", "BIGSERIAL PRIMARY KEY", stmt)
        stmt = re.sub(r"\bINTEGER\b", "BIGINT", stmt)
        stmt = re.sub(r"\bADD COLUMN\b(?! IF NOT EXISTS)", "ADD COLUMN IF NOT EXISTS", stmt)
        out.append(stmt)
    return out


# ---------- Postgres wrapper with sqlite3-like behaviour ----------

class Row:
    """Behaves like sqlite3.Row: index or key access, keys(), iteration over values, dict(row)."""
    __slots__ = ("_keys", "_values")

    def __init__(self, keys, values):
        self._keys = keys
        self._values = tuple(float(v) if isinstance(v, Decimal) else v for v in values)

    def __getitem__(self, k):
        if isinstance(k, (int, slice)):
            return self._values[k]
        try:
            return self._values[self._keys.index(k)]
        except ValueError:
            raise IndexError(k)

    def keys(self):
        return list(self._keys)

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return f"Row({dict(zip(self._keys, self._values))!r})"


class PgCursor:
    def __init__(self, cur, returns_id):
        self._cur = cur
        self.rowcount = cur.rowcount
        self._keys = tuple(d.name for d in cur.description) if cur.description else ()
        self.lastrowid = None
        if returns_id:
            row = cur.fetchone()
            self.lastrowid = row[0] if row else None

    def fetchone(self):
        r = self._cur.fetchone() if self._keys else None
        return Row(self._keys, r) if r is not None else None

    def fetchall(self):
        return [Row(self._keys, r) for r in self._cur.fetchall()] if self._keys else []

    def __iter__(self):
        return iter(self.fetchall())


class PgConnection:
    def __init__(self, url):
        import psycopg  # only needed in production

        self._psycopg = psycopg
        self._conn = psycopg.connect(url, autocommit=False)

    @property
    def in_transaction(self):
        # BEGIN IMMEDIATE is translated to an advisory lock that is always safe to take, so always "not yet".
        return False

    def execute(self, sql, params=()):
        params = tuple(params) if params else ()
        text, returns_id = translate(sql, has_params=bool(params))
        cur = self._conn.cursor()
        cur.execute(text, params or None)
        return PgCursor(cur, returns_id)

    def executemany(self, sql, seq):
        rows = [tuple(p) for p in seq]
        if not rows:
            return None
        text, _ = translate(sql, has_params=True)
        self._conn.cursor().executemany(text, rows)
        return None

    def executescript(self, script):
        stmts = translate_schema(script)
        tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", script)
        have = {r[0] for r in self._conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")}
        self._conn.commit()
        if tables and set(tables) <= have:
            return  # already set up: skip the DDL, whose locks would queue behind live requests
        for stmt in stmts:
            self._conn.execute(stmt)
        self._conn.commit()

    def run_ddl(self, stmt):
        """Run one migration statement in its own transaction (a failure must not poison the rest)."""
        for s in translate_schema(stmt):
            try:
                self._conn.execute(s)
                self._conn.commit()
            except self._psycopg.Error:
                self._conn.rollback()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()
