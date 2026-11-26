"""Run with python -m unittest discover -s scripts -p test_g8_evidence.py.

Set GITLEAKS_BINARY to run the actual scanner controls (not a mock).
"""

import hashlib
import json
import os
import secrets
import tempfile
import unittest
from pathlib import Path

from audit_g8_gitleaks import audit, git
from g8_evidence import append_record, normalize_record, read_manifest, source_manifest


class EvidenceTests(unittest.TestCase):
    def test_all_historical_findings_recompute_and_unknown_value_is_not_verified(self):
        root = Path(__file__).resolve().parents[1]
        proofs = json.loads((root / "reports/g8/security/source-proof.json").read_text())
        findings = []
        for proof in proofs:
            record = json.loads(
                git("show", proof["commit"] + ":" + proof["trace"]).splitlines()[proof["line"] - 1]
            )
            value = record
            for part in proof["traceField"]:
                value = value[part]
            findings.append(
                {
                    "Commit": proof["commit"],
                    "File": proof["trace"],
                    "StartLine": proof["line"],
                    "RuleID": proof["rule"],
                    "Fingerprint": proof["fingerprint"],
                    "Secret": value,
                }
            )
        checked = audit(findings)
        self.assertEqual(len(checked), 22)
        self.assertTrue(all(p["status"] == "verified_source_digest" for p in checked))
        findings[0]["Secret"] = secrets.token_hex(32)
        self.assertEqual(audit(findings[:1])[0]["status"], "unconfirmed")

    def test_legacy_and_new_manifest_have_identical_meaning(self):
        old = {"backend/chatbot/app/core/auth.py": hashlib.sha256(b"source").hexdigest()}
        record = normalize_record({"sourceSha256": old, "tasks": [{"status": "partial"}]})
        self.assertEqual(read_manifest(record["sourceSha256"]), old)
        self.assertEqual(record["tasks"], [{"status": "partial"}])
        self.assertEqual(old, read_manifest(old))

    def test_hash_exact_bytes_and_reject_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = b"line1\r\nline2\r\n"
            (root / "auth.py").write_bytes(data)
            self.assertEqual(
                source_manifest(root, ["auth.py"])[0]["sha256"], hashlib.sha256(data).hexdigest()
            )
            with self.assertRaises(ValueError):
                source_manifest(root, ["../outside.py"])

    def test_invalid_manifest_rejected(self):
        for value in [
            {"../auth.py": "f" * 64},
            {"auth.py": "not-a-hash"},
            [{"path": "a.py", "sha256": "f" * 64}] * 2,
        ]:
            with self.assertRaises(ValueError):
                read_manifest(value)

    @unittest.skipUnless(os.environ.get("GITLEAKS_BINARY"), "actual Gitleaks binary not set")
    def test_scanned_append_preserves_history_and_rejects_synthetic_secret(self):
        scanner = os.environ["GITLEAKS_BINARY"]
        config = Path(__file__).resolve().parents[1] / ".gitleaks.toml"
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "trace.jsonl"
            prefix = b'{"oldEvidence":true}\n'
            target.write_bytes(prefix)
            good = {
                "sourceSha256": {
                    "backend/chatbot/app/core/auth.py": hashlib.sha256(b"source").hexdigest()
                }
            }
            append_record(target, good, scanner=scanner, config=config)
            saved = target.read_bytes()
            self.assertTrue(saved.startswith(prefix))
            self.assertEqual(
                read_manifest(json.loads(saved.splitlines()[1])["sourceSha256"]),
                good["sourceSha256"],
            )
            # Random fake token is created at runtime, never printed or committed.
            for field in ("api_key", "token"):
                with self.assertRaises(ValueError):
                    append_record(
                        target, {field: secrets.token_hex(24)}, scanner=scanner, config=config
                    )
                self.assertEqual(target.read_bytes(), saved)
            with self.assertRaises(ValueError):
                append_record(target, good, scanner=scanner, config=Path(folder) / "missing.toml")
            self.assertEqual(target.read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
