"""A very small service. It exists so the pipeline has something real to build, test and deploy."""

import os

from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from .pricing import final_price

app = FastAPI(title="demo-app")

# One counter, split by status code. Prometheus reads it from /metrics,
# and the pipeline uses it to check the error rate after a deploy.
REQUESTS = Counter("http_requests_total", "HTTP requests handled", ["path", "status"])


@app.middleware("http")
async def count_requests(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != "/metrics":
        REQUESTS.labels(path=request.url.path, status=str(response.status_code)).inc()
    return response


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health() -> dict:
    # FAIL_HEALTH lets us fake a broken release, to test that the pipeline rolls it back.
    if os.getenv("FAIL_HEALTH") == "true":
        raise HTTPException(status_code=503, detail="unhealthy (FAIL_HEALTH is set)")
    return {"status": "ok", "version": os.getenv("APP_VERSION", "dev")}


@app.get("/quote")
def quote(amount: float, coupon: str | None = None) -> dict:
    try:
        return {"amount": amount, "coupon": coupon, "final_price": final_price(amount, coupon)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
