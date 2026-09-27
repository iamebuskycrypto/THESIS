# THESIS 0.8.1 — Groq research drafts

The 0.8.1 patch moves Research connection into Announcement review, above Choose an announcement. It also treats `next_check.source_to_check` as a source name: one- or two-word names no longer need to pass a sentence-length rule. Nonempty text, valid citations, cited numbers, exact quotations, and the explanation checks still apply. The screenshot established a failure in this field, but did not include the rejected value; these offline checks reproduce the short-label bug, not a replay of that particular response. No live model request was made while preparing this patch.

Open THESIS with `python3 ~/Downloads/thesis-agent/launch.py`.

In **Announcement review**, open **Research connection**, paste the Groq API key, and choose **Use Groq for research**. The field is cleared after submission. The key lives only in the running app session; restart requires re-entry. Loading a key makes no API call and does not establish a connection until a review returns.

Choose an existing saved source brief and click **Assess evidence**. This sends its saved issuer passages to Groq once and saves a separate assessment. Or use **Review with AI** to collect a new source brief first. The app spaces Groq requests by at least a minute to reduce free-plan rate-limit errors. There are no automatic retries. Account limits still apply; keep the Groq account on Free. THESIS does not inspect or change billing.

The research model is `openai/gpt-oss-120b`, reached only at `https://api.groq.com/openai/v1/chat/completions`, with structured JSON, a 4,096-token output budget, and a 90-second request timeout. No browser tools are requested. The app does not store model reasoning traces. Public issuer passages are sent to Groq only when a research action is requested. No API key is included in status responses, saved research records, or exports.

## What changed

The assessment now includes an exact source excerpt and separate condition rows. Each row contains an outcome span, condition span, pending/satisfied/unstated status, and supporting source quote. The validator checks that the quote is present verbatim in the cited passage and that both spans appear in that quote. It checks cited numeric tokens and output structure, retains all detected mechanical issues, and rejects invalid drafts without silently repairing them.

The UI labels these outputs **AI draft**. Exact copying does **not** establish that the condition has been correctly attached to the outcome, that the status is correct, that all relevant conditions were selected, or that the issuer statement is true. Check the source text beside each mapping. Business implications and future checks remain AI interpretations, not verified conclusions or trading signals.

This is a workflow change, not a claim that the observed model reasoning errors are solved. The earlier four-case Groq run established connectivity only; it contained material unsupported claims. No live call on this revised schema was run during packaging. Its first real outputs must be reviewed before claiming improved reasoning quality.

## Existing data and the paper engine

The paper decision model and execution rules are unchanged. Groq is a separate, explicit research connection. Old reviews remain readable; old records are not rewritten or relabelled as results of the new workflow. Research does not approve or place paper orders. Saved input checks remain historical context.

## Verification

Focused tests use mocked model outputs to check exact-copy rejection, citation checks, multiple error reporting, truncated responses, credential handling, request pacing, session protection, and preservation of the original source brief and paper records. Existing assessment and research-rendering regressions were also checked. These are implementation checks, not model accuracy tests.

Installer checks covered backup, idempotent installation, restoration, refusal to overwrite unknown edits, and rollback after an interrupted write. A visual browser check could not run in the packaging environment because its browser download failed; the rendered appearance on the Mac still needs inspection.

## Roll back

Stop THESIS, then run:

```bash
python3 ~/Downloads/THESIS-Fix-081.py --restore-latest --install-only
```

This restores the newest backup created by this installer. It verifies that the current code still matches this update and refuses to overwrite unrecognized edits. Paper records and model settings are outside the rollback.

API reference used for this adapter: https://console.groq.com/docs/structured-outputs and https://console.groq.com/docs/reasoning.
