"""Production lab agent with shared Redis limits and mock LLM responses."""
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from app.auth import verify_api_key
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            'ts': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'event': record.getMessage(),
            **getattr(record, 'fields', {}),
        })


logger = logging.getLogger('agent')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.handlers = [handler]
logger.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Uvicorn handles SIGTERM and drains in-flight requests before cleanup.
    logger.info('startup')
    try:
        yield
    finally:
        r.close()
        logger.info('shutdown')


app = FastAPI(title='Production AI Agent', lifespan=lifespan)


@app.middleware('http')
async def log_request(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    logger.info('request', extra={'fields': {
        'method': request.method, 'path': request.url.path,
        'status': response.status_code,
        'ms': round((time.monotonic() - start) * 1000, 2),
    }})
    return response


@app.exception_handler(RedisError)
async def redis_error(request: Request, exc: RedisError):
    logger.warning('redis_unavailable')
    return JSONResponse(status_code=503, content={'detail': 'Redis unavailable'})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.get('/ready')
def ready():
    if not redis_healthy():
        raise HTTPException(503, 'Redis unavailable')
    return {'status': 'ready'}


@app.post('/ask')
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()
    answer = llm_ask(body.question)
    # This mock returns text without provider token counts. Word counts are
    # explicit estimates used only for this lab's simulated cost accounting.
    input_tokens = max(1, len(body.question.split()))
    output_tokens = max(1, len(answer.split()))
    cost = record_cost(input_tokens, output_tokens)
    return {'question': body.question, 'answer': answer,
            'usage': {'input_tokens': input_tokens, 'output_tokens': output_tokens,
                      'cost_usd': cost, 'estimated': True}}
