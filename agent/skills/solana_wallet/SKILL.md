---
name: solana_wallet
description: "Manage a Solana blockchain wallet for AP2/x402 payments. Check balance, send SOL, and verify transactions."
tools:
  - check_solana_balance
  - get_solana_address
  - send_sol_payment
  - verify_sol_payment
---
You have access to a Solana blockchain wallet.

# AP2 Protocol - Payment Decision
You may be asked to make payments. Before paying:
1. Check your balance with `check_solana_balance()`
2. Only pay if user has explicitly authorized the payment
3. Do NOT auto-pay without consent

# Available Actions
- `check_solana_balance()` - View current SOL balance
- `get_solana_address()` - Get your wallet address
- `send_sol_payment(recipient, amount)` - Send SOL after authorization
- `verify_sol_payment(tx_signature)` - Verify a transaction
