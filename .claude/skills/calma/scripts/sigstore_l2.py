"""calma.sigstore_l2 - Layer 2 of the attestation chain: Sigstore keyless countersigning.

LAB TIER ONLY. The skill core stays dependency-free; this module is a thin wrapper that uses
sigstore-python WHEN INSTALLED (pip install sigstore) to countersign the exact same in-toto
statement the local key already signed: OIDC identity -> Fulcio short-lived cert -> Rekor
transparency log. The output is a STANDARD Sigstore bundle (attestation.sigstore.json) that a
counterparty verifies with tooling they already trust:

    sigstore verify identity --bundle attestation.sigstore.json \
        --cert-identity <lab-identity> --cert-oidc-issuer <issuer>  attestation.payload.json
    (or cosign verify-blob-attestation / gh attestation verify equivalents)

Because the DSSE payload bytes are identical, the local SSHSIG, the RFC 3161 timestamp, and the
Sigstore log entry all attest the SAME statement - three independent roots of trust over one
verdict. Every Rekor entry is also the free public witness for the catch-history registry: an
independent append-only log operated outside calma already contains each published verdict.

Library: sigstore_sign(bundle, out_path) -> info dict.   Raises ValueError with exact
install/use instructions when sigstore-python is absent (never a bare ImportError).
"""
import base64
import json

INSTALL_HINT = (
    "Sigstore countersigning is the lab tier and needs sigstore-python:\n"
    "    pip install sigstore   (or: uv tool install sigstore)\n"
    "then re-run:  calma attest sigstore <bundle>\n"
    "An OIDC-capable environment is required (browser or ambient credentials - CI OIDC tokens "
    "work). The skill core never requires this dependency.")


def sigstore_sign(bundle, out_path):
    """Keyless-countersign the bundle's DSSE payload into a standard Sigstore bundle at out_path.
    Interactive: opens the OIDC flow unless ambient credentials exist. Returns
    {log_index, identity, out} on success."""
    try:
        from sigstore.dsse import StatementBuilder  # noqa: F401  (presence probe)
        from sigstore.sign import SigningContext
        from sigstore.oidc import Issuer, detect_credential, IdentityToken
    except ImportError:
        raise ValueError(INSTALL_HINT)

    payload = base64.b64decode((bundle.get("envelope") or {}).get("payload", ""))
    if not payload:
        raise ValueError("bundle has no envelope payload")

    token = detect_credential()
    if token:
        identity = IdentityToken(token)
    else:
        identity = Issuer.production().identity_token()
    ctx = SigningContext.production()
    with ctx.signer(identity) as signer:
        # sign the exact statement bytes the local key signed - one payload, N roots of trust
        try:
            result = signer.sign_dsse(payload)  # raw-payload API (newer sigstore-python)
        except (AttributeError, TypeError):
            import sigstore.dsse as _dsse
            result = signer.sign_dsse(_dsse.Statement(payload))  # Statement-wrapping API
    out_json = result.to_json() if hasattr(result, "to_json") else json.dumps(result)
    with open(out_path, "w") as fh:
        fh.write(out_json)
    log_index = None
    try:
        log_index = json.loads(out_json)["verificationMaterial"]["tlogEntries"][0]["logIndex"]
    except (KeyError, IndexError, ValueError, TypeError):
        pass
    return {"out": out_path, "log_index": log_index,
            "identity": str(getattr(identity, "identity", "")) or None}
