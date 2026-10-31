from typing import Optional
from dak_agent.decorators import PaidToolWrapper
import logging

logger = logging.getLogger(__name__)

@PaidToolWrapper(price=10.0)
def perform_premium_analysis(topic: str, payment_hash: Optional[str] = None) -> str:
    """
    Perform a premium analysis on a given topic. Requires 10 SOL payment.
    Args:
        topic: The subject to analyze.
        payment_hash: The transaction hash of the payment (from send_sol_payment).
    """
    logger.info(f"Performing premium analysis on: {topic}")
    return f"""
    # PREMIUM ANALYSIS REPORT: {topic}
    
    **Payment Verified**: {payment_hash}
    **Status**: COMPLETED
    
    ## Executive Summary
    This is a high-value, exclusive insight generated specifically for you.
    The future of '{topic}' looks promising, driven by decentralized autonomous agents.
    
    ## Key Findings
    1. Market demand is rising.
    2. Technology is maturing.
    3. Early adopters (like you) will benefit most.
    
    Thank you for your business!
    """
