# THESIS 0.7.1

THESIS is a local research and paper-trading workspace for Apple and NVIDIA Reality stock tokens on Bitget. It reads official announcements, collects public market data, asks Qwen for decisions, and records simulated outcomes with their evidence. It never sends exchange orders.

## Start on your Mac

Prerequisites: Python 3.10 or newer, Ollama running, and the downloaded `qwen3:8b` model. No Python packages, Alibaba account, model API key or Bitget trading key are required for this local configuration.

From Terminal, run:

```sh
python3 ~/Downloads/thesis-agent/launch.py
```

The launcher opens `http://127.0.0.1:8765` in your browser. Leave Terminal and Ollama open. To stop, press Control (⌃) + C in the Terminal window running THESIS. Your records remain saved in `run-data` inside the app folder. The included `Start-THESIS.command` is an optional double-click launcher if macOS allows it.

The launcher preserves the existing app-only Bitget DNS workaround. It changes name resolution only inside this Python process, keeps HTTPS certificate verification enabled, and restores the original resolver on exit. It does not edit Mac network settings. If Bitget is temporarily unreachable, the workspace still opens so you can inspect saved records.

## Use the product

1. **Overview:** refresh inputs, run one paper cycle, then start or pause monitoring. The app checks for eligible announcements about once a minute and refreshes issuer feeds about every five minutes. Monitoring requires the app and Mac to stay running.
2. **Live inputs:** inspect feed timestamps, quote age, spreads and trading-session status. Old news can remain visible without entering the trading strategy.
3. **Announcement review:** pause monitoring, choose an announcement and review it with Qwen. THESIS retrieves a bounded article excerpt and asks Qwen to choose an event category and source highlights. The app copies eligible passages exactly, retaining amounts and conditions beyond the AI highlights. It shows saved market observations alongside the source text. Click **Assess evidence** for one additional model call on the same saved passages. It explains the announced change, possible business effect, strongest limitation and a specific next source to check, then suggests **Investigate further** or **Wait for more evidence**. Each claim cites collected passages. Structure, source IDs and literal numeric tokens are checked; these checks do not establish semantic truth or investment quality. The original brief is preserved. Saved paper-entry checks are shown separately and never approve an order. Failed responses remain inspectable; there are no automatic retries. Older generated reviews remain readable with a reliability notice. This research workflow never places trades.
4. **Portfolio & journal:** inspect holdings, simulated equity, costs, decisions, rejections, fixed exits and their source evidence. Each instrument and decision maker has its own 10,000 USDT simulated account. These are not one shared multi-asset balance.
5. **Export complete run:** pause monitoring and wait for any active request. Download every ledger entry and portfolio mark, saved research review, event, and collected raw feed/market file. A manifest contains SHA-256 hashes; ledger chains are checked before export. No provider key or synthetic demo is included.
6. **Demo lab:** six scripted scenarios exercise the real paper executor. They demonstrate software behavior and are explicitly not model results or trading-performance evidence.
7. **Model setup:** the launcher configures local Qwen. Use Connect & test if needed. Online providers are optional; their credentials remain in app memory. Switching the model or policy of an existing recorded run requires a separate data folder.

## What the paper strategy does

Only new eligible issuer events within one hour of publication enter the existing strategy. The model can buy, sell, or hold. Independent rules check source chronology, quote freshness, trading availability, spread, position size, displayed liquidity, costs and price drift during the model call. A quote is refreshed after the decision. Each fill includes simulated adverse slippage and fees. Fixed holding-time and stop rules monitor positions; an exit can be blocked when market data or liquidity is unsuitable.

The comparison rule uses the same decision-time execution packet and execution limits after a valid model decision. Research reviews, scripted demos and model failures do not become profitable strategy observations. A HOLD or rejected trade can be correct behavior. No advantage or profitability has been demonstrated.

The journal values open positions at the last accepted bid. Net change includes charged fees and fill slippage but does not subtract prospective exit fees. Drawdown is measured from the observed equity peak; it is not a guarantee about future losses. Quotes and marks retain their timestamps.

