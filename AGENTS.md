# Developing

The primary goal of this repository is to consolidate code and their related
lifecycles (development, testing, deployment, runtime). The IAM team has
limited time, focus, and attention to be spread across many repositories,
deployment methods, and runtime targets.

Projects in scope:

* [cis](https://github.com/mozilla-iam/cis): the primary target;
* [cis-publishers](https://github.com/mozilla-iam/cis-publishers): the LDAP publisher;
* [auth0-cis-webhook-consumer](https://github.com/mozilla-iam/auth0-cis-webhook-consumer): the webhook which CIS calls to publish to Auth0.

And related:

* [iam-infra](https://github.com/mozilla-iam/iam-infra/): AWS CloudFormation
  and Terraform related to infrastructure. Not necessarily in scope, but there
  are related areas (e.g. AWS policies, etc).

Suggestion: create a `local` directory in this repository, and in it add a
`.gitignore` with `*` to ignore its contents. Clone each of our references into
there, so we're able to better search and cross-reference.

The TASKS.md file lists tasks, in order of priority. If you're looking for
work, start there.

A quick breakdown of development practices and projects follow.

# Guidelines

Guidelines for development and migrations:

1. Existing tests must be moved.
2. Each migration must have at least one unit test.
3. Each migration must add at least one integration test.
4. Behaviour of migrated functionality must not change.

Guidelines for tests:

1. Unit tests must be self-contained and must not depend on an externally
   running service.
2. If a unit test cannot be self-contained, a mock must be used.
3. Mocks must run in-process, and must not use external dependencies.

# Projects

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
