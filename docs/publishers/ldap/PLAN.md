# Plan: Migrate the LDAP publisher (`cis-publishers` → `mono-cis`)

Task: first item in TASKS.md. Source: `local/cis-publishers/cis_publishers/`.
Governed by the guidelines in DEVELOPING.md; deviations are called out.

Status: **executed** (2026-09-10). Code, tests, Dockerfile and docs are in
place; 65 tests pass. Remaining: the local `mise run test` and
`docker build --target test .` runs on a machine with Docker (§4.5), then the
tick in TASKS.md.

DEVELOPING.md was updated after the first execution pass, adding development
guideline 6 (prefer the standard library over duplicating code, e.g.
`unittest.mock.Mock`) and test guidelines 4–6 (prefer `unittest.mock.Mock`;
assert on outputs, not log messages; don't test dependencies). The tests were
reworked to comply: hand-rolled fakes replaced by `patch.object(...,
autospec=True)` / `Mock(spec=...)` / `create_autospec` (§4.2), every
`assertLogs` and log-text assertion removed in favour of return values and
recorded calls, and the one test that only checked a log line dropped.

Deviations from the plan as written, all within its stated fallbacks:

* Tests are stdlib `unittest.TestCase` (the §4.0 fallback; no `pytest` dev
  dependency was added). They run with `mise run test` and equally under
  `pytest`. Shared helpers live in `tests/support.py` instead of a `conftest.py`.
* `PUBLISHER_SIGNING_KEY` for tests is a committed JWK fixture generated from
  the `cis` fake PEM (`tests/fixtures/fake-publisher-key_0.jwk.json`) rather
  than converted at import time with `jose.jwk.construct`.
* Besides the import line and `cli()`, one comment in `ldap.py` was reworded
  (it pointed at the unported `unused_create_profile` path).
* The sandbox used to develop this has Python 3.10 and no PyPI access. The
  suite was run there with the real `python-jose` 3.5.0 / `boto3` 1.43.92 /
  `requests` 2.34.2 (pure-Python, borrowed from the project `.venv`) and with
  `-W error::DeprecationWarning`, but not on 3.14 itself — which is how one
  3.12+ incompatibility (`EntryPoints[0]`, now a by-name lookup) reached the
  local run before being fixed. The 3.14 run is the local `mise run test`.

## 1. Scope

In scope:

* Move the LDAP publisher Python code and its `common` library, verbatim.
* Tests. Upstream has none; that changes nothing. Guidelines 2 and 3 make at
  least one unit test and one integration test mandatory for every migration.
  This plan adds ~30 unit tests and 3 integration tests (§4.2). The migration
  is not done until they pass.
* Console-script entrypoint `publisher-ldap` (a small `cli()` wrapper). The
  codebase will be shared by several projects, each with its own entrypoint.
* Simplified environment contract: 4 required variables (3 secrets + the
  discovery URL); everything else defaulted or dropped (§6).
* Docker image that builds the project and runs `publisher-ldap`.
* Port the documentation (README env vars, signing key, running locally).

Out of scope (recorded, not done):

* `cis_publishers/common/unused_create_profile.py` — unused (guideline 6).
* `serverless.yml` — deployment moves to a Docker image on Kubernetes. Its
  runtime contract is captured in §6 so a CronJob can be written later.
* Unifying with `cis`'s `cis_publisher`/`cis_profile` (§8). Behaviour must not
  change (guideline 4), so no rewrites.
* Collapsing `LDAP_CACHE_S3_BUCKET`/`LDAP_CACHE_S3_KEY`/`LDAP_CACHE_FILENAME`
  into one URL-style variable — would change `main()`; defaults make it moot.
* Fixing latent bugs in the moved code (§5). Note them; do not change them.

## 2. Findings

Source inventory (all of it is moved except the unused file):

| Source (`cis_publishers/`)          | Lines | Purpose                                                     |
|-------------------------------------|------:|-------------------------------------------------------------|
| `ldap/handler.py`                   |   193 | `handle()` Lambda glue, `get_ldap_dump()`, `synchronize()`, `main()` (32-thread pool, summary log) |
| `common/__init__.py`                |    10 | re-exports                                                  |
| `common/people.py`                  |   129 | discovery → OIDC → Auth0 client-credentials token; Person API `get_profile()`; Change API `change_profile()` |
| `common/profile.py`                 |   354 | `Profile`, `ProfileDict`, `SignableAttribute`, exceptions; RS256 JWS signing via `python-jose` |
| `common/unused_create_profile.py`   |    49 | **not moved**                                               |

* No `cis` python-modules are imported. The publisher talks to CIS only over
  HTTP (`requests`: Person API v2, Change API v2, discovery, Auth0 token) and
  to S3 (`boto3`) for the LDAP dump. Those two libraries are the only
  external boundaries, and they are where tests mock.
* Runtime deps: `boto3`, `python-jose[cryptography]`, `requests`. `mono-cis`
  has none today. All three are already used by `cis` (`cis_crypto` signs with
  `jose.jws` RS256; `cis_publisher.publisher` uses `requests`).
* Tests upstream: none. See §1 and §4.2.
* Environment variables read by the moved code: `IAM_DISCOVERY_URL`,
  `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `PUBLISHER_SIGNING_KEY`,
  `PUBLISHER_NAME`, `LDAP_CACHE_S3_BUCKET`, `LDAP_CACHE_S3_KEY`,
  `LDAP_CACHE_FILENAME`, `DRY_RUN`, and `CIS_NULL_PROFILE_URL` (only on the
  no-identifier `get_profile()` path, which the publisher never takes).
  `LDAP_USER_ID_PREFIX` is read only by the unported creation code. In
  `serverless.yml`, `PUBLISHER_NAME`, `LDAP_CACHE_S3_BUCKET` and
  `LDAP_CACHE_S3_KEY` had the same value in every stage — constants, not
  configuration.
* SSM secrets were injected as env vars by Serverless at deploy time, so
  Kubernetes Secrets-as-env needs no code change.
* `cis` also contains an *older* LDAP publisher (`cis_publisher/ldap.py`,
  `serverless-functions/ldap_publisher`) that consumed a different S3 dump
  (`ldap.sso.mozilla.com`, full CIS profiles). Its fixture
  `ldap_profiles.json.xz` is in that old format and is not reusable. Its fake
  RSA key pair (`tests/fixture/fake-publisher-key_0.{priv,pub}.pem`) is. Its
  tests mock at the request level too (`unittest.mock.patch` on
  `Publish._request_get/_request_post`), the same boundary chosen here.
* Discrepancy: TASKS.md says the HRIS publisher is in `cis-publishers`; it is
  actually in `cis/python-modules/cis_publisher/hris.py` (DEVELOPING.md and the
  cis-publishers README agree). Not this task, but §8 plans for it.

## 3. Target layout

```
src/mono_cis/
  __init__.py                       # existing
  publishers/
    __init__.py
    ldap.py                         # ← cis_publishers/ldap/handler.py, plus cli()
    common/
      __init__.py                   # ← cis_publishers/common/__init__.py
      people.py                     # ← cis_publishers/common/people.py
      profile.py                    # ← cis_publishers/common/profile.py
tests/
  support.py                        # env setup, state reset, mock helpers (was: conftest.py)
  fixtures/
    ldap_users.json                 # small dump in the cache.ldap.sso format
    user_profile_null.json          # ← cis/python-modules/cis_profile/cis_profile/data/
    fake-publisher-key_0.priv.pem   # ← cis/python-modules/cis_publisher/tests/fixture/
    fake-publisher-key_0.pub.pem    # ← same
    fake-publisher-key_0.jwk.json   # private JWK generated from the PEM above
  unit/publishers/
    test_ldap.py
    test_people.py
    test_profile.py
  integration/publishers/
    test_ldap_publisher.py
docs/publishers/ldap.md             # ported README + runtime contract
Dockerfile
.dockerignore
```

`pyproject.toml`:

```toml
[project.scripts]
mono-cis = "mono_cis:main"                          # existing
publisher-ldap = "mono_cis.publishers.ldap:cli"     # new

[tool.pytest.ini_options]
testpaths = ["tests"]
```

The only new code, appended to `ldap.py`:

```python
def cli() -> int:
    """Entrypoint for `publisher-ldap`. Applies the LDAP publisher's defaults
    (constants in the old serverless.yml) and maps main()'s result to an exit
    code. main() itself is unchanged."""
    environ.setdefault("PUBLISHER_NAME", "ldap")
    if not environ.get("LDAP_CACHE_FILENAME"):  # main() prefers S3 when a bucket is set
        environ.setdefault("LDAP_CACHE_S3_BUCKET", "cache.ldap.sso.mozilla.com")
        environ.setdefault("LDAP_CACHE_S3_KEY", "ldap_users.json.xz")
    return 1 if main() else 0
```

`main()`, `handle(event, context)` and the `__main__` block are moved
verbatim; they keep reading the raw variables, so `python -m` behaves exactly
as before. Naming: flat `publishers/ldap.py` mirrors
`cis_publisher/{ldap,hris}.py`, so task 2 lands as `publishers/hris.py` with
`publisher-hris` and its own `cli()` defaults. Only the two
`from cis_publishers.common import …` lines change in the moved modules.

## 4. Steps

### 4.0 Approvals (blocking; nothing below runs without them)

- [x] Approve runtime deps `boto3`, `python-jose[cryptography]`, `requests`.
- [x] Approve dev dep `pytest` (fallback: stdlib `unittest`; pytest can still
      run those later when `cis` tests are moved).
- [x] Then `uv add boto3 "python-jose[cryptography]" requests` and
      `uv add --dev pytest`. Verify `python-jose`/`cryptography` resolve for
      Python 3.14. No commits.

### 4.1 Move the code

- [x] Create `src/mono_cis/publishers/{__init__.py,common/__init__.py}`.
- [x] Copy the three modules; rewrite only the two import lines. Keep
      module-level side effects as they are (§5).
- [x] Append `cli()` to `ldap.py`; add `publisher-ldap` to
      `[project.scripts]`; `uv sync`; `uv run publisher-ldap` with no env
      exits 1 (S3 read fails → `main()` returns the 500 dict).
- [x] `uv run python -c "import mono_cis.publishers.ldap"` with
      `PUBLISHER_SIGNING_KEY` unset must still import (the key is optional at
      import time by design).

### 4.2 Tests (required deliverable)

Rules (DEVELOPING.md test guidelines): self-contained, no external services,
mocks in-process with no extra dependencies, `unittest.mock.Mock` wherever
possible, assert on outputs rather than log messages, and don't test the
dependencies. Mocking happens at the two client boundaries only, with
`patch.object(..., autospec=True)` so every call is recorded and checked
against the real signatures:

* HTTP: `patch.object(people, "requests", autospec=True)`. `get`/`post` get
  `side_effect` routers (`tests/support.py: route_requests`) answering the
  canned CIS documents by URL — discovery (`api.endpoints.change`/`person`,
  `api.audience`, `oidc_discovery_uri`), OIDC (`token_endpoint`), token POST,
  null profile, `GET <person>/v2/user/<kind>/<identifier>?active=any` (canned
  per identifier: active, inactive, unknown → `{}`) and
  `POST <change>/v2/user?user_id=<id>`. Responses are `Mock(spec=requests.Response)`
  with `.json()` configured. Anything else fails the test. Recorded calls are
  read back from `mock_calls` / `call_args_list` (`support.calls_to`); the
  integration test counts `call_args_list` rather than `call_count`, because
  32 worker threads record concurrently.
* S3: `patch.object(ldap, "boto3", autospec=True)`;
  `client.return_value.get_object` serves `{"Body": io.BytesIO(data)}` (`data`
  is `lzma.compress(json)` or plain JSON) or raises a real
  `botocore.exceptions.ClientError` (NoSuchKey).
* Neighbours inside the module under test are autospecced too:
  `ldap.Profile` (its instance's two nested sections are real dicts so what
  `synchronize()` writes can be asserted directly), `ldap.synchronize`,
  `ldap.main`, `profile.get_profile`, `profile.change_profile`, and the parent
  `Profile` a `SignableAttribute` notifies (`create_autospec(Profile, instance=True)`).
* No HTTP server, no `moto`, no `responses`, no hand-rolled fake classes.

`tests/support.py` (imported first by every test module):

- [x] At import time (before test modules import `profile.py`, which parses
      the key on import): `PUBLISHER_SIGNING_KEY` = the committed JWK fixture;
      `PUBLISHER_NAME=ldap`; `IAM_DISCOVERY_URL` (a fake URL the router
      recognises); `OAUTH_CLIENT_ID`/`OAUTH_CLIENT_SECRET` dummies;
      `AWS_DEFAULT_REGION=us-west-2`. Assigned, not `setdefault`, so a real
      key or client id in the developer's shell can't leak into assertions.
- [x] `PublisherTestCase`: snapshots/restores `os.environ`, scrubs the optional
      variables, resets the cached module globals
      (`people.{BEARER_TOKEN,CHANGE_API_URL,NULL_PROFILE,OAUTH_AUDIENCE,PERSON_API_URL,TOKEN_ENDPOINT}`,
      `profile.DISPLAY_LEVEL`) before and after each test, and offers
      `patch_requests(profiles, change_response, route)` / `patch_boto3(body)`.
      (`profile.py` binds `get_profile`/`change_profile` at import, so unit
      tests patch those names in `profile`'s namespace, not `people`'s.)
- [x] Helpers: `null_profile()`, `cis_profile(email, active=…)` (null profile
      with `user_id`/`primary_email`/`primary_username`/`uuid`/`active`
      filled), `ldap_users()`, `xz()`, `response()`, `calls_to()`,
      `no_such_key()`, `without_signature()`, `PUBLIC_PEM`.

`tests/fixtures/ldap_users.json` — three users in the `cache.ldap.sso` dump
format (fields taken from what `synchronize()` and the unused creation code
read: `distinguished_name`, `user_id`, `groups`, `pgp_public_keys`,
`phone_numbers`, `ssh_public_keys`, `posix.uid`, `posix.uid_number`,
`entry_uuid`, `created_at`, `first_name`, `last_name`, `title`): one staff
(`o=com` DN, PGP keys in mixed `0x`/spaced forms, two SSH keys, groups), one
whose CIS profile is inactive, one unknown to CIS.

Unit tests — `tests/unit/publishers/`:

- [x] `test_profile.py`
  - `SignableAttribute` value set: list → `{v: None}` (sorted); `int`/`float`
    → `str`; `bool` untouched.
  - No-op when value unchanged, and when `None` → `None`/`[]`/`{}`: no
    signature, `parent.notify` not called.
  - On change: `metadata.created` replaced only when it starts with `1970`,
    `last_modified` updated, `display` taken from `DISPLAY_LEVEL`;
    `ValueError` when neither is set; `RuntimeError` when
    `profile.PUBLISHER_SIGNING_KEY` is `None`.
  - Signature block: `publisher.name == PUBLISHER_NAME`, `alg RS256`,
    `additional` placeholder; `jws.verify(value, public_pem, "RS256")`
    payload equals the attribute without `signature` (asserting what *our*
    code signs, with which key — not the library).
  - Notifications: `parent.notify` called once with the list diff `+a, -b`;
    from `None` `+a, +b`; scalar `old --> new`.
  - `Profile` (with `profile.get_profile` autospecced): `.data` mirrors
    values; `json()` round-trips; `p["identities"].update(...)` then `sign()`
    propagates into `_profile`; `InactiveProfileException` when `active` is
    `False` unless `allow_inactive=True`.
  - `Profile.publish` (with `profile.change_profile` autospecced): not called
    when nothing changed; not called when `DRY_RUN` is set (env or argument);
    otherwise called once with the signed JSON document.
  - `ProfileDict.__setitem__`: `ValueError` on overwriting a nested
    `ProfileDict` with a scalar; sets a `SignableAttribute`'s value in place.
- [x] `test_people.py`
  - `get_profile` with two identifiers → `ValueError`.
  - `get_profile()` with none → `CIS_NULL_PROFILE_URL` fetched once, cached
    (the test sets that variable itself; nothing else needs it).
  - Token chain, as the exact ordered `mock_calls`: discovery GET, OIDC GET,
    token POST with `audience`/`client_id`/`client_secret`/`grant_type`, then
    the Person API GET with the bearer header; a second lookup adds one GET.
  - URL shapes for `email` (quoted) / `user_id` / `username`, all
    `?active=any`; empty body → `ProfileNotFoundException`.
  - Missing `IAM_DISCOVERY_URL` → `EnvironmentError`, nothing requested.
  - `change_profile` (bare autospec, `post.return_value` per test): accepts
    `str`/`dict`/`ProfileDict`; `assert_called_once_with(<change>/v2/user?user_id=<id>, headers=…, json=…)`;
    `ValueError` when `user_id.value` is `None`; `True` on
    `status_code == 200`, else `False` (with and without error details).
- [x] `test_ldap.py`
  - `get_ldap_dump(filename=…)` reads JSON from a temp dir; missing file →
    `FileNotFoundError`.
  - `get_ldap_dump(bucket, key)`: `.xz` decompressed when `LDAP_CACHE_S3_KEY`
    ends in `xz`, plain otherwise (and the quirk that the argument doesn't
    decide); `get_object.assert_called_once_with(Bucket=, Key=)`; missing
    object → `ClientError` propagates.
  - `synchronize` (with `ldap.Profile` autospecced): `Profile(email=…)`
    asserted; `update()` called once with the normalised PGP (`"ABCD EF01"`
    → `0xABCDEF01`, `"0x1234"` unchanged, never `0x0x`) and stripped SSH
    keys under `LDAP-1..n`; `access_information["ldap"]` and `identities`
    written; `publish(display_level=…)` `staff` for `o=com`/`o=org` DNs else
    `private`; returns `True`; `InactiveProfileException` /
    `ProfileNotFoundException` → `False` and no publish; other errors
    propagate.
  - `main()`: no `LDAP_CACHE_*` env, unreadable S3, missing local file →
    `{"statusCode": 500, …}` and `synchronize` never called; local file and
    S3 paths → `None` and `synchronize` called once per user
    (`assertCountEqual`, order is concurrent); S3 wins over a local file; a
    worker exception propagates.
  - `handle()` calls `main()` and returns `None`, even for the error dict.
  - `cli()` (with `main` autospecced): sets `PUBLISHER_NAME`, bucket and key
    defaults when absent; never overrides values already set; applies no S3
    defaults when `LDAP_CACHE_FILENAME` is set; returns `0` for `None`, `1`
    for the error dict.

Integration tests — `tests/integration/publishers/test_ldap_publisher.py`
(everything real except `people.requests` and `ldap.boto3`), run through
`cli()` with only the four required variables set (§6). The expected output is
what reaches CIS:

- [x] Full run with the xz dump of three users: `get_object` called once with
      the defaulted bucket/key; every account looked up once with the bearer
      token; exactly one Change API POST, whose body has
      `pgp_public_keys.values`, `ssh_public_keys.values`,
      `identities.mozilla_ldap_id` / `mozilla_ldap_primary_email` /
      `mozilla_posix_id`, `access_information.ldap.values` matching the dump;
      `signature.publisher.name == "ldap"` on each changed attribute and each
      verifies against the public PEM; `metadata.display == "staff"`;
      untouched attributes unsigned; `cli()` returns `0`.
- [x] Same with `DRY_RUN=True`: same reads, zero POSTs.
- [x] Unreadable dump: `cli()` returns `1`, nothing requested from CIS.
- [x] Entrypoint: `importlib.metadata.entry_points(group="console_scripts", name="publisher-ldap")`
      → `mono_cis.publishers.ldap:cli`, and `load()` is `ldap.cli` (pins the
      shared-codebase contract; the project is installed by `uv sync`).

### 4.3 Docker

- [x] `Dockerfile`, multi-stage on `python:3.14-slim` with the `uv` binary
      copied from `ghcr.io/astral-sh/uv`: `builder` (`uv sync --frozen
      --no-dev`), `test` (`uv sync --frozen`, `RUN uv run pytest`), `runtime`
      (copy `.venv`, non-root user, `.venv/bin` on `PATH`). No default `CMD`:
      the image is shared, each Job sets its command (`publisher-ldap`).
- [x] `.dockerignore`: `local/`, `.venv/`, `dist/`, `.git/`, `__pycache__/`.
- [ ] Verify: `docker build --target test .` passes;
      `docker run --rm <image> publisher-ldap` exits 1 (no env);
      `docker run --rm --env-file … <image> publisher-ldap` with
      `DRY_RUN=True` exits 0.

### 4.4 Documentation

- [x] `docs/publishers/ldap.md`: port the README (env vars per §6,
      signing-key generation, running locally via `uv run publisher-ldap` and
      via Docker), plus §5 and §6 of this plan.
- [ ] Optional, needs approval: one-line pointer from DEVELOPING.md's
      `cis-publishers` section to `docs/publishers/ldap.md`.

### 4.5 Verify and close out

- [ ] `mise run test` green locally and `docker build --target test .` passes
- [x] Diff moved modules against source: only import lines differ, plus the
      appended `cli()`.
- [ ] Tick the task in TASKS.md. No commits.

## 5. Behaviour to preserve (do not "fix" while moving)

* `profile.py` parses `PUBLISHER_SIGNING_KEY` at import; `people.py` caches
  token/URLs in module globals for the process lifetime.
* `get_ldap_dump()` decides `.xz` from `environ["LDAP_CACHE_S3_KEY"]`, not its
  `key` argument.
* `main()` prefers S3 whenever `LDAP_CACHE_S3_BUCKET` is set, which is why
  `cli()` only defaults it when `LDAP_CACHE_FILENAME` is absent.
* `handle()` is annotated `-> int` but returns `None`; `main()` returns
  `{"statusCode": 500, …}` when the dump can't be read and `None` otherwise;
  the bare `except:` swallows the cause.
* `synchronize()` returns `True`/`False` only, so `failed_accounts` is
  effectively unreachable; an exception in a worker propagates out of
  `future.result()` and aborts the summary.
* `change_profile()`'s required-attribute check compares dicts to `None`, so
  only `user_id.value` is really validated.
* `SignableAttribute.__contains__` calls `super().__contains__(self, k)`
  (would `TypeError`) — unreachable in practice.
* `handle()`'s module adds a `StreamHandler` to the root logger at import.

## 6. Environment contract for `publisher-ldap`

Required (set these and nothing else in the normal case):

| Env var                 | Secret | Value / was                                                          |
|-------------------------|:------:|----------------------------------------------------------------------|
| `IAM_DISCOVERY_URL`     |        | prod `https://auth.mozilla.com/.well-known/mozilla-iam`; dev/test `https://auth.allizom.org/.well-known/mozilla-iam`. Deliberately no default: it selects the stage. |
| `OAUTH_CLIENT_ID`       |  yes   | was SSM `/iam/cis/<stage>/ldap_publisher/client_id`                  |
| `OAUTH_CLIENT_SECRET`   |  yes   | was SSM `/iam/cis/<stage>/ldap_publisher/client_secret`              |
| `PUBLISHER_SIGNING_KEY` |  yes   | JWK JSON; was SSM `/iam/cis-publishers/<stage>/ldap_signing_key`     |

Defaulted by `cli()` (override only if the value changes):

| Env var                | Default                        |
|------------------------|--------------------------------|
| `PUBLISHER_NAME`       | `ldap`                         |
| `LDAP_CACHE_S3_BUCKET` | `cache.ldap.sso.mozilla.com`   |
| `LDAP_CACHE_S3_KEY`    | `ldap_users.json.xz`           |

Optional:

| Env var               | Effect                                                        |
|-----------------------|---------------------------------------------------------------|
| `DRY_RUN`             | any value: read everything, write nothing to the Change API   |
| `LDAP_CACHE_FILENAME` | local dump path; suppresses the S3 defaults (dev use)         |

Dropped (were in `serverless.yml`, never read on the publisher's code path):
`LDAP_USER_ID_PREFIX`, `CIS_NULL_PROFILE_URL`.

Provided by the platform, not by the app config: AWS credentials and region
(IRSA / pod identity sets `AWS_REGION`, `AWS_DEFAULT_REGION`; Lambda implied
`us-west-2`).

CronJob mapping: command `publisher-ldap`; `rate(30 minutes)` →
`*/30 * * * *`; `maximumRetryAttempts: 0` → `concurrencyPolicy: Forbid`,
`backoffLimit: 0`; `timeout: 900` → `activeDeadlineSeconds: 900`;
`memorySize: 2048` → ~2Gi request. IAM: `s3:ListBucket`, `s3:GetObject` on
`cache.ldap.sso.mozilla.com` (the `s3:PutObject lastRun*` grant backed a TODO
that was never implemented).

## 7. Decisions needed

1. Dependency approval (§4.0). Zero-dep alternatives: `requests` → `urllib`
   is a rewrite with subtle behaviour risk; JWS RS256 has no stdlib option.
2. Defaults for the S3 bucket/key live in `cli()`, i.e. an infrastructure
   name moves from `serverless.yml` into code. Faithful to the old deployment
   (identical in every stage), but say so if you'd rather keep them required.
3. DEVELOPING.md pointer to the new docs (§4.4).

## 8. Fit with later work

* Task 2 (HRIS, `cis/python-modules/cis_publisher/hris.py`, 523 lines) lands
  as `publishers/hris.py` with `publisher-hris` and its own `cli()` defaults
  (`PUBLISHER_NAME=hris`, …). It brings `cis_publisher.publisher.Publish`,
  `secret.py` (SSM + everett config) and `cis_profile.User` — a second,
  parallel "common" layer to this task's `publishers/common/`.
  `cis_publisher/common.py` (everett) must not collide with the package
  `publishers/common/`; suggest `publishers/config.py` when it arrives. Its
  existing tests (`tests/test_hris.py`, `test_publisher.py`, …) already mock
  at the request level (`Publish._request_get/_request_post`), matching the
  style here. The same env-simplification applies there: HRIS currently pulls
  config from SSM + everett INI at runtime, which will need to become env vars
  for Kubernetes.
* Duplication to converge on later (not now): `Profile` vs `cis_profile.User`
  (profile walk/sign), `people.py` vs `Publish` (token + Person/Change API),
  JWS signing here vs `cis_crypto.operation`. All use `python-jose` RS256, so
  the approved dep set covers all of them.
* Shared test assets: the fake RSA key pair, `user_profile_null.json`, and
  `tests/support.py` (`PublisherTestCase.patch_requests`/`patch_boto3`,
  `route_requests`, `response`, `calls_to`).
