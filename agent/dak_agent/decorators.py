import functools
import threading
from typing import Optional, Callable, Any
from .errors import PaymentRequiredError
from .wallets.solana_wallet import get_solana_wallet_manager

# Payment hashes accepted (or being verified) in this process (real mode only).
# Not persisted: a restart or another process accepts them again.
_used_payment_hashes: set[str] = set()
_used_payment_hashes_lock = threading.Lock()

def PaidToolWrapper(price: float, currency: str = "SOL", address: Optional[str] = None):
    """
    Decorator to mark a tool as requiring payment.
    
    Args:
        price: The amount required.
        currency: The currency (default: SOL).
        address: The recipient address. If None, uses the agent's wallet address.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Check if payment_hash is provided
            payment_hash = kwargs.get('payment_hash')
            
            # If payment_hash is provided, verify it on-chain. In real mode a hash
            # accepted once in this process is refused the second time (replay).
            # Mock hashes depend only on amount and recipient, so they are not recorded.
            
            if payment_hash:
                # Verify transaction on-chain using wallet_manager
                wallet = get_solana_wallet_manager()
                
                # If address is not provided, use agent's address
                target_address = address
                if not target_address:
                    target_address = wallet.get_address()

                if not wallet.use_mock:
                    # Reserve the hash before verifying, so a concurrent call with
                    # the same hash is refused; released again if verification fails.
                    with _used_payment_hashes_lock:
                        reused = payment_hash in _used_payment_hashes
                        _used_payment_hashes.add(payment_hash)
                    if reused:
                        raise PaymentRequiredError(
                            price=price,
                            address=target_address,
                            message=f"Payment already used: {payment_hash}",
                            currency=currency
                        )
                    
                verified = False
                try:
                    verified = wallet.verify_transaction(payment_hash, target_address, price)
                finally:
                    if not verified and not wallet.use_mock:
                        _used_payment_hashes.discard(payment_hash)
                if not verified:
                    raise PaymentRequiredError(
                        price=price,
                        address=target_address,
                        message=f"Payment verification failed for hash: {payment_hash}",
                        currency=currency
                    )
                return func(*args, **kwargs)
            
            # If no payment_hash, raise PaymentRequiredError
            target_address = address
            if not target_address:
                # Default to agent's own address
                wallet = get_solana_wallet_manager()
                target_address = wallet.get_address()
                
            raise PaymentRequiredError(
                price=price,
                address=target_address,
                message=f"Payment of {price} {currency} required for {func.__name__}",
                currency=currency
            )
        return wrapper
    return decorator
