from abc import ABC, abstractmethod
from typing import Optional

class BaseWalletManager(ABC):
    """
    Abstract base class for blockchain wallet managers.
    """

    @abstractmethod
    def get_balance(self) -> float:
        """Fetch the current balance."""
        pass

    @abstractmethod
    def get_address(self) -> str:
        """Get the wallet's public address."""
        pass

    @abstractmethod
    def send_transaction(self, recipient_address: str, amount: float, message: str = "") -> str:
        """
        Send a transaction.
        Returns the transaction hash/signature.
        """
        pass

    @abstractmethod
    def verify_transaction(self, tx_hash: str, expected_recipient: str, expected_amount: float) -> bool:
        """
        Verify if a transaction has been confirmed and matches the expected details.
        """
        pass
