# Review: DEVELOPING.md, TASKS.md, PLAN.md and the LDAP publisher change set

Reviewed at 2026-09-11 00:18 EDT against branch `initial-ldap-publisher` at `3b01c1f`
(`8d0c2a8` Initial port of the LDAP publisher, `fc014e1` Add Dockerfile, `3b01c1f` fixup
adding PLAN.md). `master` is at `14555fe` and still carries three unsquashed `fixup!`
commits. Working tree clean. Line numbers below refer to these files at `3b01c1f`.

The target moved while the review ran. It started against `3a9c6e4` with an empty index
(nothing was staged; the "staged" set was three unstaged edits plus untracked files).
During the review DEVELOPING.md was rewritten twice, mise.toml gained `ruff` and two tasks,
the whole change set was committed, history was rebased, and the Dockerfile's build break
(below) was fixed. Every finding was re-checked against the committed files, so what
follows describes HEAD, not the snapshot the review started from.

## Method

Direct verification, read-only (nothing in the repository was modified; Docker images were
built under throwaway tags and removed):

* `diff` of the four moved modules against `local/cis-publishers` at `c2662d3`.
* Fixture provenance (`cmp` against the `cis` copies) and RSA modulus of the JWK fixture
  against the PEM.
* Test suite on the project venv (CPython 3.14.7): `python -m unittest discover -s tests
  -t .` plain, with `-W error::DeprecationWarning`, and with `-X dev`.
* `docker build --target test .` and the runtime image: first on the reviewed working
  tree (failed, see M7 history), then on a patched copy, then on `fc014e1` as committed.
  Smoke checks: `publisher-ldap` with no environment, with a missing local file, the
  container with no command, `id`, imports inside the image, image inspect.
* Claims in PLAN.md §2, §5, §6, §8 and docs/publishers/ldap.md checked against
  `local/cis-publishers/serverless.yml`, its README, and the `cis` modules they cite.

Adversarial pass: 49 agents. Eight independent review lenses (documentation consistency,
port fidelity, code and tests on 3.14, guideline compliance, build and packaging, security
and operations, scope and process, test adequacy), a completeness critic that opened four
gap lenses (steady-state and removal transitions, HRIS follow-up footprint, uv-init
scaffolding, signing-key publication and rotation), deduplication, then two independent
verifiers per finding: one re-read the cited code and tried to refute the fact, the other
judged materiality against DEVELOPING.md and the disclosed "Preserved behaviour" lists.
83 raw findings, 67 after dedup, 62 confirmed, 4 judged already disclosed with no new
consequence, 1 refuted (overtaken by the commits made mid-review). Several findings had
their claims or line numbers corrected by the verifiers; the corrected versions are used
here.

## Verdict

The port itself is sound. The moved modules are byte-identical to upstream except for two
import lines, one reworded comment and the appended `cli()`. The 65 tests are real, pass on
3.14.7 and inside the image, and pin the quirks they claim to pin. The dependency set is
upstream's. The Dockerfile now builds and produces a 71 MB image running as uid 10001 with
the interpreter, the locked packages and the installed project only.

The problems are at the edges, and seven of them should be dealt with before TASKS.md
item 1 is ticked:

| # | Item | Artifact |
|---|------|----------|
| M1 | Tracked docs do not describe the repository the migration created; DEVELOPING.md still says the LDAP publisher lives in cis-publishers and deploys with Serverless | DEVELOPING.md, README.md |
| M2 | "Docker image on Kubernetes" is an unrecorded architecture decision that shapes the Dockerfile, the docs and the follow-up plan | PLAN.md §7, DEVELOPING.md |
| M3 | The documented run workflow puts the private signing key and client secret into shell history and a repo-root `.env` that is neither git- nor docker-ignored | docs, .gitignore, .dockerignore |
| M4 | A Change API rejection is counted as "synchronized" and the run exits 0; not documented as such, not pinned by any test | docs, tests |
| M5 | Two Change-API interactions missing from "Preserved behaviour": clearing groups never lands (202 noop, retried forever) and DN or posix-id changes are rejected and take the user's other changes down with them | docs |
| M6 | No steady-state test: every test starts from the null profile, so the code path the publisher runs every 30 minutes is never exercised end to end | tests |
| M7 | Dockerfile claims "no default command" but inherits `CMD ["python3"]`; a Job without `command` exits 0 doing nothing | Dockerfile |

PLAN.md §4.5's two open gates are now satisfied: `mise run test` is green on 3.14.7 and
`docker build --target test .` passes on `fc014e1`. Ticking item 1 is a judgement call
after the table above; nothing found changes how the migrated publisher behaves relative
to upstream.

## 1. What held up

Port fidelity

* `common/__init__.py` and `common/people.py` are byte-identical to upstream.
  `common/profile.py` differs only at line 10 (import). `ldap.py` differs at line 8
  (import), lines 119-122 (comment reworded, disclosed at PLAN.md:28-29) and lines
  193-211 (appended `cli()`). `main()`, `handle()`, `synchronize()`, `get_ldap_dump()`
  and the `__main__` block are unchanged.
