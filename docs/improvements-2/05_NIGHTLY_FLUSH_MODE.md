# Round 2, item 5: nightly Flush Mode checks

**Status:** implemented and verified; owner review pending.
**Branch:** `codex/round2-item5-nightly-flush-mode`.
**Roadmap:** [second-round item 5](../IMPROVEMENTS_ROADMAP_2.md#item-5-nightly-flush-mode-checks).

## Maintenance behavior

Every ordinary nightly maintenance run checks live Flush Mode counts after health
and before checking library-file freshness. Recent, Full and January 1 history
rebuild runs use the same checker. If all four canonical files are already current,
their refresh jobs remain skipped, but the policy observation still happens.
Delayed duplicate triggers may repeat the inexpensive count check; they do not
create duplicate library jobs merely to update policy.

The existing Berlin schedules, early probes, 22:00–05:00 window, DST handling,
workflow concurrency and manual maintenance budget are unchanged. Scheduled
invocations outside the window start neither count checks nor library jobs.
The existing ordered four-source manifest, reconnect behavior, automatic library
rate-limit recovery and accepted checkpoints remain intact.

The automation posts to the existing `/flush-mode/check` endpoint. That use case
owns live Spotify reads, hysteresis, failure retention and field-preserving CAS.
No automation request changes `control`: Force On/Off persists, while the
independent automatic decision keeps updating underneath it. Results report
both counts, effective mode, control, successful timestamp and reason.

Transport, gateway and Space restarts use the existing bounded HTTP retries.
A count failure returned in an HTTP 200 is also an explicit failure: the previous
successful observations and decision remain stored, and the automation retries
at the existing 20-second interval within its maintenance deadline. It does not
claim fresh success from stale counts. Exhausting that deadline fails visibly;
no library job is started before a successful count check. Invalid status fields
or incomplete successful observations fail explicitly instead of reporting green.

## Read-only and narrow manual verification

`check_only` remains read-only. It verifies the usual authentication, shared
state, four artifacts and idle routine endpoints, then reads `/flush-mode`.
It never posts a count check, requests Spotify counts or changes operator control.
Unobserved Automatic status is valid before the first successful policy check.

GitHub Actions also offers **`flush_mode_only`**, default off. This performs a
live policy check without starting history or library refresh jobs. It is useful
for release verification and uses the same authentication and bounded retries.
If both workflow booleans are selected, read-only `check_only` takes precedence.
The command-line flags themselves are mutually exclusive.

```console
python .github/scripts/nightly_refresh.py --check-only
python .github/scripts/nightly_refresh.py --flush-mode-only
python .github/scripts/nightly_refresh.py --scheduled
python .github/scripts/nightly_refresh.py --scheduled --full-rebuild
```

The runner remains Python 3.13 with standard-library-only imports. No new secret,
service, schedule, dependency, public application route or data schema is needed.
The typed HTTP resource decodes external policy responses at its JSON boundary;
the named application workflow calls that resource directly before the existing
freshness decision. Domain rules remain shared with the panel and CLI.

## Owner review

- [Account preview](http://127.0.0.1:8767/?review=round2-item5).
- [Offline preview](http://127.0.0.1:8769/?review=round2-item5).
- Unlock text: `nightly-flush-review`.

Both previews use isolated local state and durable data. No account routine or
live production count check is run before this item's approval. The frontend is
unchanged; the existing panel reflects observations made by the nightly script.

For a repeatable offline review, run this private helper from the repository:

```console
.venv/bin/python /private/tmp/round2-item5-simulate-night.py
```

It executes the branch's real maintenance entry point against **only** the
synthetic server on port 8769, with a fixed in-window clock. All four local files
are already current: the log reports the count check and skips library jobs.
Repeat it to observe 2,399/1,199 normal, 2,400/900 active, and 1,300/950 retained
active. The fourth invocation encounters a synthetic failure, retains the prior
state, waits twenty seconds, retries, and exits mode at 1,200/900. The panel polls
these results normally. Set Force On/Off in the offline panel before a run to
verify that the override persists while automatic observations update.

Append `--check-only` to verify there is no new count read or state change, or
`--flush-mode-only` to exercise the narrow checker. Review fixtures and helper
code stay outside the repository and deployment. The initial offline scenario
is restored after verification.

## Verification and release

Focused checks cover real entry-point dispatch in Recent/Full/annual modes,
Berlin boundaries and DST, current-file duplicate triggers, mutually exclusive
verification flags, read-only check-only requests, codec validation, transient
HTTP recovery and deadline clipping. Integration tests run the actual HTTP
adapter through the real policy endpoint and local namespace persistence for
Automatic, Force On and Force Off across normal, activation, hysteresis, failed
counts and recovery/exit observations.

All 90 recorded original automation outcomes and complete prior request/message
sequences are preserved after removing only the new Flush Mode observations.
The fixture intentionally extends 31 scenarios; no previous error, cancellation,
reconnect, library-job sequence or artifact freshness behavior changes.

`just ci-test` passed **12,593 tests**, random-order seed **227521**, in
**492.72 seconds**, with **95.41%** aggregate coverage and every independent
statement/branch floor passing. The single warning is the existing
Starlette/httpx TestClient deprecation. Package Ruff/formatting and typing
(744 checked files), strict inner typing (493 checked files), architecture and
callback guards passed. An additional strict pass covers the changed HTTP
resources and new integration tests.

All **11 public interface artifacts** remain unchanged. Wheel verification passes
for **744 exact runtime files**, **45 commands**, **139 wrapped routes** and both
installed entry points. The operational script still imports with `python -S`
and its automation sources parse as Python 3.13.

Both previews serve the exact branch runtime and operational script, have
**20 idle job endpoints**, and retain their original local state after resetting
the synthetic scenario. The account preview retains the owner's existing policy;
no account count check or routine was started. Offline browser verification
observed ordinary polling, override preservation, failed/stale status and automatic
recovery, with no console errors. Check-only verification kept state, count-step
and durable manifest hashes unchanged. A private retry screenshot and logs are
retained outside the repository.

Deployment and merge await owner approval. After approval, verify
read-only access, deploy the approved application helpers, then enable the approved
workflow by merging. Run the narrow manual automation check and record the live
result without starting the four library refreshes. Record completion of this
roadmap after that verification.

Rollback restores the previous application automation helpers, script and workflow.
This stops nightly count checks without altering shared policy, manual overrides,
routine state, canonical artifacts or the already released Flush Mode panel.
