# THESIS — competition build brief

Updated 18 September 2026. Working name and proposed direction, open to revision
once the team's existing code, data access and compute budget are known.

**Build 0.3 progress:** A local interface, issuer-feed ingestion, session checks,
continuous paper runner, quote refresh, fixed exits and a comparison rule are now
implemented. Thirty-five automated tests passed. THESIS now supports either an
online HTTPS provider with an API key or a compatible model running on the same
computer without a key. A genuine model-backed forward run still needs a model
to be configured and tested. A daylight-label conflict was resolved for
the observed instruments by verifying complete daily session coverage; partial-day
instruments remain blocked on conflicting metadata. See the README for detail.

## The entry I would build

**An event-driven agent that decides whether a stock's news still offers a trade
after the market's response, trading costs and execution constraints.**

The initial user is a part-time trader who follows a small set of tokenized U.S.
technology stocks and cannot monitor every announcement. The initial product is
a supervised paper-trading agent for that watchlist. It produces buy, reduce or
hold decisions, with the source, observed price reaction, concise explanation,
invalidation condition and resulting portfolio change visible together.

The research hypothesis is that grounding an LLM in timestamped primary evidence,
the pre-event reference price and current tradable quotes improves decisions over
a simple news-response rule after costs. This is **a hypothesis to test**. There is
no demonstrated predictive edge, unique-in-market claim or guaranteed contest win.

## Competition facts that drive the design