* `cli()` matches the PLAN.md §3 sketch, and its three defaults are the literal constants
  in `local/cis-publishers/serverless.yml:51-52,56` (not stage-mapped, so "same value in
  every stage" is true; only `IAM_DISCOVERY_URL` and `LDAP_USER_ID_PREFIX` varied).
* Upstream had no tests, no package side effects, and `requirements.txt` was exactly
  unpinned `boto3`, `python-jose[cryptography]`, `requests`.
* `unused_create_profile.py` is the only reader of `LDAP_USER_ID_PREFIX`;
  `CIS_NULL_PROFILE_URL` is read only at `people.py:71` on the no-identifier path.

Fixtures and signing

* `fake-publisher-key_0.{priv,pub}.pem` and `user_profile_null.json` are byte-identical to
  the `cis` copies. The JWK's modulus equals the PEM's; it has `use=sig` and a v4-shaped
  `kid`, matching the upstream recipe. The key pair is already public in `mozilla-iam/cis`.
* `jws.sign` is deterministic (RS256 PKCS#1 v1.5 over `json.dumps(payload,
  separators=(",", ":"))`), the JWS header carries no `kid`, and the Change API verifier
  tries every key under `api.publishers_jwks.ldap.keys`, so overlap rotation is safe.
* The bootstrap POST the integration test produces would be accepted upstream: null
  previous value plus new value selects the `create` rule, and `ldap` is in every
  relevant create list.

Tests

* 65 tests = 27 (`test_ldap`) + 11 (`test_people`) + 23 (`test_profile`) + 4
  (integration). Green on 3.14.7, with deprecation warnings as errors, and under `-X dev`.
  Green inside the Docker test stage. `EntrypointTests` does not skip in either place.
* Mocking is at the two client boundaries only, with `unittest.mock`; no network, no
  moto/responses, no `assertLogs`. `route_requests` raises on any unrouted URL. Test env
  is assigned, not `setdefault`-ed, so a developer's real key cannot leak in.
* Pinned quirks confirmed by reading and, where marked, by mutation: xz decided by env not
  argument; S3 preferred when bucket and key are set; worker exception aborts `main()`;
  `handle()` discards the error dict; phone numbers never written; untouched attributes
  stay unsigned with `display: null`; `synchronize()` returns `True` unconditionally after
  publish (mutant `return p.publish(...)` fails two tests); dropping any of pgp, ssh,
  `access_information.ldap` or `identities.*` fails both unit and integration tests.
* `reset_module_state` covers every mutable module global. Autospec on `ldap.Profile`
  enforces the real method signatures. `Mock(spec=requests.Response)` is adequate because
  `people.py` only calls `.json()`.
* The `SignableAttribute.__contains__` quirk is real (`"signature" in attr` raises
  `TypeError`) and unreachable: the only `in` on a `SignableAttribute` is `"value" in v` at
  `profile.py:133`, which takes the early return.

Build and packaging

* uv.lock: 18 packages added, all from PyPI with sdist and wheel hashes; `requires-dist`
  matches pyproject.toml; the venv matches the lock exactly. cp314 wheels exist for
  `cffi`/`cryptography`, so the slim image needs no compiler.
* Dockerfile two-phase sync is correct; the test stage imports the installed wheel, not
  `src/` (`/app` is on `sys.path`, `/app/src` is not); the runtime symlink
  `.venv/bin/python -> /usr/local/bin/python3.14` resolves; nothing writes into the
  root-owned `/app`. Version pins are consistent across Dockerfile, mise.toml, mise.lock
  and `build-system`. `.dockerignore`'s header matches the five `COPY` lines.
* `local/.gitignore` contains `*`, as DEVELOPING.md suggests, so `local/` is hidden for
  teammates without the global ignore rule too.

Documentation accuracy (the parts that are right)

* PLAN.md §2 line-count table, the `c2662d3` commit, the older `cis` LDAP publisher's
  bucket, fixture format, `reservedConcurrency: 1` and request-level mocks, `hris.py` at
  523 lines, `cis_crypto` signing with `jws.sign(..., "RS256")`, `cis_publisher.publisher`
  using `requests`, the HRIS location discrepancy: all confirmed.
* PLAN.md §6 and docs "Configuration": every env var, SSM path, stage URL, the schedule,
  `maximumRetryAttempts: 0`, `memorySize: 2048` and its comment, `timeout: 900`, the IAM
  statements and the never-implemented `lastRun*` grant match `serverless.yml`.
* docs "Preserved behaviour": each bullet corresponds to code as described. The `DRY_RUN`
  wording ("set to anything") is more accurate than upstream's own README.
* docs "Signing key" script is the upstream README's verbatim; `api.publishers_jwks.ldap`
  exists in both the dev and prod well-known templates, one 4096-bit key each, with `n`
  matching the `x5c` certificate.

DEVELOPING.md compliance, guideline by guideline (HEAD numbering)

| Guideline | Result |
|-----------|--------|
| Dev 1 tests moved / written | Pass. Upstream had none; 61 unit + 4 integration written. |
| Dev 2, 3 unit and integration tests | Pass. |
| Dev 4 behaviour unchanged | Pass for the moved modules. `cli()` is additive (new entrypoint only) and documented. See D1 for the Lambda-to-process model change. |
| Dev 5 stdlib over deps | Pass with the trade-off argued in PLAN.md §7.1: `requests` to `urllib` is a rewrite, RS256 JWS and SigV4 have no stdlib option. Deps are upstream's. |
| Dev 6 human adds deps | Not verifiable from the tree. PLAN.md §4.0 has the executor running `uv add` after ticked approvals; the rule was written after execution. See P2. |
| Dev 7 don't port unneeded code | Tension. `unused_create_profile.py` dropped; `handle()`, `__main__` and `Profile.is_empty()` kept. See C1. |
| Dev 8 quirks documented and pinned | Partial. "Preserved behaviour" exists; M4, M5, D6, D8, D9 are quirks it misses. |
| Test 1-4 self-contained, in-process, `unittest.mock` | Pass. Only real non-mock object is `botocore.exceptions.ClientError` from a project dependency. |
| Test 5, 8 no log assertions | Pass. Consequence: `main()`'s summary is untested (T3). |
| Test 6 don't test dependencies | Pass. `jws.verify` is used as an oracle on what our code signed. |
| Test 7 one function, neighbours patched | Strained by `ProfileTests` and `test_accepts_a_profile_dict`, which run three classes plus real signing (T7). |
| Test 9 integration = entrypoint with only external boundaries mocked | Pass. `cli()` is driven with `people.requests` and `ldap.boto3` patched. |

## 2. Fix before ticking TASKS.md item 1

### M1. Tracked docs do not describe the repository the migration created

* Where: DEVELOPING.md:126-132, DEVELOPING.md:46-48, README.md, PLAN.md:355-356,
  PLAN.md:432.
* What: DEVELOPING.md's cis-publishers section still reads "This is also deployed using
  Serverless. Right now the only publisher using this is the LDAP publisher." Nothing in
  DEVELOPING.md, AGENTS.md, README.md or TASKS.md says where migrated code lives
  (`src/mono_cis/publishers/`), where per-project docs live (`docs/publishers/`), that
  there is one Docker image whose command selects the project, or how tests are laid out.
  New guideline 8 requires "each project's doc" to have a Preserved behaviour section
  without saying where project docs are. All of that is documented only in
  docs/publishers/ldap.md (which nothing points at), the Dockerfile header and PLAN.md.
  PLAN.md left the pointer as an optional, approval-gated item.
* Why: DEVELOPING.md is the entry point it tells contributors to start from, and right
  after the migration it misdescribes where the first consolidated project lives and how
  it deploys. Task 2 is meant to follow the same layout.
* Fix: rewrite DEVELOPING.md:126-132 ("Migrated to `src/mono_cis/publishers/ldap.py`; see
  `docs/publishers/ldap.md`; upstream remains for reference"), add a short "This
  repository" subsection listing the layout convention (`publishers/<name>.py`,
  `publisher-<name>` script, `docs/publishers/<name>.md`, `tests/{unit,integration}/publishers`,
  one image), and point README.md at it. Treat this as required, not optional.

### M2. The deployment target is an unrecorded decision

* Where: PLAN.md:56-57, PLAN.md:425-432, Dockerfile:3-5, docs/publishers/ldap.md:23-24,
  53-58, 108-118, PLAN.md:445-447.
* What: PLAN.md §1 states "deployment moves to a Docker image on Kubernetes" as a given.
  No tracked document names a runtime target for this repo; DEVELOPING.md's only
  Kubernetes mention is a past GCP experiment. §7 "Decisions needed" lists three items and
  omits this one. The assumption shapes the Dockerfile header, the docs' "Provided by the
  platform" (IRSA sets `AWS_REGION`) and Kubernetes sections, and the HRIS follow-up note.
  It is plausible (iam-infra runs EKS; `cis` has a helm chart) but a reviewer cannot tell
  whether it is the team's intent or the executor's guess.
* Why: a repo-wide infrastructure decision was taken inside a single-publisher task with
  no approval trail. If the team stays on Lambda (container-image Lambda or Serverless),
  the docs' platform contract is wrong. The Dockerfile and `cli()` themselves are
  runtime-agnostic and would survive either answer.
* Fix: add "deployment target" as decision 4 in PLAN.md §7 and answer it. Record the
  answer once in DEVELOPING.md (a Deployment subsection or a short ADR under `docs/`) so
  the HRIS migration does not re-derive it. Until then label the Kubernetes sections of
  ldap.md as an example mapping.

### M3. Documented run workflow leaks secrets into shell history and an unignored `.env`

* Where: docs/publishers/ldap.md:73, :87, Dockerfile:9, .gitignore (10 lines, no `.env`),
  .dockerignore:3-8.
* What: line 73 shows `export OAUTH_CLIENT_ID=… OAUTH_CLIENT_SECRET=…
  PUBLISHER_SIGNING_KEY='{"kty":"RSA",…}'` in an interactive shell; line 87 and the
  Dockerfile header say `docker run --rm --env-file .env`. `git check-ignore .env` matches
  nothing, and `.dockerignore` does not exclude it, so a repo-root `.env` holding the RSA
  private JWK and the Auth0 secret would be committed by `git add -A` and shipped in every
  build context. Upstream operators never handled these values; Serverless resolved them
  from SSM at deploy time.
* Why: this is new exposure created by the migration docs, and the asset is a publisher
  signing key.
* Fix: add `.env` and `.env.*` to both ignore files (or point the example at a file
  outside the repo). Rewrite the shell example to read from SSM without touching history,
  for example `export PUBLISHER_SIGNING_KEY="$(aws ssm get-parameter --with-decryption
  --name /iam/cis-publishers/<stage>/ldap_signing_key --query Parameter.Value --output
  text)"`. Note that env values are visible in `docker inspect` and `/proc/<pid>/environ`.

