"""Unit tests for mono_cis.publishers.common.profile: SignableAttribute, ProfileDict and Profile."""

import json
import os
import time
from unittest.mock import create_autospec, patch

from tests import support
from tests.support import PUBLIC_PEM, PublisherTestCase, cis_profile, null_profile, without_signature

from jose import jws
from mono_cis.publishers.common import profile
from mono_cis.publishers.common.profile import (
    InactiveProfileException,
    Profile,
    ProfileDict,
    SignableAttribute,
)

EMAIL = "astaff@mozilla.com"
USER_ID = "ad|Mozilla-LDAP|astaff"


def mock_parent():
    """The parent Profile a SignableAttribute reports changes to, as an autospecced instance mock."""
    return create_autospec(Profile, instance=True)


def attribute(name, **overrides):
    """A SignableAttribute built from the null profile's attribute ``name``, plus its (mock) parent."""
    data = null_profile()[name]
    data.update(overrides)
    parent = mock_parent()
    return SignableAttribute(data, name=name, parent_profile=parent), parent


class SignableAttributeTests(PublisherTestCase):
    def setUp(self):
        super().setUp()
        profile.DISPLAY_LEVEL = "staff"

    def test_list_becomes_sorted_dict_of_nulls(self):
        attr, _ = attribute("pgp_public_keys")

        attr.value = ["b", "a"]

        self.assertEqual(attr.data["values"], {"a": None, "b": None})
        self.assertEqual(attr.value, {"a": None, "b": None})

    def test_numbers_become_strings_but_booleans_do_not(self):
        first_name, _ = attribute("first_name")
        first_name.value = 42
        self.assertEqual(first_name.data["value"], "42")

        first_name.value = 1.5
        self.assertEqual(first_name.data["value"], "1.5")

        active, _ = attribute("active")
        active.value = True
        self.assertIs(active.data["value"], True)

    def test_unchanged_value_is_a_noop(self):
        attr, parent = attribute("first_name", value="Ada")

        attr.value = "Ada"

        self.assertEqual(attr.data["signature"]["publisher"]["value"], "")
        self.assertEqual(attr.data["metadata"]["created"], "1970-01-01T00:00:00Z")
        parent.notify.assert_not_called()

    def test_empty_values_over_none_are_a_noop(self):
        for empty in (None, [], {}):
            with self.subTest(empty=empty):
                attr, parent = attribute("pgp_public_keys")
                attr.value = empty
                self.assertIsNone(attr.data["values"])
                parent.notify.assert_not_called()

    def test_change_updates_metadata_and_signs(self):
        attr, _ = attribute("first_name")
        year = time.strftime("%Y", time.gmtime())

        attr.value = "Ada"

        metadata = attr.data["metadata"]
        self.assertTrue(metadata["created"].startswith(year), metadata["created"])
        self.assertTrue(metadata["last_modified"].startswith(year), metadata["last_modified"])
        self.assertEqual(metadata["display"], "staff")

        signature = attr.data["signature"]
        self.assertEqual(signature["additional"], [{"alg": "RS256", "name": None, "typ": "JWS", "value": ""}])
        self.assertEqual(signature["publisher"]["alg"], "RS256")
        self.assertEqual(signature["publisher"]["typ"], "JWS")
        self.assertEqual(signature["publisher"]["name"], "ldap")

        # What was signed: the attribute without its signature block, with the fixture key.
        payload = json.loads(jws.verify(signature["publisher"]["value"], PUBLIC_PEM, algorithms="RS256"))
        self.assertEqual(payload, without_signature(attr.data))
        self.assertEqual(payload["value"], "Ada")

    def test_existing_created_timestamp_and_display_are_kept(self):
        attr, _ = attribute("first_name")
        attr.data["metadata"]["created"] = "2019-02-27T11:23:33.000Z"
        attr.data["metadata"]["display"] = "public"

        attr.value = "Ada"

        self.assertEqual(attr.data["metadata"]["created"], "2019-02-27T11:23:33.000Z")
        self.assertEqual(attr.data["metadata"]["display"], "public")

    def test_signing_without_a_display_level_fails(self):
        profile.DISPLAY_LEVEL = None
        attr, _ = attribute("first_name")

        with self.assertRaises(ValueError):
            attr.value = "Ada"

    def test_signing_without_a_key_fails(self):
        attr, _ = attribute("first_name")

        with patch.object(profile, "PUBLISHER_SIGNING_KEY", None):
            with self.assertRaises(RuntimeError):
                attr.value = "Ada"

    def test_attribute_without_signature_block_is_set_but_not_signed(self):
        parent = mock_parent()
        attr = SignableAttribute({"metadata": {}, "value": None}, name="x", parent_profile=parent)

        attr.value = "y"

        self.assertEqual(attr.data, {"metadata": {}, "value": "y"})
        parent.notify.assert_not_called()

    def test_notification_for_list_diff(self):
        attr, parent = attribute("pgp_public_keys", values={"a": None, "b": None})

        attr.value = ["b", "c"]

        parent.notify.assert_called_once_with("pgp_public_keys", "+c, -a")

    def test_notification_for_list_from_nothing(self):
        attr, parent = attribute("pgp_public_keys")

        attr.value = ["y", "x"]

        parent.notify.assert_called_once_with("pgp_public_keys", "+x, +y")

    def test_notification_for_scalar_change(self):
        attr, parent = attribute("first_name", value="Ada")

        attr.value = "Bob"

        parent.notify.assert_called_once_with("first_name", "Ada --> Bob")

    def test_only_value_and_values_are_readable(self):
        attr, _ = attribute("first_name")

        with self.assertRaises(ValueError):
            attr.metadata