Proposed track: Agentic Trading, Event-Driven Agent. The handbook describes an
LLM-led decision/execution system and permits simulation. The current stated
submission deadline is **September 27, 2026 (UTC+8)**. A valid entry also needs
a runnable demonstration, project description, materials link and a compliant
promotional X post. The plan should focus on genuine model-backed forward logs,
not invented history. [Official handbook](https://bitget-ai.gitbook.io/bitgetai_hackathons2).

The selected examples on the event page already include overnight stock tracking
and trading safeguards. Our contribution must therefore go beyond those features:
the proposal is a tested connection between an event, what price has already
absorbed, and the incremental value of the agent's decision.
[Selected examples](https://www.bitget.com/activity-hub/hackathon).

## Product experience

One screen should answer six questions without opening technical logs:

1. What happened, and where is the original evidence?
2. When was it published, when did we observe it, and how old is the quote?
3. How much did the instrument move after the event?
4. Why did the agent choose to trade, reduce or wait?
5. Did executable prices and risk limits permit the decision?
6. What happened next, and how did the comparison rule perform?

The user can inspect an individual decision and download its evidence packet.
A display of model-generated confidence must not masquerade as a calibrated
probability. Explain missing information and show abstention explicitly.

For the first release, use three verified stock-token instruments, one trusted
event source class and one trading horizon. Select the final watchlist after
observing liquidity and event availability; Apple, Nvidia and Microsoft are
integration candidates, not asserted opportunities. Avoid spreading a five-day
build across crypto, options, futures, sentiment and multiple exchange venues.

## The decision system

| Component | Responsibility | Evidence the reviewer can inspect |
|---|---|---|
| Evidence collector | Archive an official release, timestamp it, identify duplicates and map the issuer to the instrument | Original URL, text hash, publication and observation times |
| Market collector | Capture quotes, exact symbol, instrument constraints and trading availability | Raw Bitget response plus collection timestamp |
| Feature builder | Calculate pre/post-event price movement and a transparent cost estimate | Reproducible numbers and their source snapshots |
| LLM decision maker | Choose action and target exposure, explain what remains uncertain, name invalidation conditions | Structured decision and short evidence-based rationale |
| Independent execution rules | Reject invalid data and proposals outside fixed limits | Rule outcome, policy version, estimated costs |
| Paper executor | Apply a documented conservative fill model or supported exchange demo route | Order intent, fill/rejection and portfolio state |
| Evaluator | Compare the frozen agent and predeclared rules on matching observations | Full denominators, drawdown, costs, outcome distributions |

Use a single LLM decision maker initially. Separate collectors, rules and accounting
in code, but adding model calls must earn its latency and cost through measured
improvement. The LLM proposes the trade; deterministic rules can veto it. That
division preserves autonomous decision-making without letting generated text alter
position limits or execute arbitrary commands.

## Proof that could make the submission competitive

Freeze the model, prompt, policy and comparison rules before the forward evaluation
window. If something changes, version the run and report each period separately.

Run these comparisons on the same allowed instruments, timestamps, quotes, starting
capital and fee/slippage assumptions:

- Cash and a predetermined buy-and-hold allocation for market context.
- A simple documented event rule with identical execution limits.
- The LLM agent receiving the event but no pre/post-event price-response feature.
- The full agent receiving both the evidence and observed market response.

Comparisons must expose whether the LLM and the price-response information each
add value. Do not define the simple rule after seeing which version loses. An
agent that makes fewer trades can look safer because it takes less exposure;
report time invested, turnover and exposure as well as returns.

Separate three evidence groups:

| Evidence | What it can establish | What it cannot establish |
|---|---|---|
| Synthetic scenario tests | Whether a rule or state transition behaves as specified | Investment returns or LLM reasoning quality |
| Historical event replay | Behavior on an archived, controlled sample | Prospective profits; freedom from model memorization |
| Forward paper run | Decisions actually produced on newly observed information | Proven live fills, durable alpha, or long-run reliability |

For historical replay, archive the data available at decision time and exclude
subsequent returns from the decision input. Explicitly disclose the possibility
that a pretrained model already knows the historical event. Forward collection
is the strongest available check against that problem. Never backdate collection
times or combine replay duration with forward duration.

Record net returns, maximum drawdown, turnover, time invested, completed-trade
count, win rate with its denominator, no-trade rate, rejected proposals, stale-feed
incidents, decision latency and inference cost. Use fixed-interval portfolio marks
for return statistics. Treat Sharpe/Sortino from a few days as unstable descriptions;
do not annualize a short, selected sequence into an impressive headline. Show all
failures and compare results across more than one cost assumption.

## Demonstration sequence

Target three minutes. Use genuine recorded runs when available and clearly label
any scenario reenactment.

1. Open an event with its source and times. Show the observed price response.
2. Show the agent's concise decision and the independent execution result.
3. Inspect a second case where costs, missing evidence or a price move remove the
   reason to enter. Make the abstention as understandable as the trade.
4. Show the forward comparison with counts and costs visible.
5. Open a failed decision and its record. Explain the limitation and next fix.

The memorable capability should be: **a reviewer can reconstruct why the agent
took or refused a trade, and see whether that decision process earned its cost.**

## Build sequence

| Date / gate | Deliverable | Pass condition |
|---|---|---|
| September 16 | Data feasibility, core and first model connection | Fresh real quotes and archived event reach a real configured LLM; one complete paper decision is recorded |
| September 17 | Continuous runner and comparison rules | Duplicate events, restarts, missing data and model failures do not corrupt holdings; begin frozen forward run as soon as possible |
| September 18 | Position monitoring, thesis expiry, stress cases and historical replay | Entry, exit and abstention are reproducible; replay is kept separate from forward logs |
| September 19 | Review interface and evaluation report | Judges can inspect sources, decisions, fills, baselines, costs and failures |
| September 20 | Demo recording and complete submission draft | Links work without private setup; description and actual evidence agree |
| September 21 | Deadline buffer | Submit before the organizer-confirmed cutoff |

This is an aggressive schedule, not a claim that the full product already exists.
Preserve existing genuine logs if the team has them. If starting from zero, the
short forward window is a competitive weakness that cannot be repaired with
manufactured history. Do not add more features at the expense of evidence collection.

## Current implementation and next dependencies

The accompanying source implements the execution foundation, local interface,
issuer-feed collector, continuous runner, position monitor and initial comparison
rule. Mechanical and integration tests pass. A genuine LLM-backed forward run and
a comparative performance study remain.

To choose the next implementation step, establish:

- Whether an existing codebase and genuine competition-period logs already exist.
- Which model API and secure local configuration are available, with a usage budget.
- Which official event feed can be archived at observation time.
- Whether Bitget demo supports the selected stock tokens and whether approved
  Reality depth access is available. Verify these rather than assuming them.
- Which continuously running machine or service will own the collector and ledger.

The first measurable milestone is one complete, real-model paper decision using
fresh, sourced inputs. The second is an uninterrupted, versioned forward run.
The interface and pitch should make those results easy to judge.
