"""A very small service. It exists so the pipeline has something real to build, test and deploy."""

import os

from fastapi import FastAPI, HTTPException

from .pricing import final_price

app = FastAPI(title="demo-app")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": os.getenv("APP_VERSION", "dev")}


@app.get("/quote")
def quote(amount: float, coupon: str | None = None) -> dict:
    try:
        return {"amount": amount, "coupon": coupon, "final_price": final_price(amount, coupon)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