class ProfileDictTests(PublisherTestCase):
    def test_nested_dict_cannot_be_replaced_by_a_scalar(self):
        d = ProfileDict()
        d["nested"] = ProfileDict()

        with self.assertRaises(ValueError):
            d["nested"] = "scalar"

    def test_assigning_to_a_signable_attribute_sets_its_value(self):
        d = ProfileDict()
        d["attr"] = SignableAttribute({"metadata": {}, "value": None}, name="attr", parent_profile=mock_parent())

        d["attr"] = "new"

        self.assertIsInstance(d["attr"], SignableAttribute)
        self.assertEqual(d["attr"].value, "new")


class ProfileTests(PublisherTestCase):
    def setUp(self):
        super().setUp()
        self.retrieved = cis_profile(EMAIL)
        get_profile = patch.object(profile, "get_profile", autospec=True, return_value=self.retrieved)
        self.get_profile = get_profile.start()
        self.addCleanup(get_profile.stop)
        change_profile = patch.object(profile, "change_profile", autospec=True, return_value=True)
        self.change_profile = change_profile.start()
        self.addCleanup(change_profile.stop)

    def test_data_mirrors_person_api_values(self):
        p = Profile(email=EMAIL)

        self.get_profile.assert_called_once_with(EMAIL, None, None)
        self.assertEqual(p["primary_email"], EMAIL)
        self.assertEqual(p["user_id"], USER_ID)
        self.assertIs(p["active"], True)
        self.assertEqual(p["schema"], self.retrieved["schema"])
        self.assertIsNone(p["identities"]["mozilla_ldap_id"])
        self.assertIsNone(p["access_information"]["ldap"])
        self.assertIsNone(p["pgp_public_keys"])

    def test_json_round_trips_the_person_api_document(self):
        p = Profile(email=EMAIL)

        self.assertEqual(json.loads(p.json()), self.retrieved)

    def test_inactive_profile_is_rejected_unless_allowed(self):
        self.get_profile.return_value = cis_profile(EMAIL, active=False)

        with self.assertRaises(InactiveProfileException):
            Profile(email=EMAIL)

        p = Profile(email=EMAIL, allow_inactive=True)
        self.assertIs(p["active"], False)

    def test_sign_propagates_changes_into_the_signed_document(self):
        p = Profile(email=EMAIL)
        p.update({"pgp_public_keys": {"LDAP-1": "0xABC"}})
        p["identities"].update({"mozilla_ldap_id": "mail=astaff@mozilla.com,o=com,dc=mozilla"})
        p["access_information"]["ldap"] = ["team_iam", "all_staff"]

        p.sign("staff")

        signed = json.loads(p.json())
        self.assertEqual(signed["pgp_public_keys"]["values"], {"LDAP-1": "0xABC"})
        self.assertEqual(signed["identities"]["mozilla_ldap_id"]["value"], "mail=astaff@mozilla.com,o=com,dc=mozilla")
        self.assertEqual(signed["access_information"]["ldap"]["values"], {"all_staff": None, "team_iam": None})
        for changed in (signed["pgp_public_keys"], signed["identities"]["mozilla_ldap_id"], signed["access_information"]["ldap"]):
            self.assertEqual(changed["metadata"]["display"], "staff")
            self.assertEqual(changed["signature"]["publisher"]["name"], "ldap")
            self.assertNotEqual(changed["signature"]["publisher"]["value"], "")
        # Untouched attributes are left exactly as retrieved.
        self.assertEqual(signed["first_name"], self.retrieved["first_name"])

    def test_publish_skips_when_nothing_changed(self):
        p = Profile(email=EMAIL)

        p.publish(display_level="staff")

        self.change_profile.assert_not_called()

    def test_publish_respects_dry_run_environment(self):
        os.environ["DRY_RUN"] = "True"
        p = Profile(email=EMAIL)
        p["identities"].update({"mozilla_ldap_id": "dn"})

        p.publish(display_level="staff")

        self.change_profile.assert_not_called()

    def test_publish_respects_dry_run_argument(self):
        p = Profile(email=EMAIL)
        p["identities"].update({"mozilla_ldap_id": "dn"})

        p.publish(display_level="staff", dry_run=True)

        self.change_profile.assert_not_called()

    def test_publish_sends_the_signed_document_when_changed(self):
        p = Profile(email=EMAIL)
        p["identities"].update({"mozilla_ldap_id": "dn"})

        p.publish(display_level="staff")

        self.change_profile.assert_called_once()
        (sent,) = self.change_profile.call_args.args
        self.assertIsInstance(sent, str)
        document = json.loads(sent)
        self.assertEqual(document["identities"]["mozilla_ldap_id"]["value"], "dn")
        self.assertEqual(document["identities"]["mozilla_ldap_id"]["metadata"]["display"], "staff")
        self.assertEqual(document["identities"]["mozilla_ldap_id"]["signature"]["publisher"]["name"], "ldap")
        self.assertEqual(document["user_id"]["value"], USER_ID)


if __name__ == "__main__":
    import unittest

    unittest.main()
