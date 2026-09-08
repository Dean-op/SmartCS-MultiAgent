from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ecommerce_ai_agent.services.refund import RefundService
from ecommerce_ai_agent.services.user import UserService
from tests.integration.conftest import IntegrationDatabase

NOW = datetime(2026, 9, 8, tzinfo=UTC)


@pytest.mark.asyncio
async def test_refund_command_applies_rules_risk_and_idempotency(
    seeded_database: IntegrationDatabase,
) -> None:
    async with seeded_database.session_factory.begin() as session:
        users = UserService(session)
        alice = await users.get_user_by_email("alice@example.com")
        bob = await users.get_user_by_email("bob@example.com")
        erin = await users.get_user_by_email("erin@example.com")
        assert alice and bob and erin
        refunds = RefundService(session)

        automatic = await refunds.request_refund(
            user_id=alice.id,
            order_number="EC2026080011",
            amount=Decimal("50.00"),
            reason="配送问题",
            thread_id="alice-thread-auto",
            now=NOW,
        )
        duplicate = await refunds.request_refund(
            user_id=alice.id,
            order_number="EC2026080011",
            amount=Decimal("50.00"),
            reason="重复提交不应新建",
            thread_id="alice-thread-auto",
            now=NOW,
        )
        manual = await refunds.request_refund(
            user_id=alice.id,
            order_number="EC2026080021",
            amount=Decimal("150.00"),
            reason="高金额退款",
            thread_id="alice-thread-review",
            now=NOW,
        )
        not_owned = await refunds.request_refund(
            user_id=alice.id,
            order_number="EC2026080002",
            amount=Decimal("10.00"),
            reason="越权",
            thread_id="ownership",
            now=NOW,
        )
        unpaid = await refunds.request_refund(
            user_id=alice.id,
            order_number="EC2026080001",
            amount=Decimal("10.00"),
            reason="未支付",
            thread_id="unpaid",
            now=NOW,
        )
        expired = await refunds.request_refund(
            user_id=alice.id,
            order_number="EC2026080006",
            amount=Decimal("10.00"),
            reason="已超期",
            thread_id="expired",
            now=NOW,
        )
        fully_refunded = await refunds.request_refund(
            user_id=erin.id,
            order_number="EC2026080020",
            amount=Decimal("10.00"),
            reason="已全退",
            thread_id="fully-refunded",
            now=NOW,
        )
        too_much = await refunds.request_refund(
            user_id=bob.id,
            order_number="EC2026080012",
            amount=Decimal("99999.00"),
            reason="超额",
            thread_id="too-much",
            now=NOW,
        )
        rejected_review = await refunds.request_refund(
            user_id=bob.id,
            order_number="EC2026080012",
            amount=Decimal("150.00"),
            reason="人工拒绝样例",
            thread_id="bob-thread-review",
            now=NOW,
        )
        approved = await refunds.resolve_review(
            manual.review_id,
            approve=True,
            reviewer_id=erin.id,
            note="审核通过",
            now=NOW,
        )
        rejected = await refunds.resolve_review(
            rejected_review.review_id,
            approve=False,
            reviewer_id=erin.id,
            note="审核拒绝",
            now=NOW,
        )

    assert automatic.outcome == "auto_completed"
    assert automatic.refund_number
    assert duplicate.outcome == "duplicate"
    assert duplicate.refund_number == automatic.refund_number
    assert manual.outcome == "pending_review"
    assert manual.review_id is not None
    assert not_owned.code == "order_not_found"
    assert unpaid.code == "order_not_paid"
    assert expired.code == "refund_window_expired"
    assert fully_refunded.code == "fully_refunded"
    assert too_much.code == "amount_exceeds_refundable"
    assert approved.outcome == "approved"
    assert rejected.outcome == "rejected"