### M4. Change API rejections are reported as success and exit 0

* Where: `people.py:121-129`, `profile.py:226`, `ldap.py:126-128`, `ldap.py:211`,
  docs/publishers/ldap.md:90-91, :187-189, tests/support.py:135,
  tests/unit/publishers/test_people.py:171-176.
* What (reproduced end to end through `cli()` with a 400 `invalid_profile` answer):
  `change_profile()` logs an ERROR and returns `False`; `Profile.publish()` discards the
  return value; `synchronize()` returns `True`; the summary prints "1 accounts
  synchronized … 0 accounts failed" and `cli()` returns 0. The docs' "Exit status"
  paragraph presents 0 as "the run completed" and the Preserved behaviour bullet only says
  "failed to synchronize" is unreachable. `route_requests` accepts a `change_response`
  parameter that no test passes with a non-200 value; the only failure test stops at
  `change_profile`'s return value.
* Why: for a CronJob the exit status is the success signal. A rotated key, a client that
  lost its scope, or a schema rejection produces a green job that writes nothing, for as
  long as nobody reads the logs. DEVELOPING.md's General guidelines say crashes are the
  alerting signal; here nothing crashes. Guideline 8 asks quirks to be pinned "where
  practical"; the helper already exists, so it is practical, and a future "fix" would pass
  all 65 tests today.
* Fix (code unchanged, guideline 4): state in "Exit status" and "Preserved behaviour" that
  Change API rejections do not change the exit code and are counted as synchronized; tell
  operators to alert on `Unable to update LDAP profile` (or on the absence of Change API
  POSTs). Add an integration test with `change_response={"status_code": 400, "code":
  "invalid_profile", "description": "bad signature"}` asserting exit code 0 and exactly one
  POST per active user. Whether the exit-code contract should eventually change is a
  guideline 4 decision (see §4).

### M5. Two Change-API interactions are missing from "Preserved behaviour"

Both are upstream behaviour (guideline 4 says keep them) and both were traced through the
`cis` change service and `cis_profile` code in `local/`.

M5a. Clearing groups never lands and is retried every run.

* Where: `ldap.py:82`, `profile.py:286`, `local/cis/python-modules/cis_profile/cis_profile/profile.py:170`,
  `local/cis/python-modules/cis_change_service/cis_change_service/profile.py:132-148, 252-267`.
* What: a dump entry without `groups` assigns `None` over a populated
  `access_information.ldap`. The guard at `profile.py:286` only short-circuits when the
  stored value is `None`, so the attribute is set to `values: null`, re-signed, notified
  and POSTed. The Change API's merge skips any incoming attribute whose value is `None`,
  finds no difference, and answers `{"status_code": 202, "condition": "noop"}`.
  `change_profile` treats non-200 as failure (logged, ignored, see M4). The vault still
  holds the old groups, so the same POST repeats every 30 minutes forever, and the account
  is counted as synchronized. Related asymmetry (D8): clearing all SSH or PGP keys does
  propagate (`values: {}`), and an explicit `groups: []` is signed as a JSON array, which
  the schema forbids but the Change API does not validate.

M5b. `identities.mozilla_ldap_id` / `mozilla_posix_id` can be set once and never changed.

* Where: `local/cis/well-known-endpoint/tpl/mozilla-iam-publisher-rules` (create lists
  `ldap`; `update.identities` is the single string `"mozilliansorg"`),
  `local/cis/python-modules/cis_profile/cis_profile/profile.py:439-509`, `ldap.py:84-88`.
* What: `verify_can_publish` indexes the string `"mozilliansorg"` by attribute name, hits
  the `except TypeError` fallback, and `allowed_updators` becomes `"mozilliansorg"`. Once
  a DN or posix uid is set, any different value takes the update branch and is rejected
  with 403 `invalid_publisher`. Because publishers are verified on the merged profile,
  that rejection discards the user's group and key changes in the same POST, every run.
  The doc's "identities.mozilla_* are written" is true only for the first write. Also
  (D9): `metadata.display` is written only when `None`, so a later o=net to o=com move
  never changes it.
* Why: group removal is the security-relevant direction of this publisher and the run
  summary is untruthful about it; a DN rename freezes that user's LDAP data in CIS.
  Guideline 8 requires these in Preserved behaviour; neither ldap.md nor PLAN.md §5
  mentions removal, rejections, or what "synchronized" counts.
* Fix: add both as Preserved behaviour bullets (wording proposals in T2/D8). Pin M5a at
  unit level (populated profile, assign `None`, publish, assert the POSTed
  `access_information.ldap.values is None` with a fresh signature). Do not change the
  code.

### M6. No steady-state test

* Where: tests/support.py:93-103, tests/unit/publishers/test_profile.py:183-184, :236-241,
  tests/integration/publishers/test_ldap_publisher.py:59-61, `profile.py:127-129`, `:274-287`.
* What: `cis_profile()` fills six identifying scalars of the null profile, and both
  `ProfileTests` and `LdapPublisherRunTests` build every retrieved profile from it. So
  every signed attribute in every test starts from `value(s): null`, `display: null`,
  `created: 1970`. The production steady state (a profile the previous run populated; one
  value differs or none does) is exercised nowhere: the `_walk` sync branch comparing
  populated values, the list-to-dict equality short-circuit, selective re-signing (only the
  changed attribute gets a new signature and `last_modified`), and display preservation
  are pinned only at attribute level with mocks. `test_publish_skips_when_nothing_changed`
  proves only that assigning nothing to a null profile produces no POST.
