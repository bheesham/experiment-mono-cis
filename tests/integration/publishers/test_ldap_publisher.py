"""
Integration tests for the LDAP publisher.

Everything is real — the dump parsing, thread pool, Profile walking, JWS signing and the publish
decision — except the two client boundaries: ``requests`` (Person/Change API, discovery, Auth0) and
``boto3`` (the S3 dump), which are autospecced mocks. The publisher is driven through ``cli()`` with only
the four required environment variables set (PLAN.md §6); the S3 location and publisher name come from
its defaults. The expected output is what reaches CIS: the Change API POST, and nothing else.
"""

import importlib.metadata
import json
import os
import time
from urllib.parse import quote

from tests import support
from tests.support import (
    ACCESS_TOKEN,
    CHANGE_API_URL,
    DISCOVERY_URL,
    OIDC_DISCOVERY_URL,
    PERSON_API_URL,
    PUBLIC_PEM,
    REQUIRED_ENV,
    TOKEN_ENDPOINT,
    PublisherTestCase,
    calls_to,
    cis_profile,
    ldap_users,
    no_such_key,
    without_signature,
    xz,
)

from jose import jws
from mono_cis.publishers import ldap

DEFAULT_BUCKET = "cache.ldap.sso.mozilla.com"
DEFAULT_KEY = "ldap_users.json.xz"
STAFF = "astaff@mozilla.com"
STAFF_USER_ID = "ad|Mozilla-LDAP|astaff"
INACTIVE = "inactive@mozilla.com"
GHOST = "ghost@mozilla.com"
BEARER = {"Authorization": f"Bearer {ACCESS_TOKEN}"}


