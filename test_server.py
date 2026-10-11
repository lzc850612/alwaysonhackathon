"""End-to-end API tests. Run: python3 -m unittest -v"""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

import seed
import server
from server import DAY, connect, make_server, now


class Client:
    def __init__(self, base):
        self.base, self.cookie = base, None

    def call(self, path, body=None):
        req = urllib.request.Request(self.base + "/api" + path, method="POST" if body is not None else "GET")
        if body is not None:
            req.data = json.dumps(body).encode()
            req.add_header("Content-Type", "application/json")
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req) as res:
                status, raw, headers = res.status, res.read(), res.headers
        except urllib.error.HTTPError as e:
            status, raw, headers = e.code, e.read(), e.headers
        cookie = headers.get("Set-Cookie")
        if cookie:
            self.cookie = cookie.split(";")[0]
        return status, json.loads(raw or b"{}")

    def ok(self, path, body=None):
        status, data = self.call(path, body)
        assert status < 300, (path, status, data)
        return data


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, "test.db")
        cls.srv = make_server(cls.db, port=0, quiet=True)
        seed.seed(cls.db)
        seed.seed_builders(cls.db)
        seed.seed_hackathons(cls.db)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.tmp)

    def client(self, handle=None):
        c = Client(self.base)
        if handle:
            c.ok("/login", {"handle": handle})
        return c

    def signup(self, handle, **kw):
        c = Client(self.base)
        c.ok("/signup", dict({"handle": handle, "name": handle.title(), "skills": ["react"], "tz": 0}, **kw))
        return c

    def live_challenge(self, c):
        return next(x for x in c.ok("/challenges?status=live")["challenges"] if x["sponsor"]["id"])

    def test_open_sprint_always_live(self):
        live = self.client().ok("/challenges?status=live")["challenges"]
        self.assertTrue(any(c["sponsor"]["id"] is None for c in live))

    def test_static_and_spa_fallback(self):
        with urllib.request.urlopen(self.base + "/c/1") as res:
            self.assertIn(b"always-on", res.read())
        with urllib.request.urlopen(self.base + "/static/../server.py") as res:
            self.assertNotIn(b"import", res.read())  # traversal falls back to index.html

    def test_signup_validation(self):
        c = Client(self.base)
        self.assertEqual(c.call("/signup", {"handle": "Bad Handle", "name": "x"})[0], 400)
        self.assertEqual(c.call("/signup", {"handle": "ada", "name": "x"})[0], 409)
        self.assertEqual(c.call("/me", {"name": "x"})[0], 401)

    def test_json_required_for_posts(self):
        req = urllib.request.Request(self.base + "/api/logout", data=b"a=1", method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 415)

    def test_team_lifecycle(self):
        owner, joiner = self.signup("owner1"), self.signup("joiner1", skills=["ml", "python"])
        ch = self.live_challenge(owner)
        team = owner.ok("/teams", {"challenge_id": ch["id"], "name": "Testers", "looking_for": ["ml"], "max_size": 2})["team"]
        self.assertEqual([t["name"] for t in owner.ok("/me")["user"]["teams"]], ["Testers"])  # powers the nav link
        self.assertEqual(joiner.ok("/me")["user"]["teams"], [])
        self.assertEqual(owner.call("/teams", {"challenge_id": ch["id"], "name": "Dup"})[0], 409)

        # matching ranks the team for someone with the needed skill
        match = joiner.ok("/match/teams")["teams"]
        mine = next(t for t in match if t["id"] == team["id"])
        self.assertTrue(any("ml" in r for r in mine["reasons"]))

        rid = joiner.ok(f"/teams/{team['id']}/join", {"message": "hi"})["request_id"]
        self.assertEqual(joiner.call(f"/teams/{team['id']}/join", {})[0], 409)
        self.assertEqual(joiner.call(f"/requests/{rid}", {"action": "accept"})[0], 403)
        self.assertEqual(owner.ok("/me")["user"]["inbox"], 1)
        owner.ok(f"/requests/{rid}", {"action": "accept"})
        detail = owner.ok(f"/teams/{team['id']}")["team"]
        self.assertEqual(len(detail["members"]), 2)
        self.assertFalse(detail["open"])

        third = self.signup("third1")
        self.assertEqual(third.call(f"/teams/{team['id']}/join", {})[0], 409)  # full

        sub = joiner.ok("/submissions", {"team_id": team["id"], "title": "Thing", "repo_url": "https://github.com/x/y"})
        self.assertEqual(joiner.call("/submissions", {"team_id": team["id"], "title": "T", "repo_url": "javascript:alert(1)"})[0], 400)
        sid = sub["submission"]["id"]
        self.assertEqual(owner.call(f"/submissions/{sid}/vote", {})[0], 400)  # own team
        self.assertEqual(third.ok(f"/submissions/{sid}/vote", {})["votes"], 1)
        self.assertEqual(third.ok(f"/submissions/{sid}/vote", {})["votes"], 0)

        owner.ok(f"/teams/{team['id']}/leave", {})
        self.assertEqual(owner.ok(f"/teams/{team['id']}")["team"]["owner_id"], joiner.ok("/me")["user"]["id"])
        self.assertTrue(joiner.ok(f"/teams/{team['id']}/leave", {})["deleted"])
        self.assertEqual(joiner.ok("/me")["user"]["teams"], [])

    def test_invite_flow_and_suggestions(self):
        owner = self.signup("owner2")
        guest = self.signup("guest2", skills=["rust"], interests=["ai"])
        ch = self.live_challenge(owner)
        team = owner.ok("/teams", {"challenge_id": ch["id"], "name": "Rusty", "looking_for": ["rust"]})["team"]
        people = owner.ok(f"/teams/{team['id']}/suggestions")["people"]
        gid = guest.ok("/me")["user"]["id"]
        self.assertIn(gid, [p["id"] for p in people])
        self.assertEqual(guest.call(f"/teams/{team['id']}/invite", {"user_id": gid})[0], 403)
        rid = owner.ok(f"/teams/{team['id']}/invite", {"user_id": gid})["request_id"]
        self.assertEqual(len(guest.ok("/inbox")["invites"]), 1)
        guest.ok(f"/requests/{rid}", {"action": "accept"})
        self.assertIsNotNone(guest.ok(f"/challenges/{ch['id']}")["my_team_id"])

    def test_sponsor_flow(self):
        hacker = self.signup("hack3")
        self.assertEqual(hacker.call("/sponsor/analytics")[0], 403)
        sp = self.signup("acme", role="sponsor", org="Acme", color="#123456", product_url="https://acme.test")
        t = now()
        ch = sp.ok("/challenges", {"title": "Acme Quest", "tags": ["ai"], "starts_at": t - 60, "ends_at": t + 3 * DAY})["challenge"]
        self.assertEqual(ch["status"], "live")
        self.assertEqual(sp.call("/challenges", {"title": "Bad", "starts_at": t, "ends_at": t + 90 * DAY})[0], 400)
        hacker.ok(f"/challenges/{ch['id']}")
        hacker.ok(f"/challenges/{ch['id']}")
        self.assertEqual(hacker.ok(f"/challenges/{ch['id']}/click", {})["url"], "https://acme.test")
        a = sp.ok("/sponsor/analytics")
        self.assertEqual((a["totals"]["views"], a["totals"]["clicks"], a["totals"]["ctr"]), (2, 1, 50.0))
        self.assertEqual(len(a["daily_views"]), 14)
        self.assertEqual(sp.call("/teams", {"challenge_id": ch["id"], "name": "x"})[0], 403)

    def test_demo_notifies_everyone_else(self):
        owner, watcher = self.signup("demoer5"), self.signup("watcher5")
        ch = self.live_challenge(owner)
        team = owner.ok("/teams", {"challenge_id": ch["id"], "name": "Demoers"})["team"]
        self.assertEqual(owner.call(f"/teams/{team['id']}/demos", {"zoom_url": "https://evil.example/zoom.us"})[0], 400)
        self.assertEqual(watcher.call(f"/teams/{team['id']}/demos", {"zoom_url": "https://zoom.us/j/1"})[0], 403)
        demo = owner.ok(f"/teams/{team['id']}/demos", {"zoom_url": "https://us02web.zoom.us/j/99", "title": "Show"})["demo"]
        self.assertEqual(demo["status"], "live")
        self.assertGreater(watcher.ok("/me")["user"]["unread"], 0)
        self.assertTrue(any("Demoers" in n["text"] for n in watcher.ok("/notifications")["notifications"]))
        self.assertFalse(any("Demoers" in n["text"] for n in owner.ok("/notifications")["notifications"]))
        self.assertEqual(watcher.ok(f"/demos/{demo['id']}/watch", {})["zoom_url"], "https://us02web.zoom.us/j/99")
        listed = next(d for d in watcher.ok("/demos")["demos"] if d["id"] == demo["id"])
        self.assertTrue(listed["watching"])
        watcher.ok("/notifications/read", {})
        self.assertEqual(watcher.ok("/me")["user"]["unread"], 0)
        owner.ok(f"/demos/{demo['id']}/cancel", {})
        self.assertEqual(watcher.ok("/me")["user"]["unread"], 1)  # watchers hear about cancellations

    def test_judging(self):
        self.assertEqual(Client(self.base).call("/signup", {"handle": "fakejudge", "name": "F", "role": "judge", "judge_code": "nope"})[0], 403)
        judge = self.signup("judge6", role="judge", judge_code="judge-demo")
        hacker = self.client("ada")
        self.assertEqual(hacker.call("/judge/queue")[0], 403)
        queue = judge.ok("/judge/queue")["submissions"]
        self.assertTrue(queue and queue[0]["my_score"] is None)
        sid = queue[0]["id"]
        self.assertEqual(judge.call(f"/submissions/{sid}/score", {"innovation": 11, "technical": 5, "design": 5, "impact": 5})[0], 400)
        r = judge.ok(f"/submissions/{sid}/score", {"innovation": 10, "technical": 10, "design": 10, "impact": 10})
        self.assertGreaterEqual(r["judge_count"], 1)
        self.assertEqual(judge.call("/teams", {"challenge_id": 1, "name": "x"})[0], 403)

    def test_sponsor_support_perks(self):
        sp = self.client("vectorly")
        mine = sp.ok("/sponsor/analytics")["challenges"][0]["id"]
        other = next(c["id"] for c in sp.ok("/challenges")["challenges"] if c["sponsor"]["name"] != "Vectorly")
        self.assertEqual(sp.call("/perks", {"challenge_id": other, "kind": "credits", "title": "x"})[0], 403)
        self.assertEqual(sp.call("/perks", {"kind": "bribes", "title": "x"})[0], 400)
        pid = sp.ok("/perks", {"challenge_id": mine, "kind": "credits", "title": "$100 credits", "link": "https://v.test"})["perk_id"]
        hacker = self.signup("perky7")
        self.assertIn(pid, [p["id"] for p in hacker.ok(f"/challenges/{mine}")["perks"]])
        self.assertEqual(hacker.ok(f"/perks/{pid}/claim", {})["link"], "https://v.test")
        perk = next(p for p in sp.ok("/sponsor/analytics")["perks"] if p["id"] == pid)
        self.assertEqual(perk["claims"], 1)

    def test_floor_presence_help_and_karma(self):
        asker = self.signup("asker8", skills=["python"])
        helper = self.signup("helper8", skills=["Rust", "go"])
        bystander = self.signup("bystander8", skills=["figma"])
        self.assertEqual(Client(self.base).call("/floor/checkin", {"status": "x"})[0], 401)
        for c, status in [(helper, "Profiling the indexer"), (bystander, "Making slides")]:
            c.ok("/floor/checkin", {"status": status})
        floor = asker.ok("/floor")
        self.assertIn("Profiling the indexer", [h["status"] for h in floor["here"]])
        self.assertFalse(floor["me_here"])
        self.assertGreaterEqual(asker.ok("/stats")["here_now"], 2)

        self.assertEqual(asker.call("/posts", {"kind": "rant", "text": "x"})[0], 400)
        pid = asker.ok("/posts", {"kind": "help", "text": "Borrow checker is winning", "tags": ["rust"]})["post_id"]
        # Only on-floor people with a matching skill get tapped on the shoulder.
        self.assertTrue(any("Borrow checker" in n["text"] for n in helper.ok("/notifications")["notifications"]))
        self.assertFalse(any("Borrow checker" in n["text"] for n in bystander.ok("/notifications")["notifications"]))

        hid = helper.ok("/me")["user"]["id"]
        self.assertEqual(asker.call(f"/posts/{pid}/resolve", {"helper_id": hid})[0], 400)  # hasn't replied yet
        helper.ok(f"/posts/{pid}/reply", {"text": "Clone it, ship it, fix later"})
        self.assertEqual(helper.call(f"/posts/{pid}/resolve", {"helper_id": hid})[0], 403)
        self.assertEqual(asker.ok(f"/posts/{pid}/resolve", {"helper_id": hid})["helped"], 1)
        self.assertEqual(asker.call(f"/posts/{pid}/resolve", {"helper_id": hid})[0], 409)
        self.assertEqual(asker.ok("/people/helper8")["person"]["helped"], 1)

        self.assertEqual(bystander.ok(f"/posts/{pid}/highfive", {})["count"], 1)
        self.assertEqual(bystander.ok(f"/posts/{pid}/highfive", {})["count"], 0)
        post = next(p for p in asker.ok("/floor")["posts"] if p["id"] == pid)
        self.assertEqual((post["resolved_by"]["handle"], len(post["replies"])), ("helper8", 1))

        helper.ok("/floor/leave", {})
        self.assertNotIn(hid, [h["id"] for h in asker.ok("/floor")["here"]])

    def test_team_room(self):
        owner, mate, outsider = self.signup("roomowner9"), self.signup("roommate9"), self.signup("outsider9")
        ch = self.live_challenge(owner)
        tid = owner.ok("/teams", {"challenge_id": ch["id"], "name": "Roomies"})["team"]["id"]
        mid = mate.ok("/me")["user"]["id"]
        owner.ok(f"/requests/{owner.ok(f'/teams/{tid}/invite', {'user_id': mid})['request_id']}", {"action": "cancel"})
        rid = owner.ok(f"/teams/{tid}/invite", {"user_id": mid})["request_id"]
        mate.ok(f"/requests/{rid}", {"action": "accept"})

        self.assertEqual(outsider.call(f"/teams/{tid}/room")[0], 403)
        self.assertEqual(outsider.call(f"/teams/{tid}/room/heartbeat", {"session": "outsider-session-1"})[0], 403)

        # Preview + doing-now land in the private timeline, and teammates hear about new builds.
        self.assertEqual(owner.call(f"/teams/{tid}/preview", {"url": "ftp://nope"})[0], 400)
        owner.ok(f"/teams/{tid}/preview", {"url": "https://roomies.example"})
        mate.ok(f"/teams/{tid}/doing", {"doing": "Wiring the login page"})
        room = owner.ok(f"/teams/{tid}/room")
        self.assertEqual(room["preview"]["url"], "https://roomies.example")
        self.assertEqual({m["handle"]: m["doing"] for m in room["members"]}["roommate9"], "Wiring the login page")
        self.assertEqual([x["text"].split(":")[0] for x in room["log"]],
                         ["is now on", "pushed a new preview", "joined the team"])
        self.assertTrue(any("new build" in n["text"] for n in mate.ok("/notifications")["notifications"]))

        # Signaling: both join, the owner's offer reaches only the mate's session.
        self.assertEqual(owner.call(f"/teams/{tid}/room/heartbeat", {"session": "bad"})[0], 400)
        a, b = "session-aaaaaaaa", "session-bbbbbbbb"
        owner.ok(f"/teams/{tid}/room/heartbeat", {"session": a, "cam": True})
        self.assertEqual(owner.call(f"/teams/{tid}/room/signal", {"session": a, "to": b, "kind": "offer", "payload": {}})[0], 404)
        parts = mate.ok(f"/teams/{tid}/room/heartbeat", {"session": b})["participants"]
        self.assertEqual({p["session"]: p["cam"] for p in parts}, {a: True, b: False})
        self.assertEqual(mate.call(f"/teams/{tid}/room/signal", {"session": a, "to": b, "kind": "offer", "payload": {}})[0], 403)
        owner.ok(f"/teams/{tid}/room/signal", {"session": a, "to": b, "kind": "offer", "payload": {"sdp": "v=0"}})
        got = mate.ok(f"/teams/{tid}/room/heartbeat", {"session": b, "since": 0})["signals"]
        self.assertEqual([(s["from"], s["kind"], s["payload"]["sdp"]) for s in got], [(a, "offer", "v=0")])
        self.assertEqual(mate.ok(f"/teams/{tid}/room/heartbeat", {"session": b, "since": got[-1]["id"]})["signals"], [])
        self.assertEqual(owner.ok(f"/teams/{tid}/room/heartbeat", {"session": a})["signals"], [])
        self.assertEqual({m["handle"]: m["where"] for m in owner.ok(f"/teams/{tid}/room")["members"]}["roommate9"], "room")
        mate.ok(f"/teams/{tid}/room/leave", {"session": b})
        self.assertEqual([p["session"] for p in owner.ok(f"/teams/{tid}/room/heartbeat", {"session": a})["participants"]], [a])

    def test_transcript_and_live_captions(self):
        owner, mate, outsider = self.signup("talker11"), self.signup("listener11"), self.signup("snoop11")
        ch = self.live_challenge(owner)
        tid = owner.ok("/teams", {"challenge_id": ch["id"], "name": "Chatty"})["team"]["id"]
        rid = owner.ok(f"/teams/{tid}/invite", {"user_id": mate.ok("/me")["user"]["id"]})["request_id"]
        mate.ok(f"/requests/{rid}", {"action": "accept"})
        a, b = "talker-session-1", "listen-session-1"

        # Interim words ride the heartbeat as a live caption for teammates.
        owner.ok(f"/teams/{tid}/room/heartbeat", {"session": a, "talking": True, "caption": "so the plan is"})
        parts = mate.ok(f"/teams/{tid}/room/heartbeat", {"session": b})["participants"]
        self.assertEqual({p["session"]: p["caption"] for p in parts}[a], "so the plan is")

        self.assertEqual(outsider.call(f"/teams/{tid}/transcript", {"text": "hi"})[0], 403)
        self.assertEqual(owner.call(f"/teams/{tid}/transcript", {"text": "  "})[0], 400)
        first = owner.ok(f"/teams/{tid}/transcript", {"text": "So the plan is ship by Friday"})["line"]
        self.assertEqual((first["handle"], first["text"]), ("talker11", "So the plan is ship by Friday"))
        mate.ok(f"/teams/{tid}/transcript", {"text": "Sounds good"})

        # Full history on load; only newer lines on the heartbeat.
        self.assertEqual([x["text"] for x in mate.ok(f"/teams/{tid}/room")["transcript"]], ["So the plan is ship by Friday", "Sounds good"])
        newer = mate.ok(f"/teams/{tid}/room/heartbeat", {"session": b, "transcript_since": first["id"]})["transcript"]
        self.assertEqual([x["text"] for x in newer], ["Sounds good"])
        fresh = mate.ok(f"/teams/{tid}/room/heartbeat", {"session": b, "transcript_since": 0})["transcript"]
        self.assertEqual(len(fresh), 2)  # a newcomer with no lines yet still gets them
        self.assertEqual(outsider.call(f"/teams/{tid}/room")[0], 403)

        self.assertEqual(mate.ok(f"/teams/{tid}/transcript/clear", {})["cleared"], 2)
        room = owner.ok(f"/teams/{tid}/room")
        self.assertEqual(room["transcript"], [])
        self.assertIn("cleared the call transcript (2 lines)", [x["text"] for x in room["log"]])

    def test_demo_auto_approve(self):
        owner, joiner, latecomer = self.signup("autoowner10"), self.signup("autojoiner10"), self.signup("autolate10")
        ch = self.live_challenge(owner)
        tid = owner.ok("/teams", {"challenge_id": ch["id"], "name": "Autobots", "max_size": 2})["team"]["id"]
        self.srv.auto_approve = 0.2
        try:
            r = joiner.ok(f"/teams/{tid}/join", {"message": "hi"})
            self.assertEqual(r["auto_approve_in"], 0.2)
            # The latecomer's request comes in before the first approval fills the team (max 2).
            latecomer.ok(f"/teams/{tid}/join", {})
            deadline = time.time() + 5
            while time.time() < deadline and len(owner.ok(f"/teams/{tid}")["team"]["members"]) < 2:
                time.sleep(0.05)
            time.sleep(0.4)
        finally:
            self.srv.auto_approve = 0
        # Both timers fire together, so either may win — but never both (max_size 2).
        members = {m["handle"] for m in owner.ok(f"/teams/{tid}")["team"]["members"]} - {"autoowner10"}
        self.assertEqual(len(members), 1)
        winner, loser = (joiner, latecomer) if members == {"autojoiner10"} else (latecomer, joiner)
        self.assertTrue(any("You're in" in n["text"] for n in winner.ok("/notifications")["notifications"]))
        self.assertTrue(any("auto-approved" in n["text"] for n in owner.ok("/notifications")["notifications"]))
        self.assertIn("joined the team (auto-approved)", [x["text"] for x in winner.ok(f"/teams/{tid}/room")["log"]])
        # The one that didn't fit stays pending for the owner rather than vanishing.
        pending = [x["user"]["handle"] for x in owner.ok(f"/teams/{tid}")["requests"]]
        self.assertEqual(pending, [loser.ok("/me")["user"]["handle"]])

    # ---------- shared clock ----------

    def start_ritual(self, key, ago):
        self.srv.demo_ritual = {"key": key, "starts_at": now() - ago}
        return server.make_occ(key, self.srv.demo_ritual["starts_at"])

    def tearDown(self):
        self.srv.demo_ritual = None

    def test_schedule_math(self):
        from datetime import datetime, timezone
        mon = int(datetime(2026, 10, 12, tzinfo=timezone.utc).timestamp())  # a Monday
        week = server.occurrences(mon, mon + 7 * DAY)
        kick = [o for o in week if o["key"] == "kickoff"]
        close = [o for o in week if o["key"] == "closing"]
        self.assertEqual([o["starts_at"] - mon for o in kick], [17 * 3600])
        self.assertEqual([o["starts_at"] - mon for o in close], [6 * DAY + 18 * 3600])
        self.assertEqual(len([o for o in week if o["key"] == "checkin"]), 21)  # 3 regions x 7 nights
        self.assertEqual((server.region_of(-5), server.region_of(1), server.region_of(8)), ("americas", "emea", "apac"))
        o = close[0]
        self.assertEqual(server.closing_phase(o, o["starts_at"] + 10), ("intro", None))
        self.assertEqual(server.closing_phase(o, o["starts_at"] + server.CLOSING_INTRO + 2 * server.CLOSING_SLOT + 5), ("demos", 2))
        self.assertEqual(server.closing_phase(o, o["ends_at"] - 60)[0], "awards")
        self.assertEqual(server.max_slots(o), 15)  # 45 minutes of 3-minute slots

    def test_clock_and_calendar(self):
        c = self.client("ada")  # UTC+1 → Europe & Africa check-ins only
        clock = c.ok("/clock")
        self.assertAlmostEqual(clock["now"], time.time(), delta=5)
        self.assertEqual(clock["region"], "emea")
        self.assertFalse(any(o["region"] not in (None, "emea") for o in clock["week"]))
        self.assertTrue(clock["next"]["starts_at"] > now())
        self.assertEqual(clock["deadline"]["team_name"], "Agent Smiths")
        req = urllib.request.Request(self.base + "/api/clock.ics", headers={"Cookie": c.cookie})
        with urllib.request.urlopen(req) as res:
            ics = res.read().decode()
            self.assertIn("text/calendar", res.headers["Content-Type"])
        self.assertEqual(ics.count("BEGIN:VEVENT"), 3)
        self.assertIn("RRULE:FREQ=WEEKLY", ics)
        self.assertIn("RRULE:FREQ=DAILY", ics)
        o = self.start_ritual("checkin", 60)
        self.assertIn(o["id"], [x["id"] for x in c.ok("/clock")["live"]])

    def test_kickoff_idea_becomes_team(self):
        o = self.start_ritual("kickoff", 60)
        pitcher, fan, other = self.signup("pitcher12"), self.signup("fan12"), self.signup("other12")
        self.assertEqual(pitcher.call(f"/live/{o['id']}/checkin", {"text": "x"})[0], 400)
        iid = pitcher.ok(f"/live/{o['id']}/ideas", {"text": "Uber for rubber ducks"})["idea_id"]
        self.assertEqual(pitcher.call(f"/ideas/{iid}/fan", {})[0], 400)
        self.assertTrue(fan.ok(f"/ideas/{iid}/fan", {})["in"])
        self.assertTrue(other.ok(f"/ideas/{iid}/fan", {})["in"])
        self.assertFalse(other.ok(f"/ideas/{iid}/fan", {})["in"])  # toggles off
        state = fan.ok(f"/live/{o['id']}")
        idea = next(i for i in state["ideas"] if i["id"] == iid)
        self.assertEqual(([f["handle"] for f in idea["fans"]], idea["in"]), (["fan12"], True))
        self.assertGreaterEqual(state["here"], 1)
        self.assertEqual(fan.call(f"/ideas/{iid}/form-team", {"challenge_id": 1, "name": "Ducks"})[0], 403)
        ch = self.live_challenge(pitcher)
        r = pitcher.ok(f"/ideas/{iid}/form-team", {"challenge_id": ch["id"], "name": "Ducks"})
        self.assertEqual(r["invited"], 1)
        self.assertEqual(len(fan.ok("/inbox")["invites"]), 1)
        self.assertEqual(pitcher.call(f"/ideas/{iid}/form-team", {"challenge_id": ch["id"], "name": "Again"})[0], 409)
        self.srv.demo_ritual = None
        self.assertEqual(pitcher.call(f"/live/{o['id']}/ideas", {"text": "late"})[0], 404)

    def test_checkin_and_streak(self):
        o = self.start_ritual("checkin", 60)
        u = self.signup("streaky13")
        uid = u.ok("/me")["user"]["id"]
        db = connect(self.db)
        for d in (1, 2):
            db.execute("INSERT INTO posts(user_id,kind,text,tags,ritual,created_at) VALUES(?,?,?,?,?,?)",
                       (uid, "update", "earlier", "[]", f"checkin-emea-{now() - d * DAY}", now() - d * DAY))
        db.commit()
        db.close()
        self.assertEqual(u.ok(f"/live/{o['id']}/checkin", {"text": "Shipped the thing"})["streak"], 3)
        self.assertEqual(u.call(f"/live/{o['id']}/checkin", {"text": "again"})[0], 409)
        state = u.ok(f"/live/{o['id']}")
        self.assertTrue(state["checked_in"])
        self.assertEqual(state["streak"], 3)
        floor = u.ok("/floor")["posts"]
        self.assertTrue(any(p["text"] == "Shipped the thing" and p["ritual"] == o["id"] for p in floor))

    def test_closing_ceremony_runs_on_the_clock(self):
        o = self.start_ritual("closing", server.CLOSING_INTRO + 30)  # 30s into the first demo slot
        owner = self.signup("presenter14")
        fan = self.signup("crowd14")
        ch = self.live_challenge(owner)
        tid = owner.ok("/teams", {"challenge_id": ch["id"], "name": "Stagecraft"})["team"]["id"]
        self.assertEqual(owner.call(f"/live/{o['id']}/lineup", {"team_id": tid, "zoom_url": "https://zoom.us/j/1"})[0], 400)  # no submission
        owner.ok("/submissions", {"team_id": tid, "title": "Stagecraft", "repo_url": "https://github.com/x/y"})
        self.assertEqual(fan.call(f"/live/{o['id']}/lineup", {"team_id": tid, "zoom_url": "https://zoom.us/j/1"})[0], 403)
        self.assertEqual(owner.call(f"/live/{o['id']}/lineup", {"team_id": tid, "zoom_url": "https://evil.test/j/1"})[0], 400)
        # Slot 0 is already running, so a late signup gets the next slot that hasn't started.
        r = owner.ok(f"/live/{o['id']}/lineup", {"team_id": tid, "zoom_url": "https://us02web.zoom.us/j/42"})
        self.assertEqual(r["position"], 1)
        state = fan.ok(f"/live/{o['id']}")
        self.assertEqual((state["phase"], state["slot"], state["presenter"]), ("demos", 0, None))
        # Nobody presenting in slot 0, so applause goes to the room in general.
        self.assertEqual(fan.ok(f"/live/{o['id']}/react", {"emoji": "👏"})["slot"], -1)
        self.assertEqual(fan.call(f"/live/{o['id']}/react", {"emoji": "👏"})[0], 429)  # too fast
        self.assertEqual(fan.call(f"/live/{o['id']}/react", {"emoji": "💩"})[0], 400)
        # Jump the clock into slot 1: Stagecraft is on, reactions are theirs, then awards credit them.
        def shift_clock(new_start):
            # Moving a demo ceremony changes its id, so carry its lineup along (real ceremonies never move).
            old = server.make_occ("closing", self.srv.demo_ritual["starts_at"])["id"]
            self.srv.demo_ritual["starts_at"] = new_start
            occ = server.make_occ("closing", new_start)
            db = connect(self.db)
            db.execute("UPDATE lineup SET occ_id=? WHERE occ_id=?", (occ["id"], old))
            db.commit()
            db.close()
            return occ

        o = shift_clock(self.srv.demo_ritual["starts_at"] - server.CLOSING_SLOT)
        state = fan.ok(f"/live/{o['id']}")
        self.assertEqual(state["presenter"]["team_name"], "Stagecraft")
        time.sleep(0.25)
        self.assertEqual(fan.ok(f"/live/{o['id']}/react", {"emoji": "🔥"})["slot"], 1)
        o = shift_clock(now() - 3600 + 60)  # last minute: awards
        db = connect(self.db)
        db.execute("INSERT INTO reactions(occ_id,slot,emoji,n) VALUES(?,?,?,?)", (o["id"], 1, "🔥", 7))
        db.commit()
        db.close()
        state = fan.ok(f"/live/{o['id']}")
        self.assertEqual(state["phase"], "awards")
        self.assertIn(("Crowd favorite", "Stagecraft"), [(a["title"], a["team_name"]) for a in state["awards"]])
        self.assertEqual(owner.call(f"/live/{o['id']}/lineup", {"team_id": tid})[0], 400)  # lineup closed

    def test_ritual_notices_are_sent_once(self):
        db = connect(self.db)
        start = now() + 300
        demo = {"key": "closing", "starts_at": start}
        self.assertGreaterEqual(server.run_ritual_notices(db, demo, now()), 1)
        self.assertEqual(server.run_ritual_notices(db, demo, now()), 0)  # idempotent
        self.assertGreaterEqual(server.run_ritual_notices(db, demo, start + 5), 1)  # "is live"
        db.commit()
        db.close()
        texts = [n["text"] for n in self.client("ben").ok("/notifications")["notifications"]]
        self.assertTrue(any("starts in 5 min" in x for x in texts))
        self.assertTrue(any("is live" in x for x in texts))

    # ---------- finish → demo stage ----------

    def shipped_team(self, prefix):
        owner, mate = self.signup(f"{prefix}own"), self.signup(f"{prefix}mate")
        ch = self.live_challenge(owner)
        tid = owner.ok("/teams", {"challenge_id": ch["id"], "name": f"{prefix} team"})["team"]["id"]
        rid = owner.ok(f"/teams/{tid}/invite", {"user_id": mate.ok("/me")["user"]["id"]})["request_id"]
        mate.ok(f"/requests/{rid}", {"action": "accept"})
        return owner, mate, tid

    def test_finish_closes_roster_and_requires_submission(self):
        owner, mate, tid = self.shipped_team("fin15")
        hopeful = self.signup("hopeful15")
        hopeful.ok(f"/teams/{tid}/join", {"message": "me too"})
        self.assertEqual(hopeful.call(f"/teams/{tid}/finish", {})[0], 403)  # members only
        self.assertEqual(mate.call(f"/teams/{tid}/finish", {})[0], 400)  # no submission yet
        self.assertEqual(owner.call(f"/teams/{tid}/stage/start", {})[0], 400)  # can't go live before finishing
        # Any member can finish — not just the owner.
        r = mate.ok(f"/teams/{tid}/finish", {"title": "Shipit", "description": "Done", "repo_url": "https://github.com/x/y"})
        self.assertEqual(r["withdrawn"], 1)
        team = owner.ok(f"/teams/{tid}")["team"]
        self.assertEqual((team["status"], team["open"]), ("shipped", False))
        self.assertEqual(owner.ok(f"/teams/{tid}")["submission"]["title"], "Shipit")
        self.assertEqual(hopeful.call(f"/teams/{tid}/join", {})[0], 409)
        self.assertNotIn(tid, [t["id"] for t in hopeful.ok("/teams?open=1")["teams"]])
        self.assertNotIn(tid, [t["id"] for t in hopeful.ok("/match/teams")["teams"]])
        self.assertTrue(any("closed the roster" in n["text"] for n in hopeful.ok("/notifications")["notifications"]))
        self.assertTrue(any("demo stage is ready" in n["text"] for n in owner.ok("/notifications")["notifications"]))
        self.assertEqual(owner.call(f"/teams/{tid}/finish", {})[0], 409)
        self.assertEqual(hopeful.call(f"/teams/{tid}/reopen", {})[0], 403)
        mate.ok(f"/teams/{tid}/reopen", {})
        self.assertEqual(owner.ok(f"/teams/{tid}")["team"]["status"], "building")

    def test_demo_stage_live_lifecycle(self):
        owner, mate, tid = self.shipped_team("stg16")
        owner.ok(f"/teams/{tid}/finish", {"title": "Live thing", "demo_url": "https://example.com"})
        viewer, other = self.signup("viewer16"), self.signup("other16")
        p1, p2, v1, v2 = "presenter-one-1", "presenter-two-2", "viewer-session-1", "viewer-session-2"
        # Not live yet: viewers wait, presenters can set up.
        self.assertFalse(viewer.ok(f"/teams/{tid}/stage/heartbeat", {"session": v1})["live"])
        owner.ok(f"/teams/{tid}/stage/heartbeat", {"session": p1, "screen": True, "mic": True})
        self.assertEqual(viewer.call(f"/teams/{tid}/stage/react", {"emoji": "🔥"})[0], 400)
        self.assertEqual(viewer.call(f"/teams/{tid}/stage/start", {})[0], 403)
        owner.ok(f"/teams/{tid}/stage/start", {})
        self.assertEqual(owner.call(f"/teams/{tid}/stage/start", {})[0], 409)
        self.assertTrue(any("demoing live now" in n["text"] for n in viewer.ok("/notifications")["notifications"]))
        self.assertFalse(any("demoing live now" in n["text"] for n in mate.ok("/notifications")["notifications"]))
        live = [d for d in viewer.ok("/demos")["demos"] if d["team_id"] == tid]
        self.assertEqual((live[0]["status"], live[0]["stage"]), ("live", 1))

        hb = viewer.ok(f"/teams/{tid}/stage/heartbeat", {"session": v1})
        self.assertTrue(hb["live"])
        self.assertEqual([(p["session"], p["screen"]) for p in hb["participants"]], [(p1, True)])  # viewers only see presenters
        other.ok(f"/teams/{tid}/stage/heartbeat", {"session": v2})
        mate.ok(f"/teams/{tid}/stage/heartbeat", {"session": p2})
        seen = owner.ok(f"/teams/{tid}/stage/heartbeat", {"session": p1, "screen": True})
        self.assertEqual({p["session"] for p in seen["participants"]}, {p1, p2, v1, v2})  # presenters see everyone
        self.assertEqual(seen["viewers"], 2)
        # Signaling: presenter↔viewer and presenter↔presenter, never viewer↔viewer.
        owner.ok(f"/teams/{tid}/stage/signal", {"session": p1, "to": v1, "kind": "offer", "payload": {"sdp": "x"}})
        owner.ok(f"/teams/{tid}/stage/signal", {"session": p1, "to": p2, "kind": "offer", "payload": {"sdp": "y"}})
        self.assertEqual(viewer.call(f"/teams/{tid}/stage/signal", {"session": v1, "to": v2, "kind": "offer", "payload": {}})[0], 403)
        self.assertEqual(viewer.call(f"/teams/{tid}/stage/signal", {"session": p1, "to": v2, "kind": "offer", "payload": {}})[0], 403)
        got = viewer.ok(f"/teams/{tid}/stage/heartbeat", {"session": v1})["signals"]
        self.assertEqual([(g["from"], g["payload"]["sdp"]) for g in got], [(p1, "x")])

        viewer.ok(f"/teams/{tid}/stage/react", {"emoji": "🔥"})
        qid = viewer.ok(f"/teams/{tid}/stage/questions", {"text": "Does it scale?"})["question_id"]
        self.assertEqual(viewer.call(f"/teams/{tid}/stage/questions/{qid}/answered", {})[0], 403)
        self.assertTrue(mate.ok(f"/teams/{tid}/stage/questions/{qid}/answered", {})["answered"])
        st = viewer.ok(f"/teams/{tid}/stage")
        self.assertEqual((st["live"], st["presenter"], st["reactions"], st["questions"][0]["answered"]), (True, False, {"🔥": 1}, True))
        self.assertTrue(owner.ok(f"/teams/{tid}/stage")["presenter"])
        self.assertEqual(owner.call(f"/teams/{tid}/reopen", {})[0], 409)  # end the demo first

        summary = mate.ok(f"/teams/{tid}/stage/end", {})
        self.assertEqual((summary["peak"], summary["reactions"], summary["questions"]), (2, 1, 1))
        st = viewer.ok(f"/teams/{tid}/stage")
        self.assertEqual((st["live"], st["demo"]["status"]), (False, "past"))
        self.assertFalse(viewer.ok(f"/teams/{tid}/stage/heartbeat", {"session": v1})["live"])
        self.assertIn("ended the demo", owner.ok(f"/teams/{tid}/room")["log"][0]["text"])

    def test_demo_stage_viewer_cap(self):
        owner, mate, tid = self.shipped_team("cap17")
        owner.ok(f"/teams/{tid}/finish", {"title": "Packed", "repo_url": "https://github.com/x/y"})
        owner.ok(f"/teams/{tid}/stage/start", {})
        cap = server.STAGE_MAX_VIEWERS
        server.STAGE_MAX_VIEWERS = 1
        try:
            a, b = self.signup("capa17"), self.signup("capb17")
            self.assertFalse(a.ok(f"/teams/{tid}/stage/heartbeat", {"session": "cap-viewer-a"}).get("full"))
            self.assertTrue(b.ok(f"/teams/{tid}/stage/heartbeat", {"session": "cap-viewer-b"})["full"])
            self.assertFalse(a.ok(f"/teams/{tid}/stage/heartbeat", {"session": "cap-viewer-a"}).get("full"))  # already in
        finally:
            server.STAGE_MAX_VIEWERS = cap

    # ---------- build lab ----------

    def wait_run(self, client, tid, rid):
        deadline = time.time() + 5
        while time.time() < deadline:
            run = next(x for x in client.ok(f"/teams/{tid}/build")["runs"] if x["id"] == rid)
            if run["status"] != "running":
                return run
            time.sleep(0.05)
        self.fail("agent run never finished")

    def test_build_lab_simulated_agent(self):
        owner, mate, tid = self.shipped_team("lab18")
        outsider = self.signup("labout18")
        self.srv.agent_mode, self.srv.agent_delay = "simulated", 0
        try:
            self.assertEqual(outsider.call(f"/teams/{tid}/build")[0], 403)
            b = owner.ok(f"/teams/{tid}/build")
            self.assertEqual(set(b["files"]), {"index.html", "styles.css", "app.js"})
            self.assertIn("lab18 team", b["files"]["index.html"])  # starter uses the team's name
            self.assertEqual((b["agent"]["mode"], b["versions"][0]["note"]), ("simulated", "Starter files"))

            rid = mate.ok(f"/teams/{tid}/agent", {"prompt": "Add a progress dashboard"})["run"]["id"]
            run = self.wait_run(owner, tid, rid)
            self.assertEqual(run["status"], "ready")
            self.assertIn("Simulated agent", run["summary"])
            self.assertIn("tasks", run["files"]["app.js"])
            # Nothing changes until a teammate applies it.
            self.assertEqual(owner.ok(f"/teams/{tid}/build")["files"], b["files"])
            v = owner.ok(f"/teams/{tid}/agent/{rid}/apply", {})["version"]
            after = mate.ok(f"/teams/{tid}/build")
            self.assertEqual((after["version"], after["files"]["app.js"]), (v, run["files"]["app.js"]))
            self.assertEqual(owner.call(f"/teams/{tid}/agent/{rid}/apply", {})[0], 409)  # already handled

            # A proposal made against old files can't silently overwrite newer hand edits.
            rid2 = owner.ok(f"/teams/{tid}/agent", {"prompt": "Improve keyboard accessibility"})["run"]["id"]
            self.wait_run(owner, tid, rid2)
            mate.ok(f"/teams/{tid}/build/files", {"files": {"app.js": "console.log('hand edit')"}, "note": "tweak"})
            self.assertEqual(owner.call(f"/teams/{tid}/agent/{rid2}/apply", {})[0], 409)
            owner.ok(f"/teams/{tid}/agent/{rid2}/apply", {"force": True})
            files = owner.ok(f"/teams/{tid}/build")["files"]
            self.assertIn("Skip to content", files["index.html"])
            self.assertEqual(files["app.js"], "console.log('hand edit')")  # untouched files keep the hand edit

            self.assertEqual(mate.call(f"/teams/{tid}/build/files", {"files": {"evil.php": "x"}})[0], 400)
            self.assertEqual(mate.call(f"/teams/{tid}/build/files", {"files": {"app.js": "x" * 70000}})[0], 400)
            restored = owner.ok(f"/teams/{tid}/build/restore", {"version_id": b["version"]})["version"]
            self.assertEqual(owner.ok(f"/teams/{tid}/build")["files"], b["files"])
            self.assertGreater(restored, v)
            rid3 = owner.ok(f"/teams/{tid}/agent", {"prompt": "landing page"})["run"]["id"]
            self.wait_run(owner, tid, rid3)
            mate.ok(f"/teams/{tid}/agent/{rid3}/discard", {})
            self.assertEqual(owner.ok(f"/teams/{tid}/build")["files"], b["files"])
            self.assertIn("asked the build agent", " ".join(x["text"] for x in owner.ok(f"/teams/{tid}/room")["log"]))
        finally:
            self.srv.agent_mode, self.srv.agent_delay = None, 1.5

    def test_build_lab_claude_path(self):
        owner, mate, tid = self.shipped_team("cl19")
        seen = {}
        real = server.call_claude

        def fake(prompt, files, context, history):
            seen.update(prompt=prompt, context=context, files=files)
            return "Made the button bigger.", {"styles.css": "button { font-size: 20px; }"}

        self.srv.agent_mode = "claude"
        server.call_claude = fake
        try:
            self.assertEqual(owner.ok(f"/teams/{tid}/build")["agent"]["model"], "claude-opus-5-5")
            rid = owner.ok(f"/teams/{tid}/agent", {"prompt": "Bigger button"})["run"]["id"]
            run = self.wait_run(owner, tid, rid)
            self.assertEqual((run["status"], run["mode"], run["summary"]), ("ready", "claude", "Made the button bigger."))
            self.assertEqual(seen["context"]["team"], "cl19 team")
            self.assertEqual(set(seen["files"]), {"index.html", "styles.css", "app.js"})
            self.assertEqual(owner.call(f"/teams/{tid}/agent", {"prompt": "again"})[0], 201)

            def boom(*a):
                raise server.AgentError("Claude declined this task. Try rephrasing what you'd like built.")
            server.call_claude = boom
            time.sleep(0.1)
            rid2 = None
            for _ in range(50):  # wait for the previous run to finish before starting another
                st, data = owner.call(f"/teams/{tid}/agent", {"prompt": "something"})
                if st == 201:
                    rid2 = data["run"]["id"]
                    break
                time.sleep(0.05)
            failed = self.wait_run(owner, tid, rid2)
            self.assertEqual((failed["status"], failed["files"]), ("failed", None))
            self.assertIn("declined", failed["error"])
        finally:
            server.call_claude = real
            self.srv.agent_mode = None

    def test_call_claude_request_and_reply_handling(self):
        """Exercise call_claude against a stand-in SDK: the request shape and every reply branch."""
        import sys
        import types
        sent = {}

        class Block:
            def __init__(self, text):
                self.type, self.text = "text", text

        reply = {}

        class Stream:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get_final_message(self):
                return types.SimpleNamespace(stop_reason=reply["stop"], content=[Block(reply["text"])])

        class Messages:
            def stream(self, **kw):
                sent.update(kw)
                return Stream()

        fake = types.ModuleType("anthropic")
        for name in ("AuthenticationError", "RateLimitError", "APIStatusError", "APIConnectionError"):
            setattr(fake, name, type(name, (Exception,), {}))
        fake.Anthropic = lambda: types.SimpleNamespace(beta=types.SimpleNamespace(messages=Messages()))
        sys.modules["anthropic"] = fake
        try:
            files = server.starter_files("Demo", "An idea")
            reply.update(stop="end_turn", text=json.dumps({"summary": "Done.", "files": [{"path": "app.js", "content": "x()"}]}))
            summary, changed = server.call_claude("Make it pop", files, {"team": "Demo"}, [])
            self.assertEqual((summary, changed), ("Done.", {"app.js": "x()"}))
            self.assertEqual(sent["model"], "claude-opus-5-5")
            self.assertEqual((sent["fallbacks"], sent["betas"]), ("default", ["server-side-fallback-2026-07-01"]))
            self.assertEqual(sent["output_config"]["format"]["schema"], server.AGENT_SCHEMA)
            self.assertIn("<task>\nMake it pop\n</task>", sent["messages"][0]["content"])
            self.assertIn('<file path="index.html">', sent["messages"][0]["content"])
            for stop, text, msg in [("refusal", "", "declined"), ("max_tokens", "{", "too large"), ("end_turn", "not json", "couldn't be read"),
                                    ("end_turn", json.dumps({"summary": "x", "files": [{"path": "../etc/passwd", "content": "x"}]}), "couldn't be read")]:
                reply.update(stop=stop, text=text)
                with self.assertRaises(server.AgentError) as cm:
                    server.call_claude("t", files, {}, [])
                self.assertIn(msg, str(cm.exception))
        finally:
            del sys.modules["anthropic"]

    # ---------- builders directory ----------

    def test_builders_directory_data(self):
        people = self.client().ok("/people")["people"]
        maya = next(p for p in people if p["name"] == "Maya Chen")
        self.assertEqual((maya["city"], maya["country"], maya["title"], maya["experience"], maya["hours"], maya["collab"]),
                         ("San Francisco", "United States", "Full-stack engineer", "Senior", 15, "Remote"))
        self.assertEqual(maya["skills"], ["React", "TypeScript", "Next.js"])
        self.assertEqual(sum(p["name"] == "Lena Fischer" for p in people), 1)  # no duplicate persona
        self.assertGreaterEqual(len(people), 50)
        self.assertFalse(seed.seed_builders(self.db))  # idempotent
        challenges = self.client().ok("/challenges")["challenges"]
        berlin = next(c for c in challenges if c["title"] == "Berlin Build Weekend")
        self.assertEqual((berlin["format"], berlin["location"], berlin["status"]), ("In person", "Berlin", "upcoming"))
        self.assertIn("Code for a cooler planet", [c["title"] for c in challenges])
        projects = self.client().ok("/projects")["projects"]
        compass = next(p for p in projects if p["title"] == "Carbon Compass")
        self.assertEqual((compass["stack"], compass["team_name"]), (["React", "TypeScript"], "Carbon Collective"))
        teams = self.client().ok("/teams")["teams"]
        self.assertIn("ai for good", next(t for t in teams if t["name"] == "Carbon Collective")["challenge_tags"])

    def test_save_connect_and_profile_fields(self):
        me = self.signup("saver20", title="Product designer", city="Lisbon", country="Portugal", experience="Senior",
                         hours=15, collab="Hybrid", seeking="Co-founders")
        prof = me.ok("/me")["user"]
        self.assertEqual((prof["title"], prof["city"], prof["collab"], prof["hours"]), ("Product designer", "Lisbon", "Hybrid", 15))
        self.assertEqual(me.call("/me", {"name": "S", "experience": "Wizard"})[0], 400)
        me.ok("/me", {"name": "Saver", "hours": 30, "city": "Porto"})
        prof = me.ok("/me")["user"]
        self.assertEqual((prof["hours"], prof["city"], prof["title"]), (30, "Porto", "Product designer"))  # others kept
        other = self.signup("savee20")
        oid = other.ok("/me")["user"]["id"]
        self.assertTrue(me.ok(f"/people/{oid}/save", {})["saved"])
        self.assertEqual(me.ok("/saved")["saved"], [oid])
        self.assertFalse(me.ok(f"/people/{oid}/save", {})["saved"])
        self.assertEqual(me.call(f"/people/{prof['id']}/save", {})[0], 400)
        r = me.ok(f"/people/{oid}/connect", {})
        self.assertEqual((r["connected"], r["mutual"]), (True, False))
        self.assertTrue(any("wants to connect" in n["text"] for n in other.ok("/notifications")["notifications"]))
        self.assertTrue(other.ok(f"/people/{prof['id']}/connect", {})["mutual"])
        self.assertEqual(me.ok("/saved")["connected"], [oid])
        self.assertTrue(me.ok(f"/people/{oid}/connect", {})["already"])

    def test_onboarding_checklist(self):
        owner, mate, tid = self.shipped_team("onb21")
        self.assertEqual(owner.ok(f"/teams/{tid}/room")["onboarding"], [])
        owner.ok(f"/teams/{tid}/onboarding", {"step": "brief", "done": True})
        self.assertEqual(owner.call(f"/teams/{tid}/onboarding", {"step": "nope", "done": True})[0], 400)
        self.assertEqual(self.signup("onbout21").call(f"/teams/{tid}/onboarding", {"step": "brief", "done": True})[0], 403)
        owner.ok(f"/teams/{tid}/doing", {"doing": "Writing tests"})
        room = owner.ok(f"/teams/{tid}/room")
        self.assertEqual(room["onboarding"], ["brief", "status"])  # status ticks itself once you've posted one
        self.assertEqual(mate.ok(f"/teams/{tid}/room")["onboarding"], [])  # per person
        self.assertEqual(room["build"]["note"], "Starter files")
        owner.ok(f"/teams/{tid}/onboarding", {"step": "brief", "done": False})
        self.assertEqual(owner.ok(f"/teams/{tid}/room")["onboarding"], ["status"])

    # ---------- hackathon pages ----------

    def test_real_luma_event_and_sponsors(self):
        hacks = self.client().ok("/challenges")["challenges"]
        ai = next(h for h in hacks if h["title"] == "AI Engineer New York Hackathon")
        self.assertEqual((ai["format"], ai["location"], ai["luma_url"], ai["luma_status"], ai["is_real"]),
                         ("In person", "New York", "https://luma.com/AIEngineerNYHackathon", "Waitlist", True))
        self.assertEqual(ai["food"], [])  # no invented logistics for a real event
        detail = self.client().ok(f"/challenges/{ai['id']}")
        self.assertEqual(detail["sponsors"], [])  # flyer sponsors are not attached to the real event
        berlin = next(h for h in hacks if h["title"] == "Berlin Build Weekend")
        d = self.client().ok(f"/challenges/{berlin['id']}")
        offers = [x["offer"] for x in d["sponsors"]]
        self.assertIn("Best Use of Gemma 4", offers)
        self.assertEqual([x["offer"] for x in d["sponsors"] if x["name"] == "Major League Hacking"],
                         ["Global Hack Week", "Host a Hack Day for your community"])
        self.assertTrue(d["challenge"]["food"] and "Doors open" in d["challenge"]["info"])
        self.assertGreaterEqual(len(d["people"]), 5)
        self.assertFalse(seed.seed_hackathons(self.db))  # idempotent

    def test_attend_people_and_scoped_floor(self):
        u = self.signup("attendee22", skills=["go"])
        ch = self.live_challenge(u)
        other = next(c for c in u.ok("/challenges?status=live")["challenges"] if c["id"] != ch["id"])
        self.assertTrue(u.ok(f"/challenges/{ch['id']}/attend", {})["attending"])
        d = u.ok(f"/challenges/{ch['id']}")
        self.assertTrue(d["attending"])
        me = next(p for p in d["people"] if p["handle"] == "attendee22")
        self.assertIsNone(me["team"])
        u.ok("/teams", {"challenge_id": ch["id"], "name": "Gophers"})
        me = next(p for p in u.ok(f"/challenges/{ch['id']}")["people"] if p["handle"] == "attendee22")
        self.assertEqual(me["team"]["name"], "Gophers")
        self.assertFalse(u.ok(f"/challenges/{ch['id']}/attend", {})["attending"])
        # The Floor, scoped: check in and post on one hackathon; the other doesn't show it.
        u.ok("/floor/checkin", {"status": "Wiring gRPC", "challenge_id": ch["id"]})
        u.ok("/posts", {"kind": "update", "text": "Gophers shipped login", "challenge_id": ch["id"]})
        here = u.ok(f"/floor?challenge_id={ch['id']}")
        self.assertIn("Wiring gRPC", [h["status"] for h in here["here"]])
        self.assertIn("Gophers shipped login", [p["text"] for p in here["posts"]])
        elsewhere = u.ok(f"/floor?challenge_id={other['id']}")
        self.assertNotIn("attendee22", [h["handle"] for h in elsewhere["here"]])
        self.assertNotIn("Gophers shipped login", [p["text"] for p in elsewhere["posts"]])
        self.assertIn("Gophers shipped login", [p["text"] for p in u.ok("/floor")["posts"]])  # unscoped = everything

    def test_linkedin_and_luma_validation(self):
        u = self.signup("linked23")
        self.assertEqual(u.call("/me", {"name": "L", "linkedin": "https://evil.example/in/x"})[0], 400)
        self.assertEqual(u.call("/me", {"name": "L", "linkedin": "javascript:alert(1)"})[0], 400)
        u.ok("/me", {"name": "L", "linkedin": "https://www.linkedin.com/in/linked-23"})
        self.assertEqual(u.ok("/me")["user"]["linkedin"], "https://www.linkedin.com/in/linked-23")
        sp = self.signup("lumasp23", role="sponsor", org="Luma Co")
        t = now()
        self.assertEqual(sp.call("/challenges", {"title": "x", "format": "In person", "luma_url": "https://evil.test/e", "starts_at": t, "ends_at": t + DAY})[0], 400)
        ch = sp.ok("/challenges", {"title": "Meetup Hack", "format": "In person", "location": "Lisbon",
                                   "luma_url": "https://lu.ma/meetup-hack", "starts_at": t, "ends_at": t + DAY})["challenge"]
        self.assertEqual((ch["format"], ch["location"], ch["luma_url"]), ("In person", "Lisbon", "https://lu.ma/meetup-hack"))

    def test_finished_hackathon_lists_demos(self):
        past = self.client().ok("/challenges?status=past")["challenges"]
        with_demo = [h for h in past if self.client().ok(f"/challenges/{h['id']}")["demos"]]
        self.assertTrue(with_demo)
        d = self.client().ok(f"/challenges/{with_demo[0]['id']}")
        self.assertEqual(d["demos"][0]["status"], "past")
        self.assertTrue(d["submissions"])

    def test_cannot_join_past_challenge(self):
        c = self.signup("late4")
        past = c.ok("/challenges?status=past")["challenges"][0]
        self.assertEqual(c.call("/teams", {"challenge_id": past["id"], "name": "Late"})[0], 400)

    def test_open_sprint_is_idempotent(self):
        db = connect(self.db)
        n = db.execute("SELECT COUNT(*) FROM challenges WHERE sponsor_id IS NULL").fetchone()[0]
        db.close()
        self.client().ok("/challenges")
        db = connect(self.db)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM challenges WHERE sponsor_id IS NULL").fetchone()[0], n)
        db.close()


if __name__ == "__main__":
    unittest.main()