* Why: the publisher runs every 30 minutes against populated profiles; a regression that
  re-signs everything on every run (flooding the Change API) or wipes `display` would pass
  the suite.
* Fix: add a `populated_profile(email, ldap_entry, display="staff")` helper to
  tests/support.py that fills pgp/ssh/`access_information.ldap`/`identities.mozilla_*`
  exactly as `synchronize()` would, with fixed timestamps and a placeholder signature.
  Then: (1) unchanged populated profile, same LDAP data, publish, assert no POST and
  signature bytes unchanged; (2) one SSH key changed, assert exactly that attribute is
  re-signed and every other signature is byte-identical; (3) the M5a clearing case. Keep
  these sequential (unit level) to stay clear of the `DISPLAY_LEVEL` race.

### M7. Dockerfile claims no default command but inherits `CMD ["python3"]`

* Where: Dockerfile:3-5, :60-61, `python:3.14-slim` base image.
* What (verified on the built `fc014e1` image): `docker image inspect` reports
  `CMD=[python3]`, inherited from the base image; `docker run --rm <image>` with no
  command exits 0 immediately (the REPL reads EOF). The header says "the image has no
  default command" and line 60 says "No CMD on purpose".
* Why: a CronJob whose `command` is missing or misspelled at the pod level starts, does
  nothing, and reports success every 30 minutes. Combined with M4 there is then no signal
  at all.
* Fix: set an explicit failing default, for example `CMD ["sh", "-c", "echo 'mono-cis:
  specify a console script, e.g. publisher-ldap' >&2; exit 64"]`, or use `ENTRYPOINT`
  with the project name as the argument. Correct the header comment either way.

History of this item: the Dockerfile as first reviewed did not build at all. BuildKit
rejects `COPY --from=ghcr.io/astral-sh/uv:${UV_VERSION}` with "variable expansion is not
supported for --from". `fc014e1` fixed it with a named `uv` stage; that version builds,
its test stage runs all 65 tests green, `publisher-ldap` with no env exits 1, and the
runtime image is 71.5 MB running as `uid=10001(app)`.

## 3. Minor and nit findings, by artifact

Severity tags: [minor] fix soon; [nit] cosmetic. Items marked "probe" were reproduced by
executing code, not just by reading it.

### DEVELOPING.md

* [minor] **Dangling "See Workflow" reference.** Line 27 says "See Workflow for more
  information"; no Workflow heading exists in any tracked doc. Add the section (plan,
  approvals, execute, tests, tick TASKS.md, commit set) or delete the sentence.
* [minor] **AGENTS.md is a stale, weaker copy.** AGENTS.md:31-43 carries dev guidelines
  1-4 and test guidelines 1-3 only, has never matched DEVELOPING.md (they differed in the
  commit that added both), and was never touched again. An agent reading it by convention
  is not bound by the dependency-approval, don't-port, no-log-assertions or
  preserved-behaviour rules this task relies on. Replace its body with "Read
  DEVELOPING.md" or make it a symlink; do not keep two hand-maintained copies.
* [nit] **Duplicated rules.** Test guideline 8 (lines 60-61) restates test guideline 5
  (line 57); test guideline 4 (line 56) restates the parenthetical of dev guideline 5
  (lines 40-41). Merge when the list is next renumbered, together with the PLAN.md
  citation fix below.