class LdapPublisherRunTests(PublisherTestCase):
    def setUp(self):
        super().setUp()
        # Only the required variables; cli() supplies PUBLISHER_NAME and the S3 location.
        os.environ.pop("PUBLISHER_NAME", None)
        for name in REQUIRED_ENV:
            self.assertIn(name, os.environ)

        self.users = ldap_users()
        self.boto3 = self.patch_boto3(xz(self.users))
        # GHOST is deliberately absent: the Person API answers {} for it.
        self.requests = self.patch_requests(
            profiles={STAFF: cis_profile(STAFF), INACTIVE: cis_profile(INACTIVE, active=False)}
        )

    def assert_reads_happened(self):
        self.boto3.client.assert_called_once_with("s3")
        self.boto3.client.return_value.get_object.assert_called_once_with(Bucket=DEFAULT_BUCKET, Key=DEFAULT_KEY)

        # main() fans out over 32 worker threads, so: count recorded calls (atomic appends) rather than
        # ``call_count``, and expect token acquisition to have run at least once — workers race for the
        # first token, as upstream.
        self.assertGreaterEqual(len(calls_to(self.requests.get, DISCOVERY_URL)), 1)
        self.assertGreaterEqual(len(calls_to(self.requests.get, OIDC_DISCOVERY_URL)), 1)
        self.assertGreaterEqual(len(calls_to(self.requests.post, TOKEN_ENDPOINT)), 1)

        # Every account in the dump was looked up, once, with the bearer token.
        person_calls = calls_to(self.requests.get, f"{PERSON_API_URL}/v2/user/")
        self.assertCountEqual(
            person_calls,
            [(f"{PERSON_API_URL}/v2/user/primary_email/{quote(email)}?active=any", {"headers": BEARER}) for email in self.users],
        )

    def test_publishes_the_changed_staff_profile(self):
        exit_code = ldap.cli()

        self.assertEqual(exit_code, 0)
        self.assert_reads_happened()

        # Exactly one write: the staff member. The inactive and unknown accounts are not written.
        ((change_url, change_kwargs),) = calls_to(self.requests.post, CHANGE_API_URL)
        self.assertEqual(change_url, f"{CHANGE_API_URL}/v2/user?user_id={STAFF_USER_ID}")
        self.assertEqual(change_kwargs["headers"], BEARER)

        posted = change_kwargs["json"]
        source = self.users[STAFF]
        self.assertEqual(posted["user_id"]["value"], STAFF_USER_ID)
        self.assertEqual(posted["primary_email"]["value"], STAFF)
        self.assertEqual(posted["pgp_public_keys"]["values"], {"LDAP-1": "0x0123456789ABCDEF", "LDAP-2": "0xFEDCBA9876543210"})
        self.assertEqual(
            posted["ssh_public_keys"]["values"],
            {f"LDAP-{i}": key.strip() for i, key in enumerate(source["ssh_public_keys"], start=1)},
        )
        self.assertEqual(posted["access_information"]["ldap"]["values"], {group: None for group in source["groups"]})
        self.assertEqual(posted["identities"]["mozilla_ldap_id"]["value"], source["distinguished_name"])
        self.assertEqual(posted["identities"]["mozilla_ldap_primary_email"]["value"], STAFF)
        self.assertEqual(posted["identities"]["mozilla_posix_id"]["value"], "astaff")
        # Phone numbers are computed by synchronize() but never written (as upstream).
        self.assertIsNone(posted["phone_numbers"]["values"])

        changed = [
            posted["pgp_public_keys"],
            posted["ssh_public_keys"],
            posted["access_information"]["ldap"],
            posted["identities"]["mozilla_ldap_id"],
            posted["identities"]["mozilla_ldap_primary_email"],
            posted["identities"]["mozilla_posix_id"],
        ]
        year = time.strftime("%Y", time.gmtime())
        for attribute in changed:
            publisher = attribute["signature"]["publisher"]
            self.assertEqual((publisher["alg"], publisher["typ"], publisher["name"]), ("RS256", "JWS", "ldap"))
            self.assertEqual(attribute["metadata"]["display"], "staff")
            self.assertTrue(attribute["metadata"]["created"].startswith(year))
            self.assertTrue(attribute["metadata"]["last_modified"].startswith(year))
            # Signed with the configured key, over the attribute minus its signature block.
            payload = json.loads(jws.verify(publisher["value"], PUBLIC_PEM, algorithms="RS256"))
            self.assertEqual(payload, without_signature(attribute))

        # Untouched attributes keep their retrieved, unsigned state.
        for untouched in (posted["first_name"], posted["active"], posted["identities"]["github_id_v3"]):
            self.assertEqual(untouched["signature"]["publisher"]["value"], "")
            self.assertIsNone(untouched["metadata"]["display"])

    def test_dry_run_reads_everything_and_writes_nothing(self):
        os.environ["DRY_RUN"] = "True"

        exit_code = ldap.cli()

        self.assertEqual(exit_code, 0)
        self.assert_reads_happened()
        self.assertEqual(calls_to(self.requests.post, CHANGE_API_URL), [])

    def test_unreadable_dump_exits_one_without_touching_cis(self):
        self.boto3.client.return_value.get_object.side_effect = no_such_key(DEFAULT_BUCKET, DEFAULT_KEY)

        exit_code = ldap.cli()

        self.assertEqual(exit_code, 1)
        self.boto3.client.return_value.get_object.assert_called_once_with(Bucket=DEFAULT_BUCKET, Key=DEFAULT_KEY)
        self.requests.get.assert_not_called()
        self.requests.post.assert_not_called()


class EntrypointTests(PublisherTestCase):
    def test_publisher_ldap_console_script_points_at_cli(self):
        try:
            importlib.metadata.distribution("mono-cis")
        except importlib.metadata.PackageNotFoundError:
            self.skipTest("mono-cis is not installed in this environment (run `uv sync`)")

        # Exactly one console script of that name. (Unpack rather than index: since Python 3.12,
        # EntryPoints.__getitem__ selects by *name*, so ``[0]`` raises KeyError.)
        (entry_point,) = importlib.metadata.entry_points(group="console_scripts", name="publisher-ldap")

        self.assertEqual(entry_point.value, "mono_cis.publishers.ldap:cli")
        self.assertIs(entry_point.load(), ldap.cli)


if __name__ == "__main__":
    import unittest

    unittest.main()
