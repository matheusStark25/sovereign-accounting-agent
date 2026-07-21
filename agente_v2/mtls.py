from __future__ import annotations
from typing import Optional
import ssl


def create_ssl_context(
    certfile: Optional[str] = None,
    keyfile: Optional[str] = None,
    cafile: Optional[str] = None,
) -> ssl.SSLContext:
    """Create an SSLContext for mTLS client/server use.

    Provide `certfile` and `keyfile` for client cert; `cafile` for CA bundle.
    """
    ctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH, cafile=cafile)
    if certfile and keyfile:
        ctx.load_cert_chain(certfile, keyfile)
    # require server cert verification
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx
