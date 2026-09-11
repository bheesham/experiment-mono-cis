# LDAP publisher

Publishes LDAP account data into CIS. Every run reads the full LDAP dump
(`ldap_users.json.xz`, produced by the LDAP-to-S3 cron), looks each account up
in the Person API, and for every *active* profile writes the LDAP-owned
attributes through the Change API, signing each changed attribute with the
publisher's RSA key. It only ever updates profiles; it never creates them.

Migrated from [mozilla-iam/cis-publishers](https://github.com/mozilla-iam/cis-publishers)
(`cis_publishers/ldap/handler.py` and `cis_publishers/common/`, at commit
`c2662d3`). The module bodies are unchanged apart from import paths; see
"Preserved behaviour" below before "fixing" anything.

| | |
|---|---|
| Entrypoint | `publisher-ldap` (console script → `mono_cis.publishers.ldap:cli`) |
| Code | `src/mono_cis/publishers/ldap.py`, `src/mono_cis/publishers/common/` |
| Tests | `tests/unit/publishers/`, `tests/integration/publishers/test_ldap_publisher.py` |
| Schedule (previously) | every 30 minutes, single instance, 15 minute limit, 2 GB |

## Configuration

Everything is environment variables. The secrets are values, not file paths,
so they map directly onto Kubernetes `Secret` keys exposed as `env`.

### Required

| Variable | Secret | Value |
|---|:---:|---|
| `IAM_DISCOVERY_URL` | | Production: `https://auth.mozilla.com/.well-known/mozilla-iam`. Development and testing: `https://auth.allizom.org/.well-known/mozilla-iam`. Everything else (Person API, Change API, OAuth audience, token endpoint) is discovered from this document, so it is what selects the stage. Deliberately has no default. |
| `OAUTH_CLIENT_ID` | yes | Auth0 client used to obtain a bearer token for the Person and Change APIs (client-credentials grant). Previously SSM `/iam/cis/<stage>/ldap_publisher/client_id`. |
| `OAUTH_CLIENT_SECRET` | yes | Its secret. Previously SSM `/iam/cis/<stage>/ldap_publisher/client_secret`. |
| `PUBLISHER_SIGNING_KEY` | yes | The publisher's private RSA key as a JWK JSON document (see "Signing key"). Previously SSM `/iam/cis-publishers/<stage>/ldap_signing_key`. |

### Defaulted by `publisher-ldap`

Constants in the old `serverless.yml` (the same in every stage). `cli()` sets
them only when absent, so an explicit value always wins.

| Variable | Default |
|---|---|
| `PUBLISHER_NAME` | `ldap` — the `signature.publisher.name` written on every signed attribute |
| `LDAP_CACHE_S3_BUCKET` | `cache.ldap.sso.mozilla.com` |
| `LDAP_CACHE_S3_KEY` | `ldap_users.json.xz` (a key ending in `xz` is decompressed; anything else is read as plain JSON) |

### Optional

| Variable | Effect |
|---|---|
| `DRY_RUN` | Set to anything to read everything and sign as usual, but never POST to the Change API. |
| `LDAP_CACHE_FILENAME` | Path to a local, uncompressed LDAP dump. When set, `publisher-ldap` does not apply the S3 defaults, so the file is used. (If a bucket *is* set explicitly, S3 wins.) |

### Provided by the platform

AWS credentials and region for reading the dump: on Kubernetes via IRSA / pod
identity, which also sets `AWS_REGION` and `AWS_DEFAULT_REGION` (Lambda implied
`us-west-2`). The role needs `s3:ListBucket` and `s3:GetObject` on
`cache.ldap.sso.mozilla.com` and `cache.ldap.sso.mozilla.com/*`.

### Not carried over

`LDAP_USER_ID_PREFIX` and `CIS_NULL_PROFILE_URL` were set by the old deployment
but are only read on the profile-*creation* path, which this publisher never
takes (the creation code, `unused_create_profile.py`, was not ported).

## Running

Locally, against a real CIS stage (you need the four required variables; run
[MAWS](https://github.com/mozilla-iam/mozilla-aws-cli) first for S3 access):

```bash
export IAM_DISCOVERY_URL=https://auth.allizom.org/.well-known/mozilla-iam
export OAUTH_CLIENT_ID=… OAUTH_CLIENT_SECRET=… PUBLISHER_SIGNING_KEY='{"kty":"RSA",…}'
DRY_RUN=True uv run publisher-ldap
```

Against a local copy of the dump instead of S3:

```bash
DRY_RUN=True LDAP_CACHE_FILENAME=./ldap_users.json uv run publisher-ldap
```

With Docker (one image for all projects; the command selects the project):

```bash
docker build -t mono-cis .
docker run --rm --env-file .env mono-cis publisher-ldap
```

Exit status: `0` when the run completed (the summary below is logged), `1` when
the LDAP dump could not be read (`main()` returned its error response). Every
run ends with a summary such as:

```
LDAP Publisher results:

  1234 accounts synchronized.
  2 accounts have CIS/HRIS/LDAP mismatches: a@mozilla.com, b@mozilla.com
  0 accounts failed to synchronize

LDAP Publisher completed in 45.12s.
```

"Mismatches" are accounts present in the LDAP dump whose CIS profile is either
inactive (only the HRIS publisher can change `active`, so LDAP and HRIS have
drifted) or missing (this publisher does not create profiles).

### Kubernetes

The previous Lambda settings and their CronJob equivalents:

| Lambda (`serverless.yml`) | CronJob |
|---|---|
| `schedule: rate(30 minutes)` | `schedule: "*/30 * * * *"` |
| `maximumRetryAttempts: 0` (and the older publisher's `reservedConcurrency: 1`) | `concurrencyPolicy: Forbid`, `backoffLimit: 0` |
| `timeout: 900` | `activeDeadlineSeconds: 900` |
| `memorySize: 2048` ("2048 decreases runtime to ~45s") | ~2Gi memory request |
| handler `cis_publishers.ldap.handler.handle` | `command: ["publisher-ldap"]` |

Logging goes to stderr (root logger, `INFO`).

## Signing key

`PUBLISHER_SIGNING_KEY` is the publisher's RSA private key as a JWK, with `use`
and a `kid`. It was generated from the PEM private key with
[rsa-pem-to-jwk](https://github.com/OADA/rsa-pem-to-jwk):

```javascript
const fs = require("fs");
const rsaPemToJwk = require("rsa-pem-to-jwk");
const { v4: uuidv4 } = require("uuid");

const jwk = Object.assign(rsaPemToJwk(fs.readFileSync("signing_key.pem"), {use: "sig"}, "private"), {kid: uuidv4()});

JSON.stringify(jwk);
```

The matching public key must be listed under `api.publishers_jwks.ldap` in the
well-known `mozilla-iam` document (`cis/well-known-endpoint`), which is what the
Change API verifies signatures against. Attributes are signed as RS256 JWS
(`jose.jws.sign`) over the attribute minus its `signature` block, the same
scheme `cis_crypto` uses.

## Tests

```bash
mise run test            # python -m unittest discover -s tests -t .
docker build --target test .
```

Tests are self-contained `unittest.TestCase`s. The only things replaced are the
`requests` module as seen from `common/people.py` and the `boto3` module as
seen from `ldap.py`, both with `unittest.mock.patch.object(..., autospec=True)`
so calls are recorded and checked against the real signatures
(`tests/support.py`). Everything else — dump parsing, the thread pool, profile
walking, RS256 signing, the publish decision — runs for real, and assertions
are on outputs (return values, the Change API request) rather than on log
messages. Signatures are verified against the fixture public key. Fixtures:

* `tests/fixtures/ldap_users.json` — three accounts in the dump format: one
  staff member whose profile changes, one whose CIS profile is inactive, one
  unknown to CIS.
* `tests/fixtures/user_profile_null.json` — the CIS null profile, from
  `cis/python-modules/cis_profile/cis_profile/data/`.
* `tests/fixtures/fake-publisher-key_0.{priv,pub}.pem` — the fake key pair from
  `cis/python-modules/cis_publisher/tests/fixture/`, plus its JWK form
  (`fake-publisher-key_0.jwk.json`), which is what `PUBLISHER_SIGNING_KEY`
  holds during tests.

## Preserved behaviour

Guideline 4 (DEVELOPING.md): behaviour of migrated functionality must not
change. These are known quirks, kept on purpose and pinned by tests where
practical:

* `common/profile.py` parses `PUBLISHER_SIGNING_KEY` when imported; a missing
  key only fails at signing time. `common/people.py` caches the bearer token
  and API URLs in module globals for the life of the process, and the 32
  worker threads may race to fetch the first token.
* `get_ldap_dump()` decides whether to decompress from `LDAP_CACHE_S3_KEY`, not
  from its `key` argument.
* `main()` prefers S3 whenever `LDAP_CACHE_S3_BUCKET` is set, which is why
  `cli()` only defaults it when `LDAP_CACHE_FILENAME` is absent.
* `main()` returns `{"statusCode": 500, "body": …}` when the dump cannot be
  read and `None` otherwise; the bare `except:` hides the cause. `handle()`
  (kept for interface compatibility) discards that result.
* `synchronize()` returns `True`/`False` only, so "failed to synchronize" is
  effectively unreachable; any other exception in a worker propagates out of
  `future.result()` and aborts the summary.
* Phone numbers are computed from the dump but never written to the profile;
  `access_information.ldap` and `identities.mozilla_*` are.
* `change_profile()` only really validates `user_id.value` (the other two
  checks compare dicts to `None`). The Change API URL embeds the `user_id`
  without percent-encoding.
* The display level is a module global set per `publish()` call; two profiles
  with different levels signed concurrently could observe each other's value.
