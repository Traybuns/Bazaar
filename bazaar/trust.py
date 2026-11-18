"""Ed25519 signing and verification for agent manifests and booking receipts."""
import base64, json
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def new_private_key() -> str:
    sk = Ed25519PrivateKey.generate()
    return _b64(sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))


def public_key_of(private_b64: str) -> str:
    sk = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64))
    return _b64(sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def sign(private_b64: str, payload: dict) -> str:
    sk = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64))
    return _b64(sk.sign(canonical(payload)))


def verify(public_b64: str, payload: dict, signature_b64: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_b64)).verify(
            base64.b64decode(signature_b64), canonical(payload))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def sign_manifest(manifest: dict, private_b64: str) -> dict:
    """The public key sits inside the signed body, so swapping the key breaks the signature."""
    body = {k: v for k, v in manifest.items() if k != "verification"}
    ver = {"alg": "ed25519", "public_key": public_key_of(private_b64), "signed_by": "self"}
    signature = sign(private_b64, {**body, "verification": ver})
    return {**body, "verification": {**ver, "signature": signature}}


def verify_manifest(manifest: dict) -> bool:
    ver = manifest.get("verification") or {}
    if not ver.get("signature") or not ver.get("public_key"):
        return False
    unsigned = {**manifest, "verification": {k: v for k, v in ver.items() if k != "signature"}}
    return verify(ver["public_key"], unsigned, ver["signature"])
