# Developing

The primary goal of this repository is to consolidate code and their related
lifecycles (development, testing, deployment, runtime). The IAM team has
limited time, focus, and attention to be spread across many repositories,
deployment methods, and runtime targets.

Projects in scope:

* [cis](https://github.com/mozilla-iam/cis): the primary target;
* [cis-publishers](https://github.com/mozilla-iam/cis-publishers): the LDAP
  publisher (now migrated, see below);
* [auth0-cis-webhook-consumer](https://github.com/mozilla-iam/auth0-cis-webhook-consumer):
  the webhook which CIS calls to publish to Auth0.

And related:

* [iam-infra](https://github.com/mozilla-iam/iam-infra/): AWS CloudFormation
  and Terraform related to infrastructure. Not necessarily in scope, but
  there are related areas (e.g. AWS policies, etc).

Suggestion: create a `local` directory in this repository, and in it add a
`.gitignore` with `*` to ignore its contents. Clone each of our references
into there, so we're able to better search and cross-reference.

The TASKS.md file lists tasks, in order of priority. If you're looking for
work, start there, then follow the Guidelines sections below.

A quick breakdown of this repository, development practices, and projects
follows.

# This repository

So, it's still quite early in this project. Only one publisher has been ported,
the LDAP publisher.

The ported LDAP publisher lives in `src/mono_cis/publishers/ldap.py`. The tests
for it are in `tests/unit/publishers` and `tests/integration/publishers`.

Other ports should follow a similar pattern, but care should be taken to:

1. Write tests _before_ simplifying;
2. Merge and refactor duplicate code when necessary -- ideally without changing
   behaviour.
3. Capture documentation in the `docs/` directory. For publishers, it's
   `docs/publishers`. For APIs it's `docs/apis`.

Additional port-specific LLM docs can be captured in `docs` as well. This
helps future reviewers and LLMs track what was done. These should live in a
subdirectory with the same name as the publisher, e.g. the LDAP publisher's
plans and reviews live under `docs/publishers/ldap`.

# Guidelines

## Guidelines for development and migrations

1. Existing tests must be moved. If upstream has none, tests must be written.
   Subsequent guidelines are never waived by the absence of upstream tests.
2. Each migration must have at least one unit test.
3. Each migration must add at least one integration test.
4. Behaviour of migrated functionality must not change.
5. Prefer using Python's standard library instead of adding dependencies or
   unnecessarily duplicating code (e.g. for mocks, use `unittest.mock.Mock`).
6. Dependencies must be reviewed and added by a human. Propose the exact uv add
   commands and wait; never edit dependencies in pyproject.toml directly.
7. Unless specifically required, do not port code. There are many parts of the
   codebase which are unused (e.g. Postgres).
8. Quirks found while migrating are documented, not fixed (see 4). Each
   project's doc has a "Preserved behaviour" section, and tests should capture
   the quirks where practical.
9. And finally, each publisher or API service should have its own entrypoint.
   These should be defined in `pyproject.toml`. Publishers should be named
   `publisher-<PUBLISHER>`, and APIs should be named `api-<API>`.

## Guidelines for tests

1. Unit tests must be self-contained and must not depend on an externally
   running service.
2. If a unit test cannot be self-contained, a mock must be used.
3. Mocks must run in-process, and must not use external dependencies.
4. Prefer using `unittest.mock.Mock` whenever possible.
5. Don't assert on log messages, assert on the expected output.
6. Don't test your dependencies, those already have tests.
7. Unit tests exercise one function with its neighbours patched.
8. Integration tests run the project's entrypoint with only the external
   boundaries mocked and assert on what reaches the external system.

Additionally, after each change, be sure to:

1. Run the tests with: `mise run test`;
2. Run the tests within Docker with `mise run test-docker`;
3. Ensure the ported code is sufficiently covered using `mise run coverage`.

## General guidelines

This project, not any of the other projects, uses mise and uv for dependency
management. Prefer using the standard library and existing dependencies.
Simplify code whenever possible, and avoid falling into the "catch all
exceptions" trap. Sometimes it's better to let exceptions bubble up and crash
the process -- it provides a signal to our alerting system.

There is lots of duplicated code. When developing, be sure to cross-reference
other projects and tasks to ensure future work will fit in cohesively.

As more projects are ported, we should aim to simplify the code -- now that
tests are written, we can be slightly more confident in our changes. Note that
this has not been deployed yet, so ultimately it's still risky to change the
implementation too much.

# Projects

The projects listed here describe the projects as they exist today, not the
work in this repository.

## cis

Important directories:

* `python-modules`: Libraries and the internal counterparts to applications;
* `serverless-functions`: Serverless definitions, and the glue for AWS API
  Gateway and AWS Lambda to call the internal functions defined in
  `python-modules`;
* `terraform`: build and runtime requirements;
* `well-known-endpoint`: service discovery resources, sporadically used
  throughout.

### APIs

These are all fronted by AWS API Gateway, and may sometimes call out to a slim
AWS Lambda definition. The Lambda invocation then uses the code defined in
`python-modules`.

#### Profile Retrieval (Person API)

Serverless definition: `serverless-functions/profile_retrieval`.

Relevant code: `python-modules/cis_profile_retrieval_service`. There was a past
experiment to run this code in a Kubernetes cluster in GCP. There are remnants
of this experiment lying around (`helm`, for example).

#### Change API

Serverless definition: `serverless-functions/change`.

Relevant code: `python-modules/cis_change_service`.

#### Webhook Notifier

Serverless definition: `serverless-functions/webhook_notifier`.

Relevant code: `python-modules/cis_notifications`.

### Cron jobs

#### HRIS Sync

Serverless definition: `serverless-functions/hris_publisher`.

Relevant code: `python-modules/cis_publisher`.

## cis-publishers

There was supposed to be more of a migration to move publishers into here, but
that never happened.

This is also deployed using Serverless. Right now the only publisher using
this is the LDAP publisher.

## auth0-cis-webhook-consumer

A webhook which listens for events from CIS (via the webhook notifier) and
updates Auth0. This is deployed using AWS CloudFormation.

# Deployment

Eventually, this will be deployed using Kubernetes. Take care to ensure the deployment
is not a burden.

This isn't an immediate goal, but we should try to simplify, without changing
behaviour, the environment variables required.