* [nit] **Rubric ambiguities that this review had to guess at.** Guideline 4 does not
  scope "behaviour" (is `cli()`'s exit code for a new entrypoint a change?). Guideline 7's
  example (Postgres) leaves the unit undefined: file, module or function (is porting the
  unused `Profile.is_empty()` a violation?). The General guidelines' "let exceptions
  bubble up" reads as contradicting guideline 4 for the bare `except:` in `main()` until
  the reader finds guideline 8. One sentence each would settle them: scope "behaviour" to
  what reaches external systems plus documented quirks; say guideline 7 applies per file
  (or per function); cross-reference guideline 8 from the catch-all paragraph.
* [minor] **Guideline 6 and the change set.** Guideline 6 ("Dependencies must be reviewed
  and added by a human… never edit dependencies in pyproject.toml directly") postdates the
  execution recorded in PLAN.md §4.0, where the executor ran `uv add` after ticked
  approvals. The tree cannot show who ran it. Record it in PLAN.md (or re-run the three
  `uv add`s by hand in a separate human-authored commit) so the first migration is not
  the first exception to the rule. Related: `mise run test` uses plain `uv run`, which can
  rewrite uv.lock as a side effect (see Config).

### TASKS.md

* [minor] **Item 2 points at the wrong repository.** TASKS.md:6 says the HRIS publisher is
  in `cis-publishers`; it is `cis/python-modules/cis_publisher/cis_publisher/hris.py`
  (523 lines). cis-publishers' own README says "Still in CIS"; DEVELOPING.md:120-124
  agrees; PLAN.md:102-104 recorded the error and nobody fixed the two-line file. Item 1 is
  unticked by design (gated on the runs that have now happened).
* [minor] **Item 2 is not a copy-and-add-`cli()` task.** `hris.py:100-104` always calls
  `fan_out()` when invoked on a schedule, which chunks user ids and re-invokes the Lambda
  itself via `boto3.client("lambda").invoke(FunctionName=self.context.function_name,
  InvocationType="Event")`; the in-process path needs an explicit user-id list from a
  Lambda event. A CronJob has no `context.function_name` and nothing to invoke, so task 2
  opens with a guideline 4 decision (port and change the fan-out semantics; re-implement
  on this repo's `publishers/common`; or leave HRIS on Lambda). Add a note to item 2.

### PLAN.md

Now committed via the `fixup!` at HEAD, so these are corrections to make before the
autosquash, or reasons not to squash it in (see §4).

* [minor] **Wrong guideline numbers.** PLAN.md:55 justifies the plan's only scope
  exclusion with "guideline 6"; do-not-port was 6 when the plan was drafted, became 7 in
  `3a9c6e4`, and under HEAD guideline 6 is the dependency-approval rule. PLAN.md:11-14
  describes the rubric as it stood mid-way (stdlib = dev 6, test guidelines 4-6 added) and
  omits dev 6 and 8, test 7-9, `mise run test` and the General guidelines. Fix the numbers
  or cite guidelines by text.
* [minor] **Self-contradictory approval and execution record.** §4.0 (171-178) ticks
  "Approve dev dep pytest" and "`uv add --dev pytest`" although the Deviations paragraph
  (22-23) says no pytest was added and none is in pyproject.toml, uv.lock or the venv.
  §4.3 (339-343) is ticked but describes `uv sync --frozen` and `RUN uv run pytest`; the
  shipped Dockerfile uses `--locked`, a two-phase sync and `python -m unittest` (better
  than the plan, but the record says otherwise). §7.1 (427-428) still lists dependency
  approval as needed although §4.0 records it as given. No approver is named anywhere.
  Untick or strike the pytest lines, rewrite §4.3 to match Dockerfile:32-43, delete §7.1,
  record who approved and who ran `uv add` and when.
* [minor] **Status and counts.** "Status: executed" (6) sits above open boxes at 345, 355,
  360, 363 and three open decisions; "~30 unit tests and 3 integration tests" (44) is
  stale (61 and 4). "No commits" at 178 and 363 is now false. The headline "65 tests pass"
  (7) rests on a Python 3.10 sandbox run the project excludes (`requires-python >=3.14`,
  disclosed at 30-35); the 3.14.7 result (65 OK, also with `-W error` and `-X dev`) and
  the passing `docker build --target test .` on `fc014e1` should be recorded and boxes
  345 and 360 ticked.
* [minor] **§7.2 understates the cost of reversing the S3 defaults.** The bucket/key
  defaults (429-431) are presented as freely reversible, but they are load-bearing for
  `CliTests` (test_ldap.py:269-307), the integration `setUp` and assertions
  (test_ldap_publisher.py:51-52, 65, 142-147), docs "Defaulted by publisher-ldap" and §6.
  State the cost, get a yes/no, delete the item.
* [minor] **§8 misstates how the `cis` HRIS tests mock.** 442-445 says `test_hris.py` and
  `test_publisher.py` already patch `Publish._request_get/_request_post`. Only
  `test_publisher.py` and `test_ldap.py` do (and they also patch `secret.Manager.secret`
  and `AuthZero.exchange_for_access_token`); `test_hris.py`'s sole mock is
  `Publish.get_cis_user`, one layer above the request boundary, and `hris.py` never calls
  `get_cis_user`, so that mock is dead. The upstream tests are pytest-style classes with
  bare asserts (unittest discovery collects none of them), construct a real
  `HRISPublisher()` (boto3 SSM client), reach the network through `cis_profile.User()`,
  and `test_secret.py` imports moto. Moving them is a conversion, not a move.
* [minor] **§8 "the approved dep set covers all of them" is false.** 448-451 holds only
  for the `jws.sign` call. A verbatim HRIS move needs `everett[ini]` (three upstream
  `common.py` modules), `jsonschema` (`cis_profile/profile.py:24`, used by `validate()`),
  `PyYAML` (`cis_crypto/operation.py:4`), and, unless the upstream `__init__.py` files are
  trimmed, `faker` and `auth0-python`. None is in the venv. Under guideline 6 task 2
  therefore opens with proposed `uv add` commands and a wait; the plan says the opposite.
* [minor] **§8 names one of three colliding `common` modules.** `cis_publisher.common`
  and `cis_crypto.common` are byte-identical everett shims; `cis_profile.common` adds
  `DotDict`, `WellKnown`, `MozillaDataClassification`, `DisplayLevel`. `publisher.py`
  imports two of them. The proposed `publishers/config.py` fits only the everett shim;
  `DotDict`/`WellKnown` need a home that does not shadow `publishers/common/`.
* [minor] **§8 mischaracterises HRIS configuration.** 445-447 says HRIS "pulls config from
  SSM + everett INI at runtime, which will need to become env vars". Non-secret config is
  already `CIS_*` env vars via everett's `ConfigOSEnv` (`serverless.yml:59-72`). What is
  not env is the secrets and the signing key, fetched from SSM at runtime by
  `secret.Manager` (which retries forever) and `cis_crypto.secret` (30 retries then
  `AttributeError`). The LDAP "env-simplification" was faithful only because Serverless
  had already resolved SSM into env vars; for HRIS it is a code change. Also: HRIS takes
  API URLs from env while the LDAP publisher takes them from discovery, a fork any later
  convergence must resolve.
* [nit] **§8 omits `cis_profile.User`'s runtime surface.** Every `User()` constructs
  `WellKnown` and calls `get_well_known()`; `validate()` re-fetches the schema per call;
  `verify_all_publishers` re-fetches the rules per attribute; the loaders fall back to
  four bundled data files and write a cache under `/tmp` (`common.py:127`). A
  `readOnlyRootFilesystem` CronJob would break it. Task 2 plan material; one sentence now.
* [nit] **Three shipped test comments cite PLAN.md sections** (tests/support.py:8, :51;
  test_ldap_publisher.py:7). They resolve today; the equivalent content lives in
  docs/publishers/ldap.md "Tests" and "Configuration > Required". Point there, since
  tests/support.py is the file the HRIS migration will copy.

### docs/publishers/ldap.md

* [minor] **"S3 wins" is wrong for bucket without key** (probe). With
  `LDAP_CACHE_S3_BUCKET` set, `LDAP_CACHE_FILENAME` set and `LDAP_CACHE_S3_KEY` unset,
  `cli()` (ldap.py:207-209) applies neither default, `main()` takes the S3 branch,
  `environ["LDAP_CACHE_S3_KEY"]` raises `KeyError` inside the bare except, and the run
  exits 1 with "Invalid LDAP export" having consulted neither source. Line 51's "(If a
  bucket is set explicitly, S3 wins.)" does not hold. This combination could not occur
  upstream (serverless.yml always set both). Either default the key whenever a bucket is
  set (touching only `cli()`), or reword line 51, and add a `CliTests` case for
  bucket+filename with and without key.
* [minor] **`CIS_NULL_PROFILE_URL` rationale is wrong.** Lines 62-64 attribute both
  dropped variables to the unported creation code. `LDAP_USER_ID_PREFIX`: yes.
  `CIS_NULL_PROFILE_URL` is read at `people.py:71` inside the ported, unit-tested
  `get_profile()` no-identifier path, reachable via `Profile()` with no identifier
  (`profile.py:76`). PLAN.md:87-88 has it right. Matters for the HRIS port, which does use
  skeleton profiles.
* [minor] **DRY_RUN wording and pin** (probe). Any present value, including `""`,
  `"false"`, `"0"`, enables dry run (`profile.py:225` checks `is None`), nothing in the
  output says a run was dry, and the summary is identical. Line 50 says "set to anything",
  which is correct, but Kubernetes env values are strings and `"false"` is a common
  default. Say "present at all, with any value including `false`, `0` or empty; omit to
  disable; output is identical to a real run". Turn `test_publish_respects_dry_run_environment`
  into subTests over `("True", "", "false", "0")`; only `"True"` is tested.
* [minor] **Env-file quoting trap.** Line 73 shows the JWK shell-quoted; line 87 uses
  `--env-file .env`, where quotes are literal, so a `.env` line copied from the shell
  example makes `json.loads` fail at import with a bare `JSONDecodeError` before any log
  line. One sentence under "With Docker": env-file values are taken verbatim, no quotes.
* [minor] **Kubernetes mapping has errors and omissions.** Lines 55-56 say IRSA / pod
  identity sets `AWS_REGION` and `AWS_DEFAULT_REGION`; the IRSA webhook injects
  `AWS_REGION`/`AWS_DEFAULT_REGION`/`AWS_ROLE_ARN`/`AWS_WEB_IDENTITY_TOKEN_FILE`, but EKS
  Pod Identity injects only `AWS_CONTAINER_CREDENTIALS_FULL_URI` and the auth token file,
  so region must be set explicitly there (boto3 1.43.92 with no region falls back to
  `us-east-1` and the global S3 endpoint). The table (112-118) omits `restartPolicy:
  Never` (with `OnFailure` the kubelet restarts in-pod before `backoffLimit: 0` counts),
  `startingDeadlineSeconds`, that `activeDeadlineSeconds` counts scheduling and image
  pull, and that `memorySize: 2048` was a hard cap that also scaled CPU (so a limit plus a
  CPU request, not just a request). `s3:ListBucket` is not needed (the code only calls
  `get_object`; ListBucket only turns a 404 into a 403, both swallowed).
* [minor] **Logging content undisclosed.** Line 120 says only "Logging goes to stderr".
  `profile.py:220` logs, at INFO, `user_id`, `primary_email` and the full attribute diff
  for every changed attribute. Because SSH/PGP attributes are dicts with string values,
  `_is_list()` is false and they take the scalar `old --> new` branch, printing whole SSH
  public keys with `user@host` comments and PGP fingerprints; groups print as `+group`
  `-group`; the summary lists every mismatched email. Upstream wrote the same to
  CloudWatch; the new sink is whatever the cluster ships stderr to. Add a "Logging"
  paragraph so retention and access can be set; lowering the line to DEBUG is a guideline 4
  decision.
* [minor] **No HTTP timeouts or retries** (six `requests.get/post` calls, no `timeout=`,
  no `Session`). A stalled socket in any of the 32 workers holds `executor.shutdown(wait=True)`
  until the Job deadline kills the pod with SIGTERM, which Python does not handle, so no
  summary is logged. Line 116 maps `timeout: 900` to `activeDeadlineSeconds: 900` without
  saying it is the only bound and is mandatory. Add to Preserved behaviour.
* [minor] **Intro overstates writes.** Lines 5-7 say attributes are written "for every
  active profile"; `publish()` POSTs only when something changed (`profile.py:225-228`),
  and "N accounts synchronized" counts active accounts processed, not POSTs. Reword, and
  add a Preserved behaviour bullet on what the count means.
* [minor] **Signing key: only the private half is documented.** Lines 138-142 name the
  well-known location but not the public entry shape (`{alg, kty, use, kid, n, e, x5c}`),
  that `cis/well-known-endpoint/pem_to_jwks.py` is Python 2 only (fails under the repo venv
  with a str/bytes `TypeError`), that the deployed entries use the fixed kid `LDAPKeyId`
  which the verifier never compares to the private JWK's uuid kid, and that reusing the
  existing SSM JWK verbatim needs no well-known change. Add a "Public half" paragraph
  pointing at `tpl/{dev,prod}.mozilla-iam` and the Makefile, and a three-line check that
  the private JWK's `n`/`e` appear under `api.publishers_jwks.ldap.keys` at
  `IAM_DISCOVERY_URL`.
* [minor] **No rotation note.** A key absent from the well-known makes every POST fail
  with 403 `invalid_signature` (`cis_change_service/profile.py:318-331`, signatures
  enforced in all stages) while the run reports success and exits 0 (M4). One "Rotating
  the key" paragraph: append the new public entry (verifier tries all keys, ignores
  `kid`), deploy and wait for the Change API to pick it up, then swap the Secret and check
  the logs for `Unable to update`.
* [minor] **Scanner note.** `python-jose` depends unconditionally on `ecdsa` and `rsa`
  even with the `[cryptography]` extra; `ecdsa` 0.19.2 carries CVE-2024-23342 (Minerva,
  unfixed by design). RS256 here goes through `CryptographyRSAKey` and neither `ecdsa` nor
  `rsa` is imported at runtime, but both ship in the image and Trivy/Grype will report an
  unfixable High. Write the acceptance down (docs or a `.trivyignore`). `python-jose`
  3.5.0 postdates the 3.4.0 fixes for CVE-2024-33663/33664.
* [nit] **Exit-status paragraph is not exhaustive** (probe). A propagating worker
  exception, or `EnvironmentError` from a missing `IAM_DISCOVERY_URL`, also exits 1 with a
  traceback and no summary; `LDAP_CACHE_S3_BUCKET=""` survives `setdefault` and exits 1
  too. One added sentence.
* [nit] **"Unchanged apart from import paths"** (lines 11-12) understates the diff: one
  reworded comment and the appended `cli()`. PLAN.md:28-29 discloses the comment.
* [nit] **"Checked against the real signatures"** (152-155, also tests/support.py:10-11
  and PLAN.md:197-199) overclaims for S3: autospec on the `boto3` module specs only
  `boto3.client(*args, **kwargs)`; the returned client is a bare `MagicMock`, so
  `get_object("garbage", 1, 2, nonsense=True)` is accepted (probe). The explicit
  `assert_called_once_with(Bucket=, Key=)` assertions give equivalent protection. Reword.
* [nit] **"Single instance"** (line 19) is not a setting cis-publishers had; only the
  older `cis` publisher had `reservedConcurrency: 1` (line 115 already says so). The table
  pairs `concurrencyPolicy: Forbid` with `maximumRetryAttempts: 0`, which maps only to
  `backoffLimit: 0`; Forbid is a new (sensible) choice.
* [nit] **`display` is fixed at first write.** `profile.py:305` writes `metadata.display`
  only when `None`; a later DN move never changes it, and CIS would reject an LDAP-signed
  display-only change on `identities.*` anyway. The display bullet (195-197) reads as if
  the level is applied per publish.
* [nit] **Where the source PEM lives is unknowable from any clone** and irrelevant (the
  JWK is self-sufficient); line 125's "generated from the PEM private key" invites a hunt.
  Half a sentence: the JWK in SSM is the only artefact needed.

### Code (`src/`)

* [minor] **`cli()` key default** — see the "S3 wins" item above; the one-line fix is in
  `cli()`, `main()` unchanged.
* [minor] **Dead upstream code ported and tested.** `handle()` (ldap.py:19-22, upstream's
  only caller was `serverless.yml:45`), the `__main__` block (214-215) and
  `Profile.is_empty()` (profile.py:163-208, unused upstream too, with a TODO) have no
  caller under the new entrypoint; `HandleTests` spends two tests on the Lambda shim. The
  plan never states the rule it applied (guideline 7 per file; dead functions inside a
  ported file kept so the diff stays import-only). Either record that rule in PLAN.md §1
  and DEVELOPING.md, or drop them and note the deletion. Keeping `handle()` is defensible
  while M2 is open.
* [minor] **uv-init scaffolding ships.** `mono-cis = "mono_cis:main"` (pyproject.toml:17)
  is the hello-world stub, installed as a console script in the runtime image, directly
  above the comment "One entrypoint per project sharing this codebase". A Job whose
  command is mistakenly the image name would print "Hello from mono-cis!" and exit 0 every
  30 minutes. Delete the script and the body of `src/mono_cis/__init__.py`; optionally
  extend `EntrypointTests` to assert the distribution's console scripts are exactly
  `{"publisher-ldap"}`.

### Tests

* [minor] **Import-order dependency is unenforced** (probe). Every test module relies on
  `from tests import support` preceding any `mono_cis` import because `profile.py` parses
  the key at import. `ruff check --select I --diff tests` would move the `mono_cis`
  imports above it in all four modules; importing `profile` first with the key unset gives
  11 `RuntimeError: Unable to load signing key` in `test_profile`. Ruff's default F401
  already flags the bare `from tests import support` as unused in all four files. Move the
  six `os.environ` assignments (support.py:54-59) into the existing empty
  `tests/__init__.py`, which both runners import first, then drop the ordering trick.
* [minor] **`main()`'s classification and summary have zero regression coverage**
  (mutation-confirmed). Swapping the `True`/`False` branches, deleting the classification,
  or deleting the summary log all pass 65/65. `test_synchronizes_every_user_from_a_local_dump`
  feeds `side_effect=[True, False, False]` and asserts nothing about it. This is a direct
  consequence of test guidelines 5/8 plus `main()` returning `None`, and the plan does not
  disclose the resulting untested surface, although the docs present the summary as the
  operator's output. Decide: record it as deliberately untested, or grant a narrow
  exception for the one place where the log line is the output (patch `ldap.logger.info`
  with autospec and assert the counts). Do not change `main()`.
* [minor] **`ProfileTests` aliases the profile under test** (probe). `SignableAttribute`
  shallow-copies, so signing writes `created`/`last_modified`/`display` into the same
  nested `metadata` dict as `self.retrieved`; the assertion `signed["first_name"] ==
  self.retrieved["first_name"]` (test_profile.py:234) compares a dict against itself and
  cannot fail for the mutant it exists to catch. The integration test does catch it
  (`response()` deep-copies). Use `side_effect=lambda *a, **k: cis_profile(EMAIL)` and
  compare against a fresh `cis_profile(EMAIL)["first_name"]`.
* [minor] **Person API error bodies abort the run; only `{}` is tested** (probe).
  `{"message": "Unauthorized"}` raises `KeyError('active')` at `profile.py:86`; `{"code":
  401, "message": "x"}` raises `ValueError` from `_walk`; both escape `synchronize()`'s
  except clauses and `main()` re-raises from `future.result()`. This is the most likely
  production failure (expired token, gateway error) and is pinned only via a mocked
  `RuntimeError`. One `ProfileTests` case plus a Preserved behaviour bullet.
* [minor] **Malformed dump paths** (probe). An entry lacking `distinguished_name` or
  `user_id` raises `KeyError` at ldap.py:59/66, outside the `try`, and aborts the whole run;
  a `.xz` key over non-xz bytes yields 500/exit 1; `{}` yields an all-zero summary. The
  first deserves a three-line `SynchronizeTests` case pinning the dump's required-field
  contract; the others are optional.
* [minor] **`private` display level never signed for real.** Every unmocked
  `sign()`/`publish()` uses `staff`; the dn-to-level mapping is pinned only with `Profile`
  mocked, and the only o=net fixture account is routed to `{}`. Hard-coding `staff` inside
  `publish()` would pass all 65. Cheapest fix: a `ProfileTests` case calling
  `publish(display_level="private")` and asserting the POSTed `metadata.display`.
* [minor] **Import-time tolerance of a missing key is unpinned.** The docs claim "a missing
  key only fails at signing time"; tests set the key before any import and
  `test_signing_without_a_key_fails` only patches the module global. A stdlib
  `subprocess.run([sys.executable, "-c", "import mono_cis.publishers.common.profile as
  p; assert p.PUBLISHER_SIGNING_KEY is None"], env=<without the key>)` guards against a
  future eager validation.
* [minor] **Test guideline 7 strain.** `ProfileTests` (test_profile.py:180-273) and
  `test_accepts_a_profile_dict` patch only `get_profile`/`change_profile` and run
  `Profile.__init__`, `_walk`, `ProfileDict`, `SignableAttribute` and real `jws.sign` end
  to end. Well targeted, but not "one function with its neighbours patched". Soften the
  guideline to "one module, other modules patched" or accept the tension in writing.
* [nit] **Fixture private key labelled fake only by filename.** `fake-publisher-key_0.priv.pem`
  is read by nothing (support.py loads the JWK and the public PEM) and, with the JWK's `d`
  member, will trip secret scanners. Add a `tests/fixtures/README.md` (provenance, "never
  in `publishers_jwks`") and either delete the unused `.priv.pem` or document the
  regeneration command.
* [nit] **Loose assertions.** Timestamps are checked only with `startswith(year)`; the
  `%Y-%m-%dT%H:%M:%S.000Z` format at `profile.py:299` is unpinned (a regex or a patched
  `time.gmtime` fixes it). The integration token-count lower bound (`>= 1`) is correct
  given the disclosed race; an upper bound would not detect per-request refetching either
  (one `get_profile` per account gives the same ceiling), so leave caching to the
  sequential unit test that already pins it.
* [nit] **Test output is polluted by the moved modules' root-logger setup** (INFO
  `StreamHandler` bound to the real stderr at import). Unittest's `-b` does not help: the
  handler captured `sys.stderr` at construction (verified: identical output with and
  without `-b`). If quieter output is wanted, redirect the handler's stream in
  `PublisherTestCase.setUp`; do not touch `ldap.py`.

### Dockerfile, pyproject.toml, mise.toml, uv.lock

* [minor] **`mise run test` can rewrite uv.lock.** mise.toml's task runs plain `uv run`,
  which re-locks and syncs implicitly when pyproject.toml drifted; the Dockerfile uses
  `--locked` and fails on the same drift; the Dockerfile header calls them "the same
  command". Use `uv run --locked …`. This also backs guideline 6: dependency changes should
  never happen as a side effect of running tests.
* [minor] **`ruff` is half-added.** `ruff = "latest"` (mise.toml:2; mise.lock pins
  0.15.16) with no `[tool.ruff]`, no lint task, no mention anywhere. `ruff check src tests`
  reports exactly six errors: F841 `phone_numbers` (ldap.py:62) and E722 bare except
  (ldap.py:142), both disclosed upstream quirks that guideline 4 forbids "fixing", and F401
  for the four `from tests import support` imports. Upstream's `.flake8` (ignore E722,
  W504; line length 119) was not carried over. Either drop the tool, or pin it, add
  per-file ignores for the preserved quirks, add a lint task and mention it in
  DEVELOPING.md.
