import base64
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from solders.keypair import Keypair

# litellm fetches its model map (context windows, prices) from the network at
# import unless told otherwise, so an upstream edit could fail these tests
# with no change here (#618). Use the map shipped with the locked litellm.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")


# 偽の Solana RPC が答える値（x402 の署名のテスト）
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
BLOCKHASH = "EkSnNWid2cvwEVnVx9aBqawnmiCNiDgp3gUdkDPTKN1N"


@pytest.fixture
def fake_solana_rpc():
    """getAccountInfo（decimals 6 の SPL の mint）と getLatestBlockhash に答える偽の JSON-RPC。"""
    calls: list[str] = []
    mint_data = bytearray(82)
    mint_data[44] = 6

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(req["method"])
            context = {"slot": 1}
            if req["method"] == "getAccountInfo":
                result = {
                    "context": context,
                    "value": {
                        "data": [base64.b64encode(bytes(mint_data)).decode(), "base64"],
                        "executable": False,
                        "lamports": 1461600,
                        "owner": TOKEN_PROGRAM,
                        "rentEpoch": 0,
                        "space": 82,
                    },
                }
            elif req["method"] == "getLatestBlockhash":
                result = {"context": context, "value": {"blockhash": BLOCKHASH, "lastValidBlockHeight": 100}}
            else:
                result = None
            body = json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield {"url": f"http://127.0.0.1:{httpd.server_address[1]}", "calls": calls}
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def keypair():
    """テストの実行時に作る使い捨ての鍵。"""
    return Keypair()
