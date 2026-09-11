"""
Shared support for the publisher tests.

Import this module before anything under ``mono_cis.publishers``: ``profile.py`` parses
``PUBLISHER_SIGNING_KEY`` when it is imported, so the environment has to be in place first. Every test
module does ``from tests import support`` as its first project import.

Mocking is ``unittest.mock`` at the two client boundaries only (PLAN.md §4.2): the ``requests`` module as
seen from ``mono_cis.publishers.common.people`` and the ``boto3`` module as seen from
``mono_cis.publishers.ldap`` are replaced with ``patch.object(..., autospec=True)``, so every call is
recorded and checked against the real signatures. Nothing is ever contacted.
"""

import copy
import io
import json
import lzma
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import unquote, urlsplit

import requests
from botocore.exceptions import ClientError

FIXTURES = Path(__file__).parent / "fixtures"

# Fake, never-contacted endpoints. Only their shapes matter.
DISCOVERY_URL = "https://iam.test.invalid/.well-known/mozilla-iam"
OIDC_DISCOVERY_URL = "https://auth.test.invalid/.well-known/openid-configuration"
TOKEN_ENDPOINT = "https://auth.test.invalid/oauth/token"
PERSON_API_URL = "https://person.test.invalid"
CHANGE_API_URL = "https://change.test.invalid"
NULL_PROFILE_URL = "https://iam.test.invalid/.well-known/user_profile_null.json"
AUDIENCE = "api.test.invalid"
ACCESS_TOKEN = "test-bearer-token"
CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"

DISCOVERY_DOCUMENT = {
    "oidc_discovery_uri": OIDC_DISCOVERY_URL,
    "api": {"audience": AUDIENCE, "endpoints": {"change": CHANGE_API_URL, "person": PERSON_API_URL}},
}
OIDC_DOCUMENT = {"token_endpoint": TOKEN_ENDPOINT}
TOKEN_DOCUMENT = {"access_token": ACCESS_TOKEN}

PRIVATE_JWK = json.loads((FIXTURES / "fake-publisher-key_0.jwk.json").read_text())
PUBLIC_PEM = (FIXTURES / "fake-publisher-key_0.pub.pem").read_text()

# The four required variables from PLAN.md §6, plus PUBLISHER_NAME because unit tests call into
# profile.py directly and so bypass cli()'s defaults. Assigned, not setdefault(): the tests never contact
# anything, and a real signing key or client id in the developer's shell must not leak into assertions.
os.environ["PUBLISHER_SIGNING_KEY"] = json.dumps(PRIVATE_JWK)
os.environ["PUBLISHER_NAME"] = "ldap"
os.environ["IAM_DISCOVERY_URL"] = DISCOVERY_URL
os.environ["OAUTH_CLIENT_ID"] = CLIENT_ID
os.environ["OAUTH_CLIENT_SECRET"] = CLIENT_SECRET
os.environ["AWS_DEFAULT_REGION"] = "us-west-2"

from mono_cis.publishers import ldap  # noqa: E402  (environment must be set first)
from mono_cis.publishers.common import people, profile  # noqa: E402

REQUIRED_ENV = ("IAM_DISCOVERY_URL", "OAUTH_CLIENT_ID", "OAUTH_CLIENT_SECRET", "PUBLISHER_SIGNING_KEY")
# Everything else the code reads. Scrubbed before each test so tests only see what they set.
OPTIONAL_ENV = (
    "DRY_RUN",
    "LDAP_CACHE_S3_BUCKET",
    "LDAP_CACHE_S3_KEY",
    "LDAP_CACHE_FILENAME",
    "CIS_NULL_PROFILE_URL",
    "LDAP_USER_ID_PREFIX",
)


# -- fixtures ---------------------------------------------------------------------------------------------
def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


def null_profile():
    return load_fixture("user_profile_null.json")


def ldap_users():
    return load_fixture("ldap_users.json")


def xz(obj) -> bytes:
    return lzma.compress(json.dumps(obj).encode("utf-8"))


def cis_profile(email, *, active=True, user_id=None, username=None, uuid=None):
    """A Person API response for ``email``: the null profile with its identifying values filled in."""
    local_part = email.split("@")[0]
    p = null_profile()
    p["active"]["value"] = active
    p["login_method"]["value"] = "ad"
    p["primary_email"]["value"] = email
    p["primary_username"]["value"] = username or local_part
    p["user_id"]["value"] = user_id or f"ad|Mozilla-LDAP|{local_part}"
    p["uuid"]["value"] = uuid or "00000000-0000-4000-8000-000000000001"
    return p


def without_signature(attribute):
    return {k: v for k, v in attribute.items() if k != "signature"}


