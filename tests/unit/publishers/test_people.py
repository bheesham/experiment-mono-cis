"""Unit tests for mono_cis.publishers.common.people, with the ``requests`` module mocked."""

import json
import os
from unittest.mock import call, patch
from urllib.parse import quote

from tests import support
from tests.support import (
    ACCESS_TOKEN,
    AUDIENCE,
    CHANGE_API_URL,
    CLIENT_ID,
    CLIENT_SECRET,
    DISCOVERY_URL,
    NULL_PROFILE_URL,
    OIDC_DISCOVERY_URL,
    PERSON_API_URL,
    TOKEN_ENDPOINT,
    PublisherTestCase,
    cis_profile,
    null_profile,
    response,
)

from mono_cis.publishers.common import people, profile
from mono_cis.publishers.common.profile import Profile, ProfileNotFoundException

EMAIL = "astaff@mozilla.com"
PLUS_EMAIL = "a+b@mozilla.com"
USER_ID = "ad|Mozilla-LDAP|astaff"
USERNAME = "astaff"
BEARER = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
TOKEN_REQUEST = {
    "audience": AUDIENCE,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "grant_type": "client_credentials",
}


def person_url(kind, identifier):
    return f"{PERSON_API_URL}/v2/user/{kind}/{quote(identifier)}?active=any"


class GetProfileTests(PublisherTestCase):
    def setUp(self):
        super().setUp()
        self.requests = self.patch_requests(
            profiles={
                EMAIL: cis_profile(EMAIL),
                PLUS_EMAIL: cis_profile(PLUS_EMAIL),
                USER_ID: cis_profile(EMAIL),
                USERNAME: cis_profile(EMAIL),
            }
        )

    def test_more_than_one_identifier_is_rejected(self):
        with self.assertRaises(ValueError):
            people.get_profile(email=EMAIL, user_id=USER_ID)

    def test_no_identifier_returns_the_cached_null_profile(self):
        os.environ["CIS_NULL_PROFILE_URL"] = NULL_PROFILE_URL

        first = people.get_profile()
        second = people.get_profile()

        self.assertEqual(first, null_profile())
        self.assertIs(first, second)
        # No identifier means no bearer token is needed, and the document is fetched once.
        self.requests.get.assert_called_once_with(NULL_PROFILE_URL)
        self.requests.post.assert_not_called()

    def test_bearer_token_is_acquired_via_discovery_and_cached(self):
        result = people.get_profile(email=EMAIL)

        self.assertEqual(result["primary_email"]["value"], EMAIL)
        self.assertEqual(
            self.requests.mock_calls,
            [
                call.get(DISCOVERY_URL),
                call.get(OIDC_DISCOVERY_URL),
                call.post(TOKEN_ENDPOINT, json=TOKEN_REQUEST),
                call.get(person_url("primary_email", EMAIL), headers=BEARER),
            ],
        )
        self.assertEqual(people.BEARER_TOKEN, ACCESS_TOKEN)
        self.assertEqual(people.PERSON_API_URL, PERSON_API_URL)
        self.assertEqual(people.CHANGE_API_URL, CHANGE_API_URL)
        self.assertEqual(people.OAUTH_AUDIENCE, AUDIENCE)
        self.assertEqual(people.TOKEN_ENDPOINT, TOKEN_ENDPOINT)

        people.get_profile(email=EMAIL)

        # The second lookup reuses the token: exactly one more call, to the Person API.
        self.assertEqual(self.requests.mock_calls[4:], [call.get(person_url("primary_email", EMAIL), headers=BEARER)])

    def test_lookup_urls_are_quoted_and_include_inactive_profiles(self):
        cases = {
            "email": ("primary_email", PLUS_EMAIL, "a+b"),
            "user_id": ("user_id", USER_ID, USERNAME),
            "username": ("primary_username", USERNAME, USERNAME),
        }

        for kwarg, (kind, identifier, expected_username) in cases.items():
            with self.subTest(kwarg=kwarg):
                result = people.get_profile(**{kwarg: identifier})

                self.assertEqual(result["primary_username"]["value"], expected_username)
                self.assertEqual(self.requests.get.call_args, call(person_url(kind, identifier), headers=BEARER))

        # The identifiers really were percent-encoded on the wire.
        urls = [c.args[0] for c in self.requests.get.call_args_list]
        self.assertIn(f"{PERSON_API_URL}/v2/user/primary_email/a%2Bb%40mozilla.com?active=any", urls)
        self.assertIn(f"{PERSON_API_URL}/v2/user/user_id/ad%7CMozilla-LDAP%7Castaff?active=any", urls)

    def test_unknown_profile_raises(self):
        with self.assertRaises(ProfileNotFoundException) as raised:
            people.get_profile(email="ghost@mozilla.com")

        self.assertIn("ghost@mozilla.com", str(raised.exception))

    def test_missing_discovery_url_is_an_environment_error(self):
        del os.environ["IAM_DISCOVERY_URL"]

        with self.assertRaises(EnvironmentError):
            people.get_profile(email=EMAIL)

        self.requests.get.assert_not_called()
        self.requests.post.assert_not_called()


class ChangeProfileTests(PublisherTestCase):
    def setUp(self):
        super().setUp()
        # change_profile() relies on the token and URLs cached by an earlier get_profile() call.
        people.BEARER_TOKEN = ACCESS_TOKEN
        people.CHANGE_API_URL = CHANGE_API_URL
        self.requests = self.patch_requests(route=False)
        self.requests.post.return_value = response({"status_code": 200})
        self.document = cis_profile(EMAIL)

    def assert_posted(self, document):
        self.requests.post.assert_called_once_with(
            f"{CHANGE_API_URL}/v2/user?user_id={USER_ID}", headers=BEARER, json=document
        )

    def test_accepts_a_json_string(self):
        self.assertTrue(people.change_profile(json.dumps(self.document)))
        self.assert_posted(self.document)

    def test_accepts_a_dict(self):
        self.assertTrue(people.change_profile(self.document))
        self.assert_posted(self.document)

    def test_accepts_a_profile_dict(self):
        with patch.object(profile, "get_profile", autospec=True, return_value=cis_profile(EMAIL)):
            internal = Profile(email=EMAIL)._profile

        self.assertTrue(people.change_profile(internal))
        self.assert_posted(self.document)

    def test_requires_a_user_id(self):
        self.document["user_id"]["value"] = None

        with self.assertRaises(ValueError):
            people.change_profile(self.document)

        self.requests.post.assert_not_called()

    def test_failure_is_reported_as_false(self):
        for answer in ({"status_code": 400, "code": "invalid_profile", "description": "bad signature"}, {}):
            with self.subTest(answer=answer):
                self.requests.post.return_value = response(answer)

                self.assertFalse(people.change_profile(self.document))


if __name__ == "__main__":
    import unittest

    unittest.main()
