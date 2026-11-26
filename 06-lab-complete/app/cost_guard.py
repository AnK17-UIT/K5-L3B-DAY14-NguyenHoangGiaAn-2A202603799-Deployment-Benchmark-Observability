"""Daily mock token-cost accounting shared through Redis (UTC day)."""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def budget_key() -> str:
    return 'cost:' + datetime.now(timezone.utc).strftime('%Y-%m-%d')


def check_budget() -> None:
    spent = float(r.get(budget_key()) or 0)
    if spent >= settings.daily_budget_usd:
        raise HTTPException(402, 'Daily budget exhausted')


def record_cost(input_tokens: int, output_tokens: int) -> float:
    cost = (input_tokens * PRICE_INPUT_PER_1K +
            output_tokens * PRICE_OUTPUT_PER_1K) / 1000
    # Atomic increment prevents lost updates between workers. Keep two days for
    # inspection; the date in the key resets the active budget at midnight UTC.
    key = budget_key()
    with r.pipeline() as pipe:
        pipe.incrbyfloat(key, cost)
        pipe.expire(key, 172800)
        pipe.execute()
    return cost
