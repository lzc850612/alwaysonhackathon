# Always-On Hackathon

**There's always a hackathon happening.** Rolling sponsor challenges plus a house *Open Sprint* that restarts every Monday. Hackers find teammates in minutes, ship within the time limit, demo live on Zoom, and get scored by judges. Sponsors get their product in front of builders every week, with a funnel they can measure.

## Run it

```bash
python3 server.py            # http://127.0.0.1:8000 (demo data is loaded on first run)
python3 -m unittest -v       # API tests
```

No dependencies locally: Python 3.9+ standard library, SQLite and a plain-JS single-page frontend. The optional `anthropic` SDK turns on the real Build lab agent. The UI uses a light theme: a pale canvas, blue→violet gradients, soft white cards and a neural-ribbon hero. To reset the demo data, delete `data/` and restart.

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

**Hackathons** (`#/challenges`): the list has search, an **Online / In person** filter, a theme filter and Live / Upcoming / Past / All tabs. In-person events can link to their **Luma** page ("RSVP on Luma" / "Join waitlist on Luma"); sponsors set the link when creating a hackathon (only `luma.com` / `lu.ma` links are accepted). The list includes the real **AI Engineer New York Hackathon** (Oct 11, 2026, 9 AM–9 PM EDT, hosted by AI Engineer & Major League Hacking, on the waitlist when checked). Its page shows only facts from the organizer's Luma listing and points there for venue, food and schedule.

Each **hackathon page** (`#/c/<id>`) has tabs:
- **Overview:** about, information & instructions, opening video (YouTube, Vimeo or MP4 when set), sponsors & partners, food & beverage, rules.
- **The Floor:** presence, ship log and help requests, scoped to this hackathon, with **Walk onto the floor** in the header.
- **Teams.**
- **People:** everyone who joined or is on a team. Clicking a person opens their profile, including LinkedIn if they've added it; LinkedIn links are never invented for demo people.
- **Demos & projects:** after a hackathon ends, this tab opens first with its recorded demos and projects.

The fictional hackathons list partner offers from MLH sponsor flyers: Major League Hacking (Global Hack Week, Host a Hack Day), Snowflake, Google's Gemma 4 challenge, DigitalOcean's Hackerfest and DEV. None of these are attached to the real event.

**Build lab** (the **✦ Build lab** tab in the Team Room) is the team's shared prototype plus a coding agent.
- **Shared project:** three files (`index.html`, `styles.css`, `app.js`), saved as versions everyone on the team sees. Edit them by hand in **Code**, or **restore** any earlier version (the restore is saved as a new version, so nothing is lost).
- **Agent tasks:** you describe a change. The agent reads the team's context (name, idea, challenge, submission, recent tasks) and the current files, then *proposes* complete file changes.
- **Review:** **Changes** shows a line diff, and nothing lands until a teammate clicks **Apply** (or **Discard**). If the files changed after the task started, applying asks first.
- **Preview:** **Preview** runs the real files inside a sandboxed iframe (`sandbox="allow-scripts"` without `allow-same-origin`), so prototype code can't reach this app, its cookies or its API.
- **Two agent modes:**
  - **Claude**: used when the `anthropic` Python SDK is installed and credentials are set. It calls `claude-opus-5-5` through the official SDK, with streaming, a strict JSON output schema (`{summary, files[]}`), prompt caching and server-side refusal fallbacks (`fallbacks: "default"`), and refusal and length handling. The key stays on the server.
  - **Simulated**: used otherwise. It applies built-in templates (landing page / progress dashboard / accessibility pass) to the team's real context, and every reply says it's simulated.
- **Limits:** one running task per team, 20 tasks per person per hour.

To run the real agent (the SDK needs Python 3.10+):

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...   # or ANTHROPIC_AUTH_TOKEN / an `ant auth login` profile
python3 server.py                     # AOH_AGENT=simulated forces templates; AOH_AGENT=claude forces Claude
```

**Finish → Demo Stage**: the end of the build-to-demo flow.
- **🏁 Finish & go to demo** (Team Room, any team member): confirms the submission (pre-filled), marks the team **Shipped**, and closes the roster. The team drops out of "Find a team" and matching, pending requests and invites are withdrawn (those people are told), and teammates are notified. Any member can **Reopen** while the challenge runs.
- **Demo Stage** (`#/t/<id>/stage`) runs the demo inside the app, no Zoom needed. Presenters (team members) set up privately first (🖥 **share screen**, 📷 camera as a small inset, 🎙 microphone that stays on while presenting), then **🔴 Go live**. Everyone is notified, and the demo appears on Demos with "▶ Watch live".
- **Viewers** see the shared screen and presenters' cameras, hear the presenters, react with emoji, and ask questions that presenters mark answered. **End demo** shows everyone a recap (peak viewers, reactions, questions).
- **How the video works:** every presenter sends directly to every viewer, and presenters see and hear each other. Each connection carries audio, screen and camera from the start, so toggling any of them never interrupts the stream. Viewers are capped at 30 (`STAGE_MAX_VIEWERS`); a bigger audience needs a media server (e.g. LiveKit). Screen sharing needs a desktop browser over HTTPS, or `localhost`.

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

## Deploy to Vercel

The same code runs as a Vercel Python function: `server.py` exposes a WSGI `app`, and Vercel routes every request to it (pages, static files and the API).

1. **Import the repo** at vercel.com/new. No framework preset or build command is needed; `requirements.txt` installs the Postgres driver.
2. **Add a database:** Storage → Neon Postgres (or any Postgres). This sets `DATABASE_URL`; the pooled connection string is the best choice. Tables are created and demo data is loaded on the first request. To load the data ahead of time, run `python3 seed.py "$DATABASE_URL"`.
3. **Optional settings:**
   - `ANTHROPIC_API_KEY` turns on the live Claude agent in the Build lab.
   - `AOH_AUTO_APPROVE=0` turns off demo auto-approve.
   - `AOH_LIVE_RITUAL=closing` (or another ritual) runs that ritual at the top of every hour, for demos.
   - `AOH_JUDGE_CODE` sets the judge sign-up code.
   - `AOH_SEED=0` skips the demo data.
4. **Push to `main`** and Vercel redeploys.

Without `DATABASE_URL`, each function instance uses its own throwaway SQLite file in `/tmp`. That's fine for a quick look, but data won't persist or be shared between instances.

**What changed to run serverless.** Nothing may run after a response is sent, so the long-running server's background work is now driven by requests:
- **Join auto-approve:** handled on the next request after the delay.
- **Ritual notices:** sent from `/api/clock`, which every open tab polls.
- **The Build lab agent:** works inside its own `POST …/agent/<id>/run` request, which the lab sends right after starting a task. Runs nobody picked up are given up after 10 minutes.

To test against Postgres locally:

```bash
AOH_TEST_DATABASE_URL=postgres://… python3 -m unittest test_server
```

Use an empty, throwaway database for this.

## Layout

```
server.py        HTTP server + WSGI app (Vercel), schema, every API route
db.py            SQLite locally / Postgres in production: translates the few dialect differences
static/buildlab.js  Team Room build lab: agent thread, preview sandbox, diff review, versions
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
- **Demo Stage at scale:** switch to a media server so one upload reaches any number of viewers, and add recording for replays.
- **Database:** SQLite locally; Postgres (`DATABASE_URL`) in production.
