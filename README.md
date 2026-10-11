# Always-On Hackathon

**There's always a hackathon happening.** Rolling sponsor challenges plus a house *Open Sprint* that restarts every Monday. Hackers find teammates in minutes, ship within the time limit, demo live on Zoom, and get scored by judges. Sponsors get their product in front of builders every week, with a funnel they can measure.

## Run it

```bash
python3 server.py            # http://127.0.0.1:8000 (demo data is loaded on first run)
python3 -m unittest -v       # API tests
```

No dependencies: Python 3.8+ standard library, SQLite and a plain-JS single-page frontend. To reset the demo data, delete `data/` and restart.

**Demo mode is on by default:** a request to join a team approves itself after **2 seconds**, as if the owner had clicked Accept, and drops you into the Team Room. The usual checks still apply: if the team filled up in the meantime, the request waits for the owner. Turn it off for real use:

```bash
python3 server.py --auto-approve 0     # or AOH_AUTO_APPROVE=0
```

Demo accounts (sign-in is by handle only in this MVP): `ben` (has an invite), `lena` (looking for a team), `ada` (owns a team), `judy` (judge), `nimbus` (sponsor). The judge sign-up code is `judge-demo` (set `AOH_JUDGE_CODE` to change it).

## What it does

| # | Requirement | How it works |
|---|---|---|
| 1 | Hackers sign up / sign in | `#/join`: profile with skills, interests and timezone. These drive matching. |
| 2 | Start a team or join one | Start a team on any challenge with the roles you need. Others **request to join**, or owners **invite** people from ranked suggestions. Requests and invites go to the Inbox. |
| 3 | Team size limit | Each challenge sets `max_team` (default **4**); a team can choose a lower cap. Full teams can't accept anyone else. One team per hacker per challenge. |
| 4 | Time limit | Every challenge has a start and end time with a live countdown. Submissions are accepted **only while it's live**. |
| 5 | Zoom demos with notifications | Team members schedule a demo with a Zoom link (now, +15m, +1h or a set time). **Everyone else gets a notification** (bell icon plus a toast while the page is open). Watchers click "I'll watch" or "Join on Zoom"; watcher counts are shown, and watchers are told if a demo is cancelled. |
| 6 | Judges | Judge accounts (sign up with the organizer code) get a scoring queue: innovation, technical depth, design and impact, each 1–10, plus written feedback. Averages appear on the project, and teams are notified. |
| 7 | Sponsors | Sponsors launch challenges (prize, tags, dates, team size) and **offer support**: credits, mentorship, office hours, API access or swag, which hackers claim. The dashboard shows views → product clicks → CTR → teams → hackers → projects, support claims, 14-day views and the top skills of their builders. |

**The Floor** (`#/floor`) is the in-person room, online. You check in with what you're working on and appear under *Here now* while active. The site sends a heartbeat in the background, and you drop off about 2 minutes after closing the tab. The ship log holds progress updates with 🙌 high-fives. **Raise your hand** posts a help request tagged with skills. It notifies people on the floor who have those skills, plus sponsors whose live challenge matches the tags, so sponsor engineers answer questions about their own API in public. When the asker marks it solved, the helper gets +1 **helper karma**, shown on their profile.

**Team Room** (`#/t/<id>/room`) is the team's private space, for members only:
- **Product browser:** an address bar plus an embedded view of the team's current preview link. When a teammate loads a new URL, everyone's view reloads and they're notified. Sites that block embedding fall back to "open in new tab".
- **What everyone's doing:** each member's "doing now" status and where they are (in the room, on the Floor, away), plus a private team timeline.
- **Call:** camera is opt-in and off by default. **Hold to talk** (button or Space bar) un-mutes your mic only while held, and talkers are highlighted. Audio and video go directly between teammates' browsers (WebRTC); the server only passes the connection setup between them (`/room/heartbeat`, `/room/signal`), and nothing is recorded. Camera and mic need HTTPS, or `localhost`.
- **Transcript:** while you hold to talk, your browser's built-in speech recognition turns your words into text. Teammates see live captions on your tile, and finished phrases are saved to the team transcript (Download .txt / Clear). It's per person (📝 *Transcribe me*, default on, remembered), and words still unfinished when you let go are kept. Chrome sends the audio to Google's servers to convert it; Firefox has no speech recognition, so the switch shows as unavailable there.

**The shared clock** (`#/live`). Always-on shouldn't mean always empty, so three rituals a week put everyone in the same moment. The schedule is fixed in code (`RITUALS` in `server.py`), so there's nothing to administer:

| Ritual | When (UTC) | What happens |
|---|---|---|
| 🚀 Monday Kickoff | Mon 17:00, 45 min | Challenges on screen. Pitch one-line ideas; others tap *I'm in*. **Form team** creates the team and invites everyone who's in. |
| 🔔 Nightly check-in | Daily, 30 min: Asia-Pacific 12:00, Europe & Africa 19:00, Americas 01:00 | Everyone in your region (from your timezone) posts what they shipped. Builds a 🔥 streak, and posts also appear on the Floor. |
| 🏆 Sunday Closing Ceremony | Sun 18:00, 60 min | Runs on the clock with no host: a 5-minute intro, then **3-minute slots** in lineup order (each team on its own Zoom), then awards. Reactions during a slot count toward *Crowd favorite*; the other awards are *Judges' pick* and *Community vote*. |

A **clock bar** on every page shows what's live or next and your team's deadline. Countdowns use **server time** (the browser measures its offset from the server), so everyone sees the same seconds. Reminders go out 10 minutes before and at the start (check-ins only at the start), and `/api/clock.ics` adds the whole schedule to a calendar. To demo a ritual without waiting for it:

```bash
python3 server.py --live-ritual closing   # or kickoff, checkin
```

**Always-on:** `ensure_open_sprint()` guarantees a house challenge for every ISO week, so the site is never empty between sponsor challenges.

**Matching** (`fit()` in `server.py`) scores 0–100: open roles filled (50%), new skills brought (20%), interest overlap with the challenge tags (15%) and timezone overlap (15%). Each score comes with readable reasons such as "Fills open role: react".

## Layout

```
server.py        HTTP server, SQLite schema, every API route
seed.py          fictional demo data (dates relative to now)
static/          index.html, app.js (hash-routed SPA), styles.css (light + dark)
test_server.py   end-to-end API tests
```

## Before running this for real

- **Demo mode:** start with `--auto-approve 0` so team owners decide who joins.
- **Auth:** replace handle-only sign-in with OAuth (MyMLH or GitHub). Sessions are already HttpOnly cookies, and POSTs require JSON, which blocks cross-site form posts.
- **Zoom:** links are pasted by teams and checked to be on `zoom.us`/`zoom.com`. A Zoom OAuth app could create meetings automatically.
- **Notifications:** in-app only, by polling. Add email or push, and fan out through a queue instead of inline inserts once the user count grows.
- **Judges:** assign judges per challenge, and decide winners when a challenge closes.
- **Calls:** add a TURN server. Without one, some teammates on strict corporate or carrier networks can't connect directly. The many-to-many design suits teams of 4 or fewer; larger groups would need a media server such as LiveKit.
- **Transcripts:** for consistent quality across browsers, record clips on talk and transcribe them on the server (e.g. Whisper). Also add a retention policy, since transcripts are kept until a member clears them.
- **Database:** SQLite is fine for a pilot; move to Postgres when you outgrow it.
