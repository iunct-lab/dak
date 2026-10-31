"""Stand-ins for the x402 integration tests (test_x402_flow.py), one app with three roles:

- the paid resource: GET /paid answers 402 with a v2 PAYMENT-REQUIRED, or, with a
  PAYMENT-SIGNATURE, asks its facilitator (/verify, /settle, over HTTP) and answers 200
- the facilitator: POST /verify checks the payer's signature and the accepted requirement,
  POST /settle answers a fixed transaction (nothing is sent anywhere)
- the Solana RPC: POST /rpc answers getAccountInfo (an SPL mint, 6 decimals) and getLatestBlockhash

GET /stats counts requests per path; POST /reset clears them. The payee and fee-payer keys
are made at startup; no key is in the repository. Nothing here reaches a real network.
"""
import base64
import json

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# The name the agent fetches: a dotted name on the test-only network x402net (compose/test/x402.yml),
# so it passes the agent's destination check (agent/dak_agent/outbound_url.py) without an allowlist
RESOURCE_URL = "http://paid.x402.test:8080/paid"
SOLANA_DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
USDC_DEVNET_MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
BLOCKHASH = "EkSnNWid2cvwEVnVx9aBqawnmiCNiDgp3gUdkDPTKN1N"
SETTLED_TX = "5fakeSettledTransaction1111111111111111111111111111111111111111111"
FACILITATOR_URL = "http://127.0.0.1:8080"

REQUIREMENT = {
    "scheme": "exact",
    "network": SOLANA_DEVNET,
    "amount": "10000",
    "asset": USDC_DEVNET_MINT,
    "payTo": str(Keypair().pubkey()),
    "maxTimeoutSeconds": 60,
    "extra": {"feePayer": str(Keypair().pubkey())},
}

app = FastAPI()
stats: dict[str, int] = {}


def _count(key: str) -> None:
    stats[key] = stats.get(key, 0) + 1


def _b64(value: dict) -> str:
    return base64.b64encode(json.dumps(value).encode()).decode()


def _payment_required() -> Response:
    body = {"x402Version": 2, "resource": {"url": RESOURCE_URL}, "accepts": [REQUIREMENT]}
    return JSONResponse({}, status_code=402, headers={"PAYMENT-REQUIRED": _b64(body)})


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/stats")
def get_stats():
    return {"counts": stats, "requirement": REQUIREMENT, "resource": RESOURCE_URL}


@app.post("/reset")
def reset():
    stats.clear()
    return {"ok": True}


@app.get("/paid")
async def paid(request: Request):
    _count("/paid")
    signature = request.headers.get("PAYMENT-SIGNATURE")
    if signature is None:
        return _payment_required()
    _count("/paid:signed")
    try:
        payload = json.loads(base64.b64decode(signature, validate=True))
    except ValueError:
        return _payment_required()
    if not isinstance(payload, dict):
        return _payment_required()
    body = {"x402Version": 2, "paymentPayload": payload, "paymentRequirements": REQUIREMENT}
    async with httpx.AsyncClient(base_url=FACILITATOR_URL, timeout=10.0) as client:
        verified = (await client.post("/verify", json=body)).json()
        if not verified.get("isValid"):
            return _payment_required()
        settled = (await client.post("/settle", json=body)).json()
    return JSONResponse({"data": "premium"}, headers={"PAYMENT-RESPONSE": _b64(settled)})


def _payer_if_valid(body: dict) -> str | None:
    payload = body.get("paymentPayload") if isinstance(body, dict) else None
    if not isinstance(payload, dict) or payload.get("x402Version") != 2 or payload.get("accepted") != REQUIREMENT:
        return None
    try:
        tx = VersionedTransaction.from_bytes(base64.b64decode(payload["payload"]["transaction"]))
    except (KeyError, TypeError, ValueError):
        return None
    keys = tx.message.account_keys
    # Signer 0 is the fee payer (the facilitator signs at settle), signer 1 the payer
    if len(keys) < 2 or len(tx.signatures) < 2 or str(keys[0]) != REQUIREMENT["extra"]["feePayer"]:
        return None
    if not tx.signatures[1].verify(keys[1], bytes([0x80]) + bytes(tx.message)):
        return None
    return str(keys[1])


@app.post("/verify")
async def verify(request: Request):
    _count("/verify")
    payer = _payer_if_valid(await request.json())
    if payer is None:
        return {"isValid": False, "invalidReason": "invalid_payload"}
    return {"isValid": True, "payer": payer}


@app.post("/settle")
async def settle(request: Request):
    _count("/settle")
    payer = _payer_if_valid(await request.json())
    if payer is None:
        return {"success": False, "errorReason": "invalid_payload", "transaction": "", "network": SOLANA_DEVNET}
    return {"success": True, "transaction": SETTLED_TX, "network": SOLANA_DEVNET, "payer": payer}


@app.post("/rpc")
async def rpc(request: Request):
    req = await request.json()
    _count(f"/rpc:{req.get('method')}")
    context = {"slot": 1}
    if req.get("method") == "getAccountInfo":
        data = bytearray(82)
        data[44] = 6  # decimals
        result = {
            "context": context,
            "value": {
                "data": [base64.b64encode(bytes(data)).decode(), "base64"],
                "executable": False,
                "lamports": 1461600,
                "owner": TOKEN_PROGRAM,
                "rentEpoch": 0,
                "space": 82,
            },
        }
    elif req.get("method") == "getLatestBlockhash":
        result = {"context": context, "value": {"blockhash": BLOCKHASH, "lastValidBlockHeight": 100}}
    else:
        return {"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32601, "message": "method not found"}}
    return {"jsonrpc": "2.0", "id": req.get("id"), "result": result}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