## Acceptance check

Keep Ollama open and pause paper monitoring. Run:

```sh
python3 ~/Downloads/thesis-agent/check_product.py
```

The check reads both official feeds and Bitget markets, checks the installed model, makes a real Qwen paper decision on fictional inputs in an isolated ledger, runs eight fictional source-brief cases, and records exact inputs and model responses. For a focused check after an update, append `--reviews-only`; this skips repeating market and paper-adapter checks. It writes a ZIP in `~/Downloads/THESIS-Acceptance-results` and reveals it in Finder. Upload that ZIP for review. This check does not edit observed run data or Mac settings.

For all eight development cases:

```sh
python3 ~/Downloads/thesis-agent/evaluate.py
```

The development examples informed the prompts; they are not a hidden benchmark. Actual 0.6.0 Mac testing accepted none of four new generated assessments, and the same-model auditor missed all four previously identified mistakes. Version 0.6.1 replaced that workflow with source selection and exact copying. Version 0.7.0 adds an optional, separately saved research interpretation, without the unreliable same-model audit gate. Its actual model quality must be reviewed against source evidence. Higher brief-completion counts would not demonstrate improved business reasoning: this is a narrower task. Recognisable instruction passages are quarantined, but this narrow screening is not a complete prompt-injection defence. Original evidence and exact model inputs remain available. Old rejected drafts and audit judgments are preserved unchanged. Sources may be incomplete or later updated; issuer claims are not independently verified facts.

## Focused assessment check (0.7.0)

```sh
python3 ~/Downloads/thesis-agent/check_reasoning.py
```

Four real local model calls use the photography, financing, nonbinding-partnership and source-instruction development cases. Source selection is fixed by the test. Reports retain the exact eligible text, prompt, wire request, raw response, failures and human review questions. Completion counts reflect format and reference checks, not correct business reasoning. Reports are written to `~/Downloads/THESIS-Reasoning-results`; upload the resulting ZIP for review. Paper records are not opened.

## Condition clarification in 0.7.1

The Mac's 0.7.0 run completed all four format/reference checks, but both financing
answers attached a factory construction permit to financing completion. The
source linked financing closing to investor approval and the permit to factory
construction. This demonstrates a semantic error despite a mechanical completion.

Version 0.7.1 clarifies the prompt: name each outcome with its own stated condition,
preserve already satisfied conditions, and never infer a dependency from proximity
in the source. It also asks promotional follow-ups to distinguish attributable
purchases from engagement. No new keyword rule is presented as a semantic verifier.
The revised model behavior is unverified until actual answers are reviewed.

For the focused check:

```sh
python3 ~/Downloads/thesis-agent/check_reasoning.py --condition-check
```

Two calls use the original financing case and a new diagnostic variation where a
permit really is a financing-release condition. The variation was authored after
the observed mistake; it is not an independent benchmark. Format/reference counts
retain failures and do not establish correct reasoning. Exact requests, responses,
human review questions and previous records remain available.

## Troubleshooting

- A message about an earlier app session: reload the browser page after restarting THESIS.
- Model unavailable: open Ollama and confirm `ollama list` contains `qwen3:8b`.
- No paper decisions: inspect news age and trading availability. THESIS does not backdate old news or invent trades to populate the dashboard.
- Port already in use: stop the earlier THESIS Terminal process before starting another copy.
- Failed brief or older disputed review: inspect its exact error and saved evidence. Do not count it as an accepted result. The app does not silently retry or replace it.
- Export larger than 100 MB: stop THESIS and copy the complete `run-data` folder for a full backup.

## Developer verification

```sh
python3 -m unittest discover -s tests
node --test tests/test_research_ui.cjs
```

Automated tests use explicit doubles and fixtures for model/network behavior. They verify implementation and isolation, not actual Qwen quality. A separate acceptance run on the target Mac is required.
