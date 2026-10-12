"""Certificates for the broker's own HTTPS front toward Plumb's browser (ADR-0028).

HTTPS from the browser ends at the broker, so the broker can see and check each
request; the broker then makes its own, fully verified connection to the real
server. The browser trusts exactly one key, made for this launch, by its public
key hash. No certificate authority is installed anywhere, nothing is trusted by
any other program, and the key is discarded when the launch ends.
"""

import base64
import hashlib
import ipaddress
import ssl
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def new_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def key_pem(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def certificate(
    key: ec.EllipticCurvePrivateKey,
    host: str,
    *,
    issuer_key: ec.EllipticCurvePrivateKey | None = None,
    issuer: x509.Certificate | None = None,
    authority: bool = False,
) -> x509.Certificate:
    """A short-lived certificate for ``host``: self-signed, or issued by ``issuer``."""
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host[:64])])
    try:
        alternative: x509.GeneralName = x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        alternative = x509.DNSName(host)
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(issuer.subject if issuer is not None else name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=authority, path_length=None), critical=True)
    )
    if not authority:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([alternative]), critical=False
        ).add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
    return builder.sign(issuer_key or key, hashes.SHA256())


def pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def spki_pin(key: ec.EllipticCurvePrivateKey) -> str:
    """Base64 SHA-256 of the public key, as Chromium's per-key trust switch expects."""
    public = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(hashlib.sha256(public).digest()).decode("ascii")


class FrontCertificates:
    """One key per launch, one certificate per approved host, held in a private folder."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._folder = tempfile.TemporaryDirectory(prefix="front-", dir=directory)
        self._key = new_key()
        self._key_path = Path(self._folder.name) / "key.pem"
        self._key_path.write_bytes(key_pem(self._key))
        self._contexts: dict[str, ssl.SSLContext] = {}

    @property
    def pin(self) -> str:
        return spki_pin(self._key)

    def context(self, host: str) -> ssl.SSLContext:
        if host not in self._contexts:
            path = Path(self._folder.name) / (hashlib.sha256(host.encode()).hexdigest() + ".pem")
            path.write_bytes(pem(certificate(self._key, host)))
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.set_alpn_protocols(["http/1.1"])
            context.load_cert_chain(path, self._key_path)
            self._contexts[host] = context
        return self._contexts[host]

    def close(self) -> None:
        self._contexts.clear()
        self._folder.cleanup()
