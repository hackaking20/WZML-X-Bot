#!/usr/bin/env python3
"""Build vault.json for the Amaterasu hub, from the command line.

The browser tool (vault-maker.html) does the same thing without installing
anything; this exists for scripting and for CI, which checks that a
committed vault really is ciphertext.

    python3 scripts/make-vault.py payload.json --hint "the usual one" > vault.json

The passphrase is read from $VAULT_PASSPHRASE, or prompted for.
"""

import argparse
import base64
import getpass
import hashlib
import json
import os
import sys

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
except ImportError:
    sys.exit("needs the 'cryptography' package: pip install cryptography")

ITERATIONS = 310_000


def derive(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS
    )
    return kdf.derive(passphrase.encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", help="JSON file with the pages list")
    parser.add_argument("--hint", default="", help="hint shown on the lock screen")
    parser.add_argument("--out", default="-", help="where to write vault.json")
    parser.add_argument("--demo", action="store_true", help="mark it as a demo vault")
    args = parser.parse_args()

    with open(args.payload, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not payload.get("pages"):
        return print("payload needs a 'pages' array") or 1

    passphrase = os.environ.get("VAULT_PASSPHRASE") or getpass.getpass("passphrase: ")
    if len(passphrase) < 12:
        return print("passphrase must be at least 12 characters") or 1

    salt = os.urandom(16)
    iv = os.urandom(12)
    key = derive(passphrase, salt)
    cipher = AESGCM(key).encrypt(iv, json.dumps(payload).encode("utf-8"), None)

    payload_text = json.dumps(payload)
    vault = {
        "v": 1,
        "digest": hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
        "kdf": {
            "name": "PBKDF2",
            "hash": "SHA-256",
            "iter": ITERATIONS,
            "salt": base64.b64encode(salt).decode(),
        },
        "iv": base64.b64encode(iv).decode(),
        "hint": args.hint,
        "data": base64.b64encode(cipher).decode(),
    }
    if args.demo:
        vault["demo"] = True

    text = json.dumps(vault, indent=2) + "\n"
    if args.out == "-":
        sys.stdout.write(text)
    else:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"wrote {args.out} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