# -- requests ---------------------------------------------------------------------------------------------
def response(payload, status_code=200) -> Mock:
    """A ``requests.Response`` mock whose ``.json()`` answers a fresh copy of ``payload``."""
    mock = Mock(spec=requests.Response, name="response")
    mock.json.return_value = copy.deepcopy(payload)
    mock.status_code = status_code
    mock.ok = 200 <= status_code < 300
    mock.text = json.dumps(payload)
    return mock


def route_requests(requests_mock, profiles=None, change_response=None):
    """
    Give a ``requests`` mock ``get``/``post`` side effects that answer the canned CIS documents by URL:
    discovery, OIDC, token, null profile, ``GET <person>/v2/user/<kind>/<identifier>`` and
    ``POST <change>/v2/user``. Anything else fails the test.

    :param profiles: Person API responses keyed by the identifier in the URL (email, user_id or username).
                     Unknown identifiers answer ``{}``, which people.py turns into ProfileNotFoundException.
    :param change_response: what every Change API POST answers; ``{"status_code": 200}`` by default.

    The side effects only read shared state, so they are safe to call from main()'s 32 worker threads;
    each call builds its own response mock.
    """
    profiles = dict(profiles or {})
    change_response = {"status_code": 200} if change_response is None else change_response

    def get(url, **kwargs):
        if url == DISCOVERY_URL:
            return response(DISCOVERY_DOCUMENT)
        if url == OIDC_DISCOVERY_URL:
            return response(OIDC_DOCUMENT)
        if url == NULL_PROFILE_URL:
            return response(null_profile())
        if url.startswith(f"{PERSON_API_URL}/v2/user/"):
            identifier = unquote(urlsplit(url).path.rsplit("/", 1)[1])
            return response(profiles.get(identifier, {}))
        raise AssertionError(f"unexpected GET {url}")

    def post(url, **kwargs):
        if url == TOKEN_ENDPOINT:
            return response(TOKEN_DOCUMENT)
        if url.startswith(f"{CHANGE_API_URL}/v2/user"):
            return response(change_response)
        raise AssertionError(f"unexpected POST {url}")

    requests_mock.get.side_effect = get
    requests_mock.post.side_effect = post
    return requests_mock


def calls_to(mock_method, url_prefix):
    """``(url, kwargs)`` for every recorded call to ``mock_method`` whose URL starts with ``url_prefix``."""
    return [(c.args[0], c.kwargs) for c in mock_method.call_args_list if c.args[0].startswith(url_prefix)]


# -- boto3 --------------------------------------------------------------------------------------------------
def no_such_key(bucket="bucket", key="key") -> ClientError:
    """The error a real S3 client raises for a missing object."""
    error = {"Code": "NoSuchKey", "Message": "The specified key does not exist.", "Key": key, "BucketName": bucket}
    return ClientError({"Error": error}, "GetObject")


# -- test case --------------------------------------------------------------------------------------------
def reset_module_state():
    """people.py and profile.py cache state in module globals for the life of the process."""
    for name in ("BEARER_TOKEN", "CHANGE_API_URL", "NULL_PROFILE", "OAUTH_AUDIENCE", "PERSON_API_URL", "TOKEN_ENDPOINT"):
        setattr(people, name, None)
    profile.DISPLAY_LEVEL = None


class PublisherTestCase(unittest.TestCase):
    """
    Base class for publisher tests: snapshots and restores the environment, scrubs the optional
    variables, and resets the moved modules' cached globals before and after every test.
    """

    def setUp(self):
        super().setUp()
        env_patch = patch.dict(os.environ, {}, clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        for name in OPTIONAL_ENV:
            os.environ.pop(name, None)
        reset_module_state()
        self.addCleanup(reset_module_state)

    def patch_requests(self, profiles=None, change_response=None, route=True) -> Mock:
        """
        Replace the ``requests`` module in people.py with an autospecced mock for this test. With ``route``
        (the default) ``get``/``post`` answer the canned CIS documents by URL (see route_requests); without
        it, configure ``return_value``/``side_effect`` in the test.
        """
        patcher = patch.object(people, "requests", autospec=True)
        requests_mock = patcher.start()
        self.addCleanup(patcher.stop)
        if route:
            route_requests(requests_mock, profiles, change_response)
        return requests_mock

    def patch_boto3(self, body=None) -> Mock:
        """
        Replace the ``boto3`` module in ldap.py with an autospecced mock for this test. Its S3 client's
        ``get_object()`` serves ``body`` (bytes) — or raises NoSuchKey when ``body`` is None.
        """
        patcher = patch.object(ldap, "boto3", autospec=True)
        boto3_mock = patcher.start()
        self.addCleanup(patcher.stop)
        s3 = boto3_mock.client.return_value
        if body is None:
            s3.get_object.side_effect = no_such_key()
        else:
            s3.get_object.side_effect = lambda **kwargs: {"Body": io.BytesIO(body)}
        return boto3_mock
