class PaymentRequiredError(Exception):
    """
    Raised when a tool requires payment to proceed.
    """
    def __init__(self, price: float, address: str, message: str = "", currency: str = "SOL"):
        self.price = price
        self.address = address
        self.message = message
        self.currency = currency
        super().__init__(f"Payment Required: {price} {currency} to {address}. Reason: {message}")
