"""Unit tests for mono_cis.publishers.ldap, with the ``boto3`` module and neighbours mocked."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import call, patch

from botocore.exceptions import ClientError

from tests import support
from tests.support import PublisherTestCase, ldap_users, xz

from mono_cis.publishers import ldap
from mono_cis.publishers.common.profile import InactiveProfileException, ProfileNotFoundException

BUCKET = "cache.ldap.sso.mozilla.com"
KEY_XZ = "ldap_users.json.xz"
KEY_JSON = "ldap_users.json"
ERROR_RESPONSE = {"statusCode": 500, "body": json.dumps({"error": "Invalid LDAP export"})}


class GetLdapDumpTests(PublisherTestCase):
    def setUp(self):
        super().setUp()
        self.users = ldap_users()

    def test_reads_a_local_json_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / KEY_JSON
            path.write_text(json.dumps(self.users))

            self.assertEqual(ldap.get_ldap_dump(filename=str(path)), self.users)

    def test_missing_local_file_is_an_error(self):
        with self.assertRaises(FileNotFoundError) as raised:
            ldap.get_ldap_dump(filename="/nonexistent/ldap_users.json")

        self.assertIn("Cannot open /nonexistent/ldap_users.json", str(raised.exception))

    def test_reads_a_compressed_dump_from_s3(self):
        os.environ["LDAP_CACHE_S3_KEY"] = KEY_XZ
        boto3 = self.patch_boto3(xz(self.users))

        self.assertEqual(ldap.get_ldap_dump(bucket=BUCKET, key=KEY_XZ), self.users)
        boto3.client.assert_called_once_with("s3")
        boto3.client.return_value.get_object.assert_called_once_with(Bucket=BUCKET, Key=KEY_XZ)

    def test_reads_a_plain_dump_from_s3(self):
        os.environ["LDAP_CACHE_S3_KEY"] = KEY_JSON
        boto3 = self.patch_boto3(json.dumps(self.users).encode())

        self.assertEqual(ldap.get_ldap_dump(bucket=BUCKET, key=KEY_JSON), self.users)
        boto3.client.return_value.get_object.assert_called_once_with(Bucket=BUCKET, Key=KEY_JSON)

    def test_compression_is_decided_by_the_environment_not_the_key_argument(self):
        # Preserved quirk: the ``.xz`` check reads LDAP_CACHE_S3_KEY, not ``key``.
        os.environ["LDAP_CACHE_S3_KEY"] = KEY_JSON
        boto3 = self.patch_boto3(json.dumps(self.users).encode())

        self.assertEqual(ldap.get_ldap_dump(bucket=BUCKET, key="other.json.xz"), self.users)
        boto3.client.return_value.get_object.assert_called_once_with(Bucket=BUCKET, Key="other.json.xz")

    def test_missing_s3_object_propagates(self):
        os.environ["LDAP_CACHE_S3_KEY"] = KEY_XZ
        self.patch_boto3(None)

        with self.assertRaises(ClientError):
            ldap.get_ldap_dump(bucket=BUCKET, key=KEY_XZ)

    def test_without_arguments_returns_none(self):
        self.assertIsNone(ldap.get_ldap_dump())


class SynchronizeTests(PublisherTestCase):
    def setUp(self):
        super().setUp()
        self.ldap_profile = ldap_users()["astaff@mozilla.com"]

    def synchronize(self, email="astaff@mozilla.com", ldap_profile=None, raises=None):
        """
        Run synchronize() against an autospecced ``Profile``. The instance's two nested sections are real
        dicts so what synchronize() writes into them can be asserted directly.

        :return: (result, Profile mock, sections)
        """
        sections = {"access_information": {}, "identities": {}}
        with patch.object(ldap, "Profile", autospec=True) as Profile:
            Profile.return_value.__getitem__.side_effect = sections.__getitem__
            if raises is not None:
                Profile.side_effect = raises
            result = ldap.synchronize(email, ldap_profile if ldap_profile is not None else self.ldap_profile)
        return result, Profile, sections

    def test_updates_and_publishes_a_staff_profile(self):
        result, Profile, sections = self.synchronize()

        self.assertIs(result, True)
        Profile.assert_called_once_with(email="astaff@mozilla.com")
        # Phone numbers are computed but, as upstream, never written to the profile.
        Profile.return_value.update.assert_called_once_with(
            {
                "pgp_public_keys": {"LDAP-1": "0x0123456789ABCDEF", "LDAP-2": "0xFEDCBA9876543210"},
                "ssh_public_keys": {
                    "LDAP-1": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeKeyOneFakeKeyOneFakeKeyOneFakeKeyOne astaff@laptop",
                    "LDAP-2": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQFakeKeyTwo astaff@desktop",
                },
            }
        )
        self.assertEqual(sections["access_information"], {"ldap": ["vpn_default", "all_staff", "team_iam"]})
        self.assertEqual(
            sections["identities"],
            {
                "mozilla_ldap_id": "mail=astaff@mozilla.com,o=com,dc=mozilla",
                "mozilla_ldap_primary_email": "astaff@mozilla.com",
                "mozilla_posix_id": "astaff",
            },
        )
        Profile.return_value.publish.assert_called_once_with(display_level="staff")

    def test_pgp_keys_are_normalised(self):
        cases = {
            "0x0123456789ABCDEF": "0x0123456789ABCDEF",
            "FEDC BA98 7654 3210": "0xFEDCBA9876543210",
            "0xABCD EF01": "0xABCDEF01",
            "abcd": "0xabcd",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                _, Profile, _ = self.synchronize(ldap_profile={**self.ldap_profile, "pgp_public_keys": [raw]})

                (update,) = Profile.return_value.update.call_args.args
                self.assertEqual(update["pgp_public_keys"], {"LDAP-1": expected})

    def test_display_level_follows_the_distinguished_name(self):
        cases = {
            "mail=a@mozilla.com,o=com,dc=mozilla": "staff",
            "mail=a@mozilla.org,o=org,dc=mozilla": "staff",
            "mail=a@mozilla.net,o=net,dc=mozilla": "private",
        }
        for dn, expected in cases.items():
            with self.subTest(dn=dn):
                _, Profile, _ = self.synchronize(ldap_profile={**self.ldap_profile, "distinguished_name": dn})

                Profile.return_value.publish.assert_called_once_with(display_level=expected)

    def test_optional_ldap_fields_may_be_absent(self):
        minimal = {"distinguished_name": "mail=min@mozilla.com,o=com,dc=mozilla", "user_id": "ad|Mozilla-LDAP|min"}

        result, Profile, sections = self.synchronize(email="min@mozilla.com", ldap_profile=minimal)

        self.assertIs(result, True)
        Profile.return_value.update.assert_called_once_with({"pgp_public_keys": {}, "ssh_public_keys": {}})
        self.assertEqual(sections["access_information"], {"ldap": None})
        self.assertEqual(
            sections["identities"],
            {
                "mozilla_ldap_id": "mail=min@mozilla.com,o=com,dc=mozilla",
                "mozilla_ldap_primary_email": "min@mozilla.com",
                "mozilla_posix_id": None,
            },
        )

    def test_inactive_profile_is_reported_as_desynced(self):
        result, Profile, _ = self.synchronize(raises=InactiveProfileException())

        self.assertIs(result, False)
        Profile.return_value.publish.assert_not_called()

    def test_unknown_profile_is_reported_as_desynced(self):
        result, Profile, _ = self.synchronize(raises=ProfileNotFoundException("nope"))

        self.assertIs(result, False)
        Profile.return_value.publish.assert_not_called()

    def test_other_errors_propagate(self):
        # Preserved behaviour: anything else escapes, and main() re-raises it from future.result().
        with self.assertRaises(RuntimeError):
            self.synchronize(raises=RuntimeError("boom"))


class MainTests(PublisherTestCase):
    def setUp(self):
        super().setUp()
        self.users = ldap_users()

    def write_local_dump(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / KEY_JSON
        path.write_text(json.dumps(self.users))
        return str(path)

    def expected_synchronize_calls(self):
        return [call(email, ldap_profile) for email, ldap_profile in self.users.items()]

    def test_without_a_dump_location_returns_the_error_response(self):
        self.assertEqual(ldap.main(), ERROR_RESPONSE)

    def test_unreadable_s3_dump_returns_the_error_response(self):
        os.environ["LDAP_CACHE_S3_BUCKET"] = BUCKET
        os.environ["LDAP_CACHE_S3_KEY"] = KEY_XZ
        self.patch_boto3(None)

        with patch.object(ldap, "synchronize", autospec=True) as synchronize:
            self.assertEqual(ldap.main(), ERROR_RESPONSE)

        synchronize.assert_not_called()

    def test_missing_local_dump_returns_the_error_response(self):
        os.environ["LDAP_CACHE_FILENAME"] = "/nonexistent/ldap_users.json"

        self.assertEqual(ldap.main(), ERROR_RESPONSE)

    def test_synchronizes_every_user_from_a_local_dump(self):
        os.environ["LDAP_CACHE_FILENAME"] = self.write_local_dump()

        with patch.object(ldap, "synchronize", autospec=True, side_effect=[True, False, False]) as synchronize:
            result = ldap.main()

        self.assertIsNone(result)
        # Workers run concurrently, so the recorded order is not meaningful.
        self.assertCountEqual(synchronize.call_args_list, self.expected_synchronize_calls())

    def test_reads_the_dump_from_s3_when_a_bucket_is_set(self):
        os.environ["LDAP_CACHE_S3_BUCKET"] = BUCKET
        os.environ["LDAP_CACHE_S3_KEY"] = KEY_XZ
        boto3 = self.patch_boto3(xz(self.users))

        with patch.object(ldap, "synchronize", autospec=True, return_value=True) as synchronize:
            self.assertIsNone(ldap.main())

        boto3.client.return_value.get_object.assert_called_once_with(Bucket=BUCKET, Key=KEY_XZ)
        self.assertCountEqual(synchronize.call_args_list, self.expected_synchronize_calls())

    def test_s3_wins_over_a_local_file(self):
        os.environ["LDAP_CACHE_S3_BUCKET"] = BUCKET
        os.environ["LDAP_CACHE_S3_KEY"] = KEY_XZ
        os.environ["LDAP_CACHE_FILENAME"] = "/nonexistent/ldap_users.json"
        boto3 = self.patch_boto3(xz(self.users))

        with patch.object(ldap, "synchronize", autospec=True, return_value=True):
            self.assertIsNone(ldap.main())

        boto3.client.return_value.get_object.assert_called_once_with(Bucket=BUCKET, Key=KEY_XZ)

    def test_a_worker_exception_propagates(self):
        # Preserved behaviour: main() re-raises from future.result() instead of counting a failure.
        os.environ["LDAP_CACHE_FILENAME"] = self.write_local_dump()

        with patch.object(ldap, "synchronize", autospec=True, side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                ldap.main()


class HandleTests(PublisherTestCase):
    def test_handle_runs_main_and_returns_none(self):
        with patch.object(ldap, "main", autospec=True, return_value=None) as main:
            self.assertIsNone(ldap.handle({"source": "aws.events"}, context=None))

        main.assert_called_once_with()

    def test_handle_discards_the_error_response(self):
        # Preserved behaviour: the Lambda entrypoint never surfaced main()'s result.
        with patch.object(ldap, "main", autospec=True, return_value=ERROR_RESPONSE):
            self.assertIsNone(ldap.handle({}))


class CliTests(PublisherTestCase):
    def setUp(self):
        super().setUp()
        os.environ.pop("PUBLISHER_NAME", None)

    def test_applies_the_publisher_defaults_and_exits_zero(self):
        with patch.object(ldap, "main", autospec=True, return_value=None) as main:
            self.assertEqual(ldap.cli(), 0)

        main.assert_called_once_with()
        self.assertEqual(os.environ["PUBLISHER_NAME"], "ldap")
        self.assertEqual(os.environ["LDAP_CACHE_S3_BUCKET"], BUCKET)
        self.assertEqual(os.environ["LDAP_CACHE_S3_KEY"], KEY_XZ)

    def test_never_overrides_explicit_values(self):
        os.environ["PUBLISHER_NAME"] = "ldap-canary"
        os.environ["LDAP_CACHE_S3_BUCKET"] = "another-bucket"
        os.environ["LDAP_CACHE_S3_KEY"] = "another.json"

        with patch.object(ldap, "main", autospec=True, return_value=None):
            ldap.cli()

        self.assertEqual(os.environ["PUBLISHER_NAME"], "ldap-canary")
        self.assertEqual(os.environ["LDAP_CACHE_S3_BUCKET"], "another-bucket")
        self.assertEqual(os.environ["LDAP_CACHE_S3_KEY"], "another.json")

    def test_local_cache_suppresses_the_s3_defaults(self):
        os.environ["LDAP_CACHE_FILENAME"] = "/tmp/ldap_users.json"

        with patch.object(ldap, "main", autospec=True, return_value=None):
            ldap.cli()

        self.assertNotIn("LDAP_CACHE_S3_BUCKET", os.environ)
        self.assertNotIn("LDAP_CACHE_S3_KEY", os.environ)
        self.assertEqual(os.environ["PUBLISHER_NAME"], "ldap")

    def test_error_response_exits_one(self):
        with patch.object(ldap, "main", autospec=True, return_value=ERROR_RESPONSE):
            self.assertEqual(ldap.cli(), 1)


if __name__ == "__main__":
    import unittest

    unittest.main()