* [minor] **pytest is configured but absent.** `[tool.pytest.ini_options]`
  (pyproject.toml:25-28) and its comment ("runnable with either … or pytest") plus
  PLAN.md:23 ("equally under pytest") describe a runner that is not in pyproject.toml,
  uv.lock or the venv, and there is no evidence it was ever run. Delete the block until
  pytest is approved (guideline 6) and actually exercised.
* [minor] **`[tasks.test-docker]`** (mise.toml:11-12) exists but is referenced nowhere
  (ldap.md "Tests" and the Dockerfile header spell out the raw `docker build` command).
  Mention it or drop it.
* [nit] **Base image floats at patch level.** `PYTHON_VERSION=3.14` resolves to whatever
  3.14.x Docker Hub serves, while uv is pinned exactly and mise.lock pins 3.14.7 locally.
  Pin `3.14.7` (a second place to bump) or pin by digest; or record the choice.
* [nit] **`useradd --system` with uid 10001** prints "uid 10001 is greater than
  SYS_UID_MAX 999" during the build (observed). Drop `--system` from `useradd` (keep the
  explicit uid/gid) or accept the warning.
* [nit] **`.dockerignore`/`.gitignore` `.env`** — see M3.

### Process and repository hygiene

* [minor] **PLAN.md's fate.** It is now committed as a `fixup!` of "Initial port", so
  autosquashing folds a document whose ticks, status, counts and §8 cannot be trusted into
  the migration commit. Its durable content (§5, §6) is already in
  docs/publishers/ldap.md; §8 fits as notes on TASKS.md item 2; the approvals and
  decisions (deps, S3 defaults, unittest over pytest, deployment target) fit a short ADR
  with approver and date. Either fix it (items under PLAN.md above) before squashing, or
  drop the fixup and keep PLAN.md out of history.
