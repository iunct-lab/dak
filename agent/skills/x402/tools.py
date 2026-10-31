"""
Tools for the x402 skill: fetch external HTTP resources and report x402 payment requirements.
A 402 answer becomes an Observation; nothing is paid or signed by fetch_url (System ENABLES, Agent DECIDES).
pay_x402 pays one requirement fetch_url read; PermissionPlugin asks the user before every call.
"""
import base64
import binascii
import dataclasses
import json
import os

from google.adk.tools.tool_context import ToolContext

from dak_agent import outbound_url
from dak_agent.outbound_url import OutboundURLRefused, outbound_client
from dak_agent.payments.x402 import (
    X402Requirement,
    format_x402_observation,
    parse_payment_required,
    retry_with_payment,
)
from dak_agent.wallets.solana_wallet import keypair_from_secret

# Session-state key: {url: [X402Requirement as dict, ...]} read from the last 402 of each URL.
# DAK-owned (`dak_` prefix, permission.owned_state_keys): a caller cannot plant a requirement to be paid.
STATE_X402_REQUIREMENTS = "dak_x402_requirements"


def fetch_url(url: str, tool_context: ToolContext) -> str:
    """
    Fetch an external HTTP resource with a single GET. Redirects are not followed.

    If the resource answers HTTP 402 (x402), nothing is paid or signed: the payment
    requirement (amount, asset, network, payTo, expires_in) is returned instead.

    Args:
        url: The URL to fetch. Only http / https to a public address; internal addresses are refused.

    Returns:
        "HTTP <status>" and the body, or the payment requirement for a 402 answer.
    """
    # Redirects are refused: the requirement shown must belong to the URL that would be paid
    try:
        with outbound_client(timeout=30.0) as client:
            response = client.get(url)
    except OutboundURLRefused as e:
        return f"Not fetched: {e}"
    if response.status_code != 402:
        return f"HTTP {response.status_code}\n{response.text}"

    try:
        reqs = parse_payment_required(response)
    except ValueError as e:
        return f"HTTP 402 from {url}, but its x402 payment requirement could not be read: {e}"
    # Build a new dict and assign it so that ADK records the state change
    stored = dict(tool_context.state.get(STATE_X402_REQUIREMENTS) or {})
    stored[url] = [dataclasses.asdict(r) for r in reqs]
    tool_context.state[STATE_X402_REQUIREMENTS] = stored
    return format_x402_observation(url, reqs)["error"]


def _decoded_payment_response(value: str) -> str:
    try:
        return json.dumps(json.loads(base64.b64decode(value, validate=True)))
    except (binascii.Error, ValueError):
        return value


def pay_x402(url: str, network: str, asset: str, amount: str, pay_to: str, tool_context: ToolContext) -> str:
    """
    Pay an x402 payment requirement that fetch_url returned for this URL, then fetch it again once.
    The user is asked to approve every call; nothing is paid unless they do.

    Args:
        url: The URL that answered HTTP 402 to fetch_url.
        network: The requirement's network, as fetch_url reported it.
        asset: The requirement's asset, as fetch_url reported it.
        amount: The requirement's amount (smallest unit), as fetch_url reported it.
        pay_to: The requirement's payTo, as fetch_url reported it.

    Returns:
        "HTTP <status>", the decoded PAYMENT-RESPONSE if any, and the body; or why nothing was paid.
    """
    stored = dict(tool_context.state.get(STATE_X402_REQUIREMENTS) or {})
    reqs = [X402Requirement(**r) for r in stored.get(url) or []]
    # Only a requirement fetch_url read: never pay values the model made up
    match = next(
        (r for r in reqs if (r.network, r.asset, r.amount, r.pay_to) == (network, asset, amount, pay_to)), None
    )
    if match is None:
        return f"No x402 requirement from fetch_url matches these values for {url}. Call fetch_url first. Nothing was paid."
    secret = os.getenv("SOLANA_PRIVATE_KEY")
    if not secret:
        return "SOLANA_PRIVATE_KEY is not set. Nothing was paid."
    try:
        keypair = keypair_from_secret(secret)
    except Exception:  # the value is a secret: do not echo it
        return "SOLANA_PRIVATE_KEY could not be read as a Solana key. Nothing was paid."
    rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
    # Checked before signing too: a URL that now resolves inside is not signed for at all.
    # The pinned transport checks again when sending (DNS may change in between)
    try:
        outbound_url.check_outbound_url(url)
    except OutboundURLRefused as e:
        return f"Not paid: {e}"
    # Used up before sending: a resend that fails after the server got it (a timeout) may still be
    # settled, so the same 402 is never signed twice
    kept = dict(stored)
    stored[url] = [dataclasses.asdict(r) for r in reqs if r is not match]
    tool_context.state[STATE_X402_REQUIREMENTS] = stored
    # Reaching this point means PermissionPlugin's confirmation was approved
    try:
        with outbound_client(timeout=30.0) as client:
            response = retry_with_payment(client, url, match, approved=True, keypair=keypair, rpc_url=rpc_url)
    except ValueError as e:  # OutboundURLRefused or a requirement that cannot be signed: nothing was sent
        tool_context.state[STATE_X402_REQUIREMENTS] = kept
        return f"Not paid: {e}"
    lines = [f"HTTP {response.status_code}"]
    payment_response = response.headers.get("PAYMENT-RESPONSE")
    if payment_response:
        lines.append(f"PAYMENT-RESPONSE: {_decoded_payment_response(payment_response)}")
    lines.append(response.text)
    return "\n".join(lines)


X402_TOOLS = [fetch_url, pay_x402]
