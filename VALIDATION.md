# Validation record — 18 September 2026

## Build 0.3 update

**35 automated tests passed.** The new tests verify that THESIS accepts a
keyless HTTP Chat Completions endpoint only when it is on the local computer,
while online providers still require HTTPS and an API key. They also verify that
an otherwise compatible local model response wrapped in a JSON code fence is
parsed safely. The interface script passed Node's syntax check.

No local model was installed or called during this validation, so this confirms
the connection contract rather than the quality or performance of any model.

## Build 0.2 update

**33 automated tests passed.** These include the original checks plus issuer-feed
parsing, source-domain rejection, future-news rejection, XML entity rejection,
preservation of first observation time, session/calendar handling, quote refresh
after inference latency, rejection of material price drift, holding expiry,
portfolio marking, run-profile freezing and a complete pipeline using an
explicitly labeled model test double. The six-scenario demo's outcomes matched
the expected fill/wait/rejection sequence.

Six in-process HTTP checks also passed: HTML delivery, demo endpoint, status
endpoint, rejection without the request token, rejection of a foreign Host header,
and refusal to start trading without a model connection. Interface JavaScript
passed Node's syntax check.

The live collection check retrieved **40 issuer-feed entries** across Apple and
NVIDIA, plus market and session metadata for both selected instruments. Its latest
market observation was 2026-09-16 18:31:10 UTC. These are observations, not trades.

The session API returned a daylight label inconsistent with New York's date.
Both observed instruments explicitly support all four daily sessions, whose
intervals cover all 1,440 minutes. The resolver therefore permits the narrow
full-day, non-closure case while retaining the conflict in its output. A conflicting
partial-day schedule is blocked. Calendar closures remain enforced, with an extra
hour at each boundary when the daylight label conflicts. This resolution was
tested, including a full-day instrument on a holiday.

No real model provider was called: credentials were not configured. No actual
model-backed forward run, investment-performance evaluation or exchange order
was completed. The cloud browser's URL policy blocked the local interface and
offline preview, so visual browser verification was not completed. The downloaded
HTML preview can be opened locally.

The records below describe the earlier build 0.1 and remain as historical evidence.

## Executed checks

`python3 -m unittest discover -s tests -v` completed successfully: **16 tests passed**.

Coverage includes cost accounting, adverse fill assumptions, duplicate processing
across a restart, stale quotes before and after inference latency, future-dated
evidence, invented source references, position caps, the cost hurdle, insufficient
displayed liquidity, non-finite model output, unsupported actions, drawdown entry
blocking with reduction still available, separate synthetic/observed modes,
provider failure, ledger edit detection and session availability.

The synthetic demonstration produced:

| Scenario | Result |
|---|---|
| Scripted opening decision | Local simulated fill |
| Stale quote | Blocked |
| Wide spread | Blocked |
| Scripted exit decision | Local simulated fill |

These tests do not establish LLM reasoning quality or investment performance.

## Public API check

Six public Bitget requests succeeded: instrument and ticker requests for
`RAAPLUSDT`, `RNVDAUSDT` and `RMSFTUSDT`. The first observation was collected at
2026-09-16 18:06:17 UTC. Raw responses and observation times are retained in
`evidence/bitget-observations.json`.

| Instrument | Quote age at collection, seconds | Observed bid size | Observed ask size |
|---|---:|---:|---:|
| RAAPLUSDT | 1.644 | 63 | 85 |
| RNVDAUSDT | 0.949 | 212 | 290 |
| RMSFTUSDT | 1.191 | 65 | 1 |

This demonstrates access to these public observations at that time. It does not
establish continuous feed availability, permissions for trading, depth access,
or executable fills. The thin displayed Microsoft ask is a concrete reason to
check available size before assuming that a paper order could fill.

## Not executed

- No model API call: no provider credentials were configured.
- No official event-feed ingestion or independent source verification.
- No continuous forward paper trading or historical investment evaluation.
- No exchange demo orders or live-money orders.
- No deployment, social post, or contest submission.

The implementation is an initial engineering deliverable, with remaining work
explicitly described in the README and build brief.
