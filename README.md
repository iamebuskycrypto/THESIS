# THESIS 0.8.1 — runnable research workspace

Evidence before action.

[Explore the recorded demo](https://thesis-research-bay.vercel.app/) ·
[Watch the walkthrough](https://thesis-research-bay.vercel.app/THESIS-Explainer.mp4) ·
[Evidence and limitations](https://thesis-research-bay.vercel.app/THESIS-Evidence-Review.html)

THESIS brings official Apple and NVIDIA announcements, source-linked AI research
drafts and timestamped Bitget stock-token observations into one local workspace.
The researcher makes the final decision. A separate paper simulator uses simulated funds.

## The fastest way to explore

Open the [public browser demo](https://thesis-research-bay.vercel.app/). It contains saved results, search, source
passages, recorded AI drafts, the demo video and downloadable evidence. It does
not call a model, refresh quotes or execute paper trades. No key is required.

## Run fresh research on your computer

1. Install Python 3.10 or newer if needed. Clone this repository or download and
   extract its source ZIP into a NEW folder.
   Keep your existing THESIS installation and records in their current folder.
2. In Terminal, change to the repository folder containing `launch.py`, then run:

   ```sh
   python3 launch.py
   ```

   On Windows, use `py launch.py`. The launcher opens http://127.0.0.1:8765.
   Keep the Terminal window open. Stop with Control+C in that window.
3. Open **Announcement review → Research connection**. Enter your own Groq API
   key and select **Use Groq for research**. No key is bundled with this project.
   Ollama is not required for Groq research. THESIS cannot inspect account billing;
   provider quotas and charges depend on your account.
4. Click **Refresh news**, search for Apple or NVIDIA and select an announcement.
5. Click **Review with AI**. Read the exact selected passages. After the displayed
   cooldown, click **Assess evidence** for a separate business explanation.
6. Inspect the cited text and limitations. Saved reviews keep the source brief
   and AI assessment separately. Portfolio & journal → **Export complete run**
   downloads the research and paper records with a hash manifest.

Research credentials stay in the running Python process. They are cleared from
the form after entry, and are not included in saved review exports. Restarting
requires re-entry. Public issuer passages are sent to Groq for requested research.

## Optional paper workflow

Install Ollama and `qwen3:8b` if you want the separate local paper decision model.
The launcher supplies its local endpoint defaults; **Model setup** has its
connection test. Research uses the separately selected Groq connection.
Refresh inputs, try **One cycle**, inspect the journal, then optionally **Start
paper run**. Pause stops monitoring. The app/computer must remain running.
Old announcements are not backdated into the one-hour entry window. A closed or
unverified session, stale quote or failed rule may prevent a simulated trade.
No exchange trading key is required, and the app never sends exchange orders.

## Reproducible evidence and limitations

The linked browser demo uses an actual user-exported run with 42 collected announcements,
23 research records across development versions and four separate simulated
accounts. Those accounts contain zero recorded decisions and zero fills.
Records include failed attempts and older model errors. A completed status means
the app's mechanical checks completed; it does not establish semantic accuracy.
One recent saved Groq source brief took 2.56 seconds of model time; its completed
assessment took 3.64 seconds. These are individual observations, not a latency benchmark.

The draft's proposed future earnings check must be read conditionally: check
whether relevant metrics are disclosed. The source does not guarantee that a
future filing will contain Siri AI metrics. This editorial correction is shown
separately in the browser demo; the original saved answer is not rewritten.

The source-copy and citation checks do not establish that an interpretation is
true. No trading advantage, profitability, general model accuracy or independent
user study has been demonstrated. The Demo lab uses scripted fictional decisions.

## Technical notes

Python standard library server, SQLite, plain JavaScript/CSS/HTML. No pip install
is needed. Research uses Groq's `openai/gpt-oss-120b`; optional local paper decisions
use Ollama/Qwen. Official issuer feeds/articles and public Bitget APIs supply data.
The server binds to loopback with host/origin and per-session request checks.
Do not expose this local server directly as a shared multi-user hosted service.
The launcher uses an app-only Bitget DNS fallback with HTTPS verification intact.
It does not edit system DNS settings.

## Troubleshooting

- Stop an earlier THESIS process if port 8765 is already in use.
- Reload the tab after a restart if request/session verification fails.
- Use the visible Groq cooldown; do not repeatedly click while it is waiting.
- Public news or market services can fail independently. Inspect saved records
  and try a fresh refresh later; never present saved quotes as live.
- A fresh install starts with empty working records. The demo evidence is separate.
- If `launch.py` cannot resolve Bitget, the app can still open for saved inspection.

## Developer checks

The Python checks require Python 3.10+. The separate JavaScript checks require
Node.js 18+. Running the app itself does not require Node.js.

```sh
python3 -m unittest discover -s tests
node --test tests/test_research_ui.cjs
```

These checks use fixtures and test doubles. They do not verify live model quality.
Historical development notes are preserved in DEVELOPMENT-HISTORY.md and the
other included notes; this README is the current setup guide.

## Source map

| File or folder | Purpose |
| --- | --- |
| `launch.py`, `app.py` | Local launcher and HTTP server |
| `pipeline.py`, `issuer_article.py` | Public news and market collection |
| `research.py`, `evidence_brief.py`, `review_steps.py` | Saved research workflow and source briefs |
| `research_groq.py`, `research_reasoning.py`, `research_grounding.py` | Research model adapter, prompt and evidence checks |
| `agent.py`, `runner.py` | Paper decisions, execution checks and monitoring |
| `interface.html`, `research.js`, `research.css`, `journal.js`, `journal.css` | User interface |
| `run_export.py` | Evidence export and manifest |
| `tests/` | Automated checks and development fixtures |
| `evidence/` | Bundled observations and explicitly fictional demo inputs |

The app creates `run-data/` locally when started. That folder is excluded from
Git. Share a deliberately reviewed export when publishing research evidence.
The Vercel site is a recorded demonstration; this repository runs fresh research
locally with your own model connection.
