# Demo script: Always-On Hackathon

A 12–15 minute walkthrough covering the whole journey: browse hackathons, open one, find a team or a builder, join, work in the Team Room, finish, demo live with screen share, and see the demo listed on the hackathon page.

**Story:** Lena is a designer who wants to join a hackathon tonight. In ten minutes she finds a team, builds with them, and demos live.

---

## 0. Setup (5 minutes before)

```bash
rm -rf data/ && python3 server.py        # fresh demo data, http://127.0.0.1:8000
```

Optional: `AOH_LIVE_RITUAL=closing python3 server.py` puts a closing ceremony live right away (see Act 7).

You need **two browser windows side by side**. Use different browsers, or one normal and one private window, so they keep separate sign-ins. Camera, mic and screen share need `localhost` or https.

| Window | Sign in as | Plays |
|---|---|---|
| **A** (main, on the projector) | `lena` | the new builder |
| **B** | `fatima` | Needle's team lead (teammate on calls) |
| **C** (optional) | `ben` | an audience member watching the demo |

Sign in is by handle only: click **Sign in** and type the handle.

Quick checks:
- In Window B, open **Find a team** → *Search Everything* → **Needle** → **🚪 Team room** once, and allow camera/mic so the prompt doesn't interrupt later.
- Close other tabs that might show notifications during screen share.

---

## Act 1: Hackathons, always on (2 min) · Window A

1. Open the **Hackathons** tab.
   > "There's always a hackathon running. There's a new Open Sprint every Monday, sponsor challenges all year, and real in-person events."
2. Show the toolbar:
   - **Live / Upcoming / Past / All** tabs
   - the format filter (**Online / In person**)
   - search, e.g. type `New York`
3. Point out **AI Engineer New York Hackathon**: in person, with a **Luma** button.
   > "In-person events link straight to Luma for RSVP. Luma stays the source of truth."
   - It's live only on Oct 11, 2026. On other days, find it under **Past** or **All**.
4. Clear the search and pick the live **Search Everything** card.

## Act 2: A single hackathon page (2 min) · Window A

The page tabs are **Overview · The Floor · Teams · People · Demos & projects**.

1. **Overview**, from top to bottom:
   - the countdown (**Ends in**) and team-size rules
   - **Information & instructions**
   - **Opening ceremony** video
   - **Sponsors & partners**: MLH Global Hack Week, Snowflake, Google · Gemma, DigitalOcean, DEV Community and others, each with its offer and link
   - **Food & beverage**
2. Click **Walk onto the floor**. This opens **The Floor** tab.
   > "The floor of an in-person hackathon: who's here right now, what they're shipping, who needs help."
   - Post a quick update, e.g. *"Just landed — designer looking for a team 👋"*.
3. Open the **People** tab and click a person to open their profile dialog: skills, timezone, **LinkedIn ↗**, and Connect / Invite / Save.
4. Open the **Teams** tab: every team, its roster and the roles it's looking for.

## Act 3: Find a builder (1 min) · Window A

1. In the top nav, open **Find a builder**.
   - Filter by role, skill or availability.
   - Open a profile and click **Save**.
2. Open **Buildmate** (the ✦ button, bottom right) and ask:
   > `Find 3 people with React in New York`

   It answers from the live directory, with clickable results and follow-up suggestions.
   > "This works from either side: teams find people, and people find teams."

## Act 4: Find a team and join (1 min) · Window A

1. In the top nav, open **Find a team** ("Find your missing piece").
   - Recommendations are scored by fit, e.g. *"Fills open role"* and *"Overlapping timezones"*.
2. On **Needle** (Search Everything: "Semantic search over every city council meeting transcript"), click **Request to join**.
   - Message: *"I can take the search UI and the demo video."* Click **Send request**.
3. Wait about 2 seconds. The toast reads **"You're in! Welcome to Needle 🎉"** and Lena lands in the **Team Room**.
   > "Demo mode auto-approves after two seconds. In real use the team lead accepts. The roster is capped at 4."
   - The nav now shows **🚪 My team · Needle**.
   - The clock bar shows **"Needle ships in …"**.

## Act 5: The Team Room (4 min) · Windows A + B

Window B (fatima) opens the same room: **My team · Needle**.