* [minor] **Branch state.** `master` (`14555fe`) still carries three `fixup!` commits;
  `initial-ldap-publisher` has the squashed history plus one new fixup. No remote is
  configured. Decide which branch is the line of development before more work lands.
* [minor] **Rubric and work share one author and one afternoon.** DEVELOPING.md was
  rewritten twice during execution, both times toward what the delivered tests do
  (guidelines 5-8, test 7-9), and PLAN.md records only the first edit. That is fine, but
  PLAN.md should state the DEVELOPING.md revision it was judged against, and the guideline
  6 question (who ran `uv add`) should be answered in writing.

## 4. Decisions only the maintainer can make

1. Deployment target (M2): Kubernetes CronJob, container-image Lambda, or stay on
   Serverless. Record it once.
2. PLAN.md: fix and squash, or convert to ADR plus TASKS.md notes and drop from history.
3. S3 bucket/key defaults in `cli()` (PLAN.md §7.2): keep (faithful to serverless.yml,
   load-bearing for tests and docs) or make them required. Note D3: with the default, any
   container with AWS credentials and no `LDAP_CACHE_*` reads the production dump, and
   dev/test stages push production LDAP data into dev CIS, exactly as upstream did.
4. Exit-code and alerting contract (M4): keep upstream semantics and document them, or
   schedule a guideline 4 exception so rejected writes fail the run. Same question for a
   `DRY RUN` log line and for lowering the per-attribute INFO line.
