"""PaidToolWrapper の支払いの確かめ方。wallet は偽物に差し替える。"""
from unittest.mock import MagicMock, patch

import pytest

from dak_agent import decorators
from dak_agent.decorators import PaidToolWrapper
from dak_agent.errors import PaymentRequiredError


@PaidToolWrapper(price=1.0)
def paid_tool(payment_hash=None):
    return "ok"


@pytest.fixture
def wallet():
    decorators._used_payment_hashes.clear()
    fake = MagicMock(use_mock=False)
    fake.get_address.return_value = "AgentAddress"
    fake.verify_transaction.return_value = True
    with patch("dak_agent.decorators.get_solana_wallet_manager", return_value=fake):
        yield fake
    decorators._used_payment_hashes.clear()


def test_real_mode_rejects_reused_hash(wallet):
    assert paid_tool(payment_hash="sig-1") == "ok"
    with pytest.raises(PaymentRequiredError):
        paid_tool(payment_hash="sig-1")
    wallet.verify_transaction.assert_called_once_with("sig-1", "AgentAddress", 1.0)


def test_real_mode_failed_hash_is_not_recorded(wallet):
    wallet.verify_transaction.return_value = False
    with pytest.raises(PaymentRequiredError):
        paid_tool(payment_hash="sig-bad")
    wallet.verify_transaction.return_value = True
    assert paid_tool(payment_hash="sig-good") == "ok"
    assert paid_tool(payment_hash="sig-bad") == "ok"


def test_mock_mode_allows_same_hash_twice(wallet):
    wallet.use_mock = True
    assert paid_tool(payment_hash="MockTx_1000000000_AgentAdd") == "ok"
    assert paid_tool(payment_hash="MockTx_1000000000_AgentAdd") == "ok"


def test_no_hash_raises_payment_required(wallet):
    with pytest.raises(PaymentRequiredError):
        paid_tool()
    wallet.verify_transaction.assert_not_called()


def test_real_mode_rejects_concurrent_reuse(wallet):
    import threading

    barrier = threading.Barrier(2, timeout=1)

    def slow_verify(*_):
        try:
            barrier.wait()  # 2 本とも検証の中に入るまで待つ（入れなければ片方は検証の前に拒まれている）
        except threading.BrokenBarrierError:
            pass
        return True

    wallet.verify_transaction.side_effect = slow_verify
    results = []

    def call():
        try:
            results.append(paid_tool(payment_hash="sig-1"))
        except PaymentRequiredError:
            results.append("refused")

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["ok", "refused"]