1. **What everyone's doing.** In A, click **Set** and type *"Wiring the search UI"*. It appears in B within a couple of seconds, with presence (here / on the Floor / away).
2. **Shared product browser.** Paste a URL into the address bar, e.g. `https://example.com` or your Vercel deployment, then click **Load for team**. B's browser loads the same page.
   > "Everyone is looking at the latest build. 'Pushed by @lena' shows who updated it."
3. **The call:**
   - A: **🎧 Join the call**, then **📷 Camera on** (opt-in; the camera stays off until you choose).
   - B: **🎧 Join the call**, then camera on. The video tiles fill the panel and re-tile as people join.
   - A: press and hold **Hold to talk** and say *"Fatima, can you hear me? I'm taking the search box."*
     - B hears it live.
     - The words appear in **Transcript** for the whole team. Captions need Chrome or Edge speech recognition.
   - Show **Download .txt**.
4. **Team timeline** (right column): *"@lena joined the team (auto-approved)"*, status changes, and agent tasks.

### Build lab (inside the Team Room) · Window A

5. Open the **✦ Build lab** tab: a shared three-file prototype plus a coding agent.
6. Click a suggestion chip, or type:
   > `Add a search box with sample council-meeting results`

   The agent shows *"Reading the brief and current files…"*. B sees the same task running.
7. When the proposal is ready, review the **diff** and click **✓ Apply to project**. The live preview updates and a new **version** appears. Restore is one click.
   > "With an `ANTHROPIC_API_KEY` this is Claude Opus 5.5. Without one, the simulated agent keeps the demo working offline. Nothing changes until a teammate applies it."

## Act 6: Finish → Demo Stage → screen share (3 min) · Windows A, B, C

1. In A, click **🏁 Finish & go to demo** (top right) and confirm.
   > "Any teammate can finish. It closes the roster and locks in the submission."
2. Everyone lands on the team's **Demo Stage**. Any teammate can **Reopen** the project from the Team Room later to keep building.
3. In A, before going live: click **🖥 Share screen** and pick a window, e.g. the Build lab preview. Turn the camera and mic on.
   - The panel note reads: "no one sees anything until you go live".
4. Click **🔴 Go live**. Window C (`ben`) gets a 🔔 notification.
   - In C, click **▶ Watch live**. Ben sees the shared screen and hears the presenter.
   - Ben sends emoji reactions; they float up on the presenter's screen.
   - Ben asks a question, e.g. *"Does it work for Spanish-language meetings?"*. It shows up in the presenter's **Questions** list; click **✓ Answered**.
   - The viewer count and peak are tracked.
5. In A, click **■ End demo**. The timeline records it, e.g. *"ended the demo — N watching at peak, X reactions, Y questions"*.

## Act 7: After the hackathon (1 min) · Window A

1. Go back to **Hackathons**, open **Search Everything**, then the **Demos & projects** tab. Needle's demo is now listed with the project.
   > "When a hackathon ends, its page becomes the archive: every team, every person, every demo."
2. Show the **Past** tab on the hackathons list. Finished events keep their demos.
3. Optional extras if there's time:
   - **Shared clock and rituals:** **Schedule** in the clock bar shows Monday Kickoff, check-ins and the closing ceremony. Every ritual can be added to your calendar. With `AOH_LIVE_RITUAL=closing`, open the live ceremony and show the lineup of demos.
   - **Judging:** sign in as `judy` and open **Judging**. Score submissions on innovation, technical, design and impact.
   - **Sponsors:** sign in as `nimbus` for the sponsor dashboard (views, teams, skills, perks claimed). Click **+ New challenge** to launch one.

---

## Closing line

> "Everything good about an in-person hackathon is here: the floor, the team table, the demo stage, the energy of a shared clock. And it's open every day of the year to anyone, anywhere."

## If something goes wrong

| Problem | Fix |
|---|---|
| The join doesn't auto-approve | Check the server wasn't started with `--auto-approve 0`. Lena may also already be on a team in that hackathon: reset with `rm -rf data/`. |
| No camera or mic prompt | Use `localhost` or https, and check the browser's site settings. |
| No transcript text | Use Chrome or Edge. Push-to-talk audio still works without captions. |
| Video doesn't connect between windows | Both windows must be on the same origin. On strict corporate networks, use one machine. |
| Agent seems stuck | The task resumes when anyone reopens the Build lab. Runs give up after 10 minutes. |
| Data looks used | `rm -rf data/ && python3 server.py` |
