# THESIS 0.9.1 — stock research without a visitor API key

Evidence before action.

[Open stock research](https://thesis-research-bay.vercel.app/) ·
[Watch the walkthrough](https://thesis-research-bay.vercel.app/THESIS-Explainer.mp4) ·
[Evidence and limitations](https://thesis-research-bay.vercel.app/THESIS-Evidence-Review.html)

THESIS brings official announcements for Apple, NVIDIA, Microsoft, Amazon, Meta, AMD, Intel and Broadcom, source-linked AI research
drafts and timestamped Bitget stock-token observations into one local workspace.
The researcher makes the final decision. A separate paper simulator uses simulated funds.

## Online research — no API key needed

Open https://thesis-research-bay.vercel.app/ . Select a stock, search its official
announcements, read source passages, refresh a public Bitget stock-token quote,
and save research in your browser. No account, API key, installation, model
download or provider credential is required for this reader.

Publication dates stay visible: retrieving a feed now does not mean its articles
were published recently. Article extraction can fail; the UI falls back to the
feed excerpt with an explicit label. Quotes expire after fifteen seconds.

**This is a source reader, not hosted AI.** It copies issuer evidence and makes
zero model calls. It does not generate business conclusions or execute trades.
Optional local-model AI and the existing Groq workflow remain in the local app.
Public hosted AI would require a separately configured operator-owned model
service; no such shared credential is currently configured.

The original recorded demo remains at `/demo.html`. Archive links open a separate
tab, and the archive includes a return link to current research. It contains saved AI reviews,
scripted paper-execution examples, video and original evidence downloads. Those
records have not been relabelled as fresh results. The archived demo pins its
video and original downloads to their existing immutable Vercel deployment.

## Hosted architecture

`public/` contains the browser UI and original recorded demo. The stateless,
read-only `api/research.py` Vercel Function uses `hosted_reader.py`. It accepts
catalogue symbols and feed event IDs, never visitor URLs. Issuer host/path
allowlists and bounded responses constrain collection. Successful sources are
CDN cached for five minutes, quotes for ten seconds. Errors are not cached.

Deploy the repository to Vercel using `vercel.json`. The hosted reader never
starts the local paper runner, writes SQLite files, reads credentials or calls an
AI provider. Browser saves stay on that device; clearing browser data removes
them. No model or Bitget trading key is embedded in public assets.

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
3. Open **Announcement review** and click **Refresh news**.
4. Search any of the eight companies, choose an announcement and click
   **Read source**. No key or model is required. The exact source passages are
   saved and clearly marked as zero-model-call source briefs.
5. For optional AI explanations, connect a local Ollama model under **Model
   setup** with the API key field blank. The advanced Groq connection also
   remains available if you choose to supply your own provider credential.
6. Inspect cited text and limitations. **Portfolio & journal → Export complete
   run** downloads local research and paper records with a hash manifest.


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
node --test tests/test_research_ui.cjs tests/test_reader_ui.cjs
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