5. Dead code rule for guideline 7 (per file vs per function), applied to `handle()`,
   `__main__`, `is_empty()` and the `mono-cis` stub.
6. `ruff`: adopt with config, or remove.
7. Test guideline 7 wording, and whether `main()`'s summary gets a log-assertion exception.

## 5. Disclosed quirks re-examined; no new action

* D1. Warm Lambda to fresh process: token and URL caches now live one run instead of
  across warm invocations; root-logger handler no longer duplicates the Lambda runtime's.
  Both facts are in the docs; the Kubernetes table already implies one process per run.
* D2. Bare `except:` leaves exit 1 with no cause for first-run failures (IRSA, region,
  permissions). Disclosed verbatim; the docs already say exit 1 means the dump could not
  be read. Same on Lambda.
* D3. Production bucket default in dev/test. PLAN.md §7.2 puts exactly this in front of
  you; see decision 3.
* D4. `DISPLAY_LEVEL` and first-token races. Both disclosed; the container changes nothing
  (same 32-thread pool). Consequence, for the record: a race can sign a non-staff
  account's first-written attributes `display: staff` (or a staff member's `private`),
  and up to 32 client-credentials grants can hit Auth0 per run.

## 6. Withdrawn during verification

* "Nothing is staged; the pending set is unstaged edits plus untracked files; two
  `fixup!` commits await autosquash on a branch with no remote and no `main`." True at
  the start (the index was empty, so "staged" in the request meant the working tree);
  overtaken by the commits and rebase made during the review. Reflected in the snapshot
  note instead.
* Recommendation to add `-b` to the unittest command: rejected by a verifier who showed
  it has no effect (handler bound to the original stderr).
* Recommendation to add an upper bound on integration token calls: rejected as unable to
  detect the regression it targeted.
* Severity downgrades applied by the materiality verifiers are reflected above (for
  example the AGENTS.md, `mono-cis` stub, HRIS follow-up and TASKS.md items were filed as
  major by finders and are minor here because none blocks item 1).

## Appendix: verification log

```
# Snapshot
git log --oneline -4          # 3b01c1f fixup! Initial port … / fc014e1 Add Dockerfile / 8d0c2a8 Initial port … / c9287fa Add TASKS.md
git branch -a                 # initial-ldap-publisher (HEAD), master @ 14555fe; no remote
git status --porcelain        # clean

# Port fidelity (upstream at local/cis-publishers, HEAD c2662d3 2022-12-30)
diff local/cis-publishers/cis_publishers/common/people.py   src/mono_cis/publishers/common/people.py    # identical
diff local/cis-publishers/cis_publishers/common/profile.py  src/mono_cis/publishers/common/profile.py   # line 10 import only
diff local/cis-publishers/cis_publishers/ldap/handler.py    src/mono_cis/publishers/ldap.py             # 8c8, 119-121c119-122, 191a193-213

# Fixtures
cmp tests/fixtures/fake-publisher-key_0.priv.pem local/cis/python-modules/cis_publisher/tests/fixture/…   # same (also pub.pem, user_profile_null.json)
openssl rsa -in tests/fixtures/fake-publisher-key_0.priv.pem -noout -modulus  == base64url-decode(jwk.n)   # MODULUS MATCH

# Tests on the project venv (CPython 3.14.7; PYTHONDONTWRITEBYTECODE=1, no sync)
.venv/bin/python -m unittest discover -s tests -t .                              # Ran 65 tests … OK
.venv/bin/python -W error::DeprecationWarning -m unittest discover -s tests -t . # OK
.venv/bin/python -X dev -m unittest discover -s tests -t .                       # OK

# Docker (daemon outside the sandbox; images tagged mono-cis-review:* and removed afterwards)
docker build --target test .   # at 3a9c6e4 working tree: FAILED
#   "variable expansion is not supported for --from, define a new stage with FROM using ARG from global scope"
docker build --target test .   # at fc014e1: Ran 65 tests … OK inside the image
docker build -t … .            # runtime: SIZE=71544740 USER=app CMD=[python3] ENTRYPOINT=[] WORKDIR=/app
docker run --rm IMG publisher-ldap                                   # "Reloading LDAP data from S3", exit 1
docker run --rm -e … -e LDAP_CACHE_FILENAME=/nonexistent IMG publisher-ldap   # exit 1
docker run --rm IMG                                                  # exit 0, no output (inherited python3 REPL on EOF)
docker run --rm IMG id                                               # uid=10001(app) gid=10001(app)
docker run --rm IMG python -c 'import mono_cis.publishers.ldap as l; print(l.__file__)'
#   /app/.venv/lib/python3.14/site-packages/mono_cis/publishers/ldap.py ; jose 3.5.0 boto3 1.43.92 requests 2.34.2
# build log: "useradd warning: app's uid 10001 is greater than SYS_UID_MAX 999"

# Upstream claims
grep -n reservedConcurrency local/cis/serverless-functions/ldap_publisher/serverless.yml   # :98 reservedConcurrency: 1
grep -rn '_request_get\|_request_post' local/cis/python-modules/cis_publisher/tests/       # test_publisher.py, test_ldap.py only
grep -n 'mock.patch' local/cis/python-modules/cis_publisher/tests/test_hris.py            # :71 Publish.get_cis_user only
wc -l local/cis/python-modules/cis_publisher/cis_publisher/hris.py                        # 523
```
