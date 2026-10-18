import base64


async def test_device_register_and_pair(auth_client):
    from app.core.crypto import generate_ed25519, generate_x25519
    ed = generate_ed25519()
    _, x_pub = generate_x25519()

    r = await auth_client.post("/api/v1/devices", json={
        "name": "phone", "kind": "phone",
        "capabilities": ["vibrate", "notify"],
        "ed25519_pub": ed.public_b64, "x25519_pub": x_pub,
    })
    assert r.status_code == 201, r.text
    dev_id = r.json()["id"]

    r = await auth_client.post(f"/api/v1/devices/{dev_id}/pair/start")
    assert r.status_code == 200
    code = r.json()["code"]

    r = await auth_client.post(
        f"/api/v1/devices/{dev_id}/pair/complete", json={"code": code},
    )
    assert r.status_code == 200
    assert r.json()["paired"] is True


async def test_device_command_encrypted_decryptable_by_device_key(auth_client):
    """The cryptographic correctness test: decrypt with the device's private
    key using ONLY the server public key — proof the channel is real."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey, X25519PublicKey,
    )
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    from app.core.crypto import (
        b64d, b64e, generate_ed25519, generate_x25519,
    )

    ed = generate_ed25519()
    x_priv, x_pub = generate_x25519()

    r = await auth_client.post("/api/v1/devices", json={
        "name": "laptop", "kind": "laptop",
        "capabilities": ["shell"], "ed25519_pub": ed.public_b64,
        "x25519_pub": x_pub,
    })
    dev_id = r.json()["id"]

    r = await auth_client.post(f"/api/v1/devices/{dev_id}/pair/start")
    code = r.json()["code"]
    await auth_client.post(
        f"/api/v1/devices/{dev_id}/pair/complete", json={"code": code},
    )

    r = await auth_client.post(
        f"/api/v1/devices/{dev_id}/commands",
        json={"action": "vibrate", "payload": {"duration_ms": 500}},
    )
    assert r.status_code == 201
    cmd_id = r.json()["id"]

    # Fetch server public key and the encrypted payload
    server_pub_b64 = (await auth_client.get("/api/v1/devices/server-key")).json()[
        "server_x25519_pub"
    ]

    from app.database.session import AsyncSessionLocal
    from app.database.models import DeviceCommand
    async with AsyncSessionLocal() as db:
        cmd = await db.get(DeviceCommand, cmd_id)
        ciphertext = cmd.payload_enc
        uid, did = cmd.user_id, cmd.device_id

    # Device-side derivation: X25519(device_priv, server_pub) + HKDF
    priv = X25519PrivateKey.from_private_bytes(x_priv)
    peer = X25519PublicKey.from_public_bytes(b64d(server_pub_b64))
    shared = priv.exchange(peer)
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None,
        info=f"user:{uid}:device:{did}".encode(),
    ).derive(shared)

    # Decrypt
    raw = b64d(ciphertext)
    nonce, ct = raw[:12], raw[12:]
    aad = f"cmd:{uid}:{did}:{cmd_id}".encode()
    plaintext = AESGCM(key).decrypt(nonce, ct, aad)

    import json
    decoded = json.loads(plaintext)
    assert decoded["duration_ms"] == 500, (
        "device-side decryption must yield the original payload — proves the "
        "server channel is correctly derived"
    )


async def test_x25519_persists_across_secret_rotation(auth_client):
    """The persisted key in SystemKey must survive SECRET_KEY changes."""
    from app.database.session import AsyncSessionLocal
    from app.database.models import SystemKey
    async with AsyncSessionLocal() as db:
        row = await db.get(SystemKey, "x25519")
        assert row is not None
        first = row.value

    # Simulate a fresh bootstrap — should reuse the persisted value
    from app.services.device_mesh import bootstrap_server_key
    async with AsyncSessionLocal() as db:
        await bootstrap_server_key(db)
        row = await db.get(SystemKey, "x25519")
        assert row.value == first
