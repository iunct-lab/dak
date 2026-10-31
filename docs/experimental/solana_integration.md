# Solana Integration for AP2/x402 Protocol

This module integrates **Solana blockchain** into the Decentralized Agent Kit for an experimental, custom payment flow modelled on AP2 and x402. It is not a compliant implementation of either standard.

## Key Difference: LLM Decides Payments

Unlike auto-payment systems, this implementation follows AP2 principles:

> **"Verifiable Intent, Not Inferred Action"**

The LLM receives payment requests and **decides** whether to pay based on:
- User consent
- Intent Mandate (pre-authorized conditions)

**No automatic payment occurs.**

---

## Configuration

```bash
# Enable mock mode for development (no real transactions)
SOLANA_USE_MOCK=true

# Network: devnet, mainnet, or custom RPC URL
SOLANA_NETWORK=devnet

# Private key (base58 or JSON array format)
#SOLANA_PRIVATE_KEY=your_key_here

# Custom RPC (optional)
#SOLANA_RPC_URL=https://api.devnet.solana.com
```

---

## Available Tools

| Tool | Description |
|------|-------------|
| `check_solana_balance()` | Check SOL balance |
| `get_solana_address()` | Get wallet public address |
| `send_sol_payment(recipient, amount)` | Send SOL to recipient |
| `verify_sol_payment(tx_signature, ...)` | Verify transaction on-chain |

---

## Payment Flow

```
1. Tool raises PaymentRequiredError
2. _on_tool_error informs LLM of payment details
3. LLM decides: ask user OR call send_sol_payment
4. After payment: LLM retries tool with payment_hash
```

---

## Payment Verification (real mode)

With `SOLANA_USE_MOCK=false`, a paid tool (`PaidToolWrapper`) runs only when the
`payment_hash` passes these checks (`verify_sol_payment` uses the same checks
but does not mark the hash as used):

- The transaction succeeded (its meta has no `err`).
- The recipient's balance grew in that transaction.
- It grew by at least the price (converted to lamports).
- The hash was not already accepted by this agent process. A second use of the
  same hash (再利用（replay）) is refused with `PaymentRequiredError`.
  A hash that failed verification is not recorded and can be retried.
- When the check cannot be made (RPC error, transaction not found), the payment
  is refused.

What it does **not** check:

- Replay across a restart or across processes (for example parallel Lambda
  invocations): the used hashes live only in the memory of one process.
- That the payer and the caller of the tool are the same: the first use of
  someone else's transaction with the right recipient and amount is accepted.
- That the RPC node itself answers truthfully.

Mock mode (`SOLANA_USE_MOCK=true`, the default) checks none of this: it accepts
any hash starting with `MockTx` and does not refuse reuse (a mock hash depends
only on the amount and recipient, so two genuine payments of the same amount
share it). No real funds move in mock mode.

---

## Payment Intent Check (optional)

The user can sign the limits of what the agent may pay — "at most this much",
"only to these addresses" — and DAK refuses any `send_sol_payment` outside them
**before the transfer runs**. The intent is a Verifiable Intent v0.1 L2 SD-JWT
narrowed to DAK's profile. What is checked, where DAK deliberately differs from
the spec, and how DAK's payment flow ("AP2" in this repository: Agent-to-Agent
Payment Protocol) differs from Google's AP2 (Agent Payments Protocol) are in
[docs/design/verifiable_intent.md](../design/verifiable_intent.md).

```bash
# Off by default: the payment flow above is unchanged.
ENABLE_PAYMENT_INTENT_CHECK=true

# The user's PUBLIC key(s) as a JWKS JSON string (EC, P-256, ES256).
DAK_PAYMENT_INTENT_TRUSTED_JWKS='{"keys":[{"kty":"EC","crv":"P-256","kid":"user-1","x":"...","y":"..."}]}'
```

- **Keys**: only public keys go in `DAK_PAYMENT_INTENT_TRUSTED_JWKS`. The user
  keeps the private key that signs intents; never put it in the repository, in
  `env.example.d/`, or in the agent's environment. When the check is on but the
  JWKS is missing or unusable, the agent still starts and blocks every payment
  (it logs why).
- **Passing the intent**: the caller puts the SD-JWT (`<JWS>~<disclosure>~...~`,
  every disclosure attached) in the session state under `dak:payment_intent`,
  e.g. when creating the session:
  `POST /apps/dak_agent/users/{user}/sessions` with `{"state": {"dak:payment_intent": "<SD-JWT>"}}`.
  No agent tool writes this key.
- **Constraints**: `payment.amount` (`currency: "SOL"`, `min` / `max` in
  lamports, 1 SOL = 10^9) and `payment.allowed_payee` (exact match on
  `allowed_payees[].id`, the base58 address). Any other constraint type
  rejects the intent. The signature must be ES256; `exp` / `iat` allow 300 s of
  clock skew.
- **When blocked**, the tool is not run and the model gets an Observation:

```json
{"error": "Payment blocked by payment intent: amount 1500000000 is above max 1000000000 (constraint: payment.amount). Ask the user to review their payment intent."}
```

The check only blocks. It never starts, approves or retries a payment; the
permission rules (`PermissionPlugin`) still run first.

---

## Testing

```bash
cd agent && uv run python -c "
import os
os.environ['SOLANA_USE_MOCK'] = 'true'
from skills.solana_wallet.tools import check_solana_balance
print(check_solana_balance())
"
```

Output:
```
## Solana Wallet Balance
**Address**: `MockSoLAddress...`
**Balance**: 10.000000 SOL
**Network**: devnet
```

---

## Files

| File | Description |
|------|-------------|
| `dak_agent/solana_wallet_manager.py` | Core wallet operations |
| `skills/solana_wallet/tools.py` | Agent tools |
| `skills/solana_wallet/skill.yaml` | Skill definition |
