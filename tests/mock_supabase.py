"""
Minimal Supabase mock (PostgREST + Storage) for offline testing
==============================================================

Implements exactly the subset of PostgREST/Storage semantics ``app/store.py``
uses, so the whole API can be exercised end-to-end without network access:

* ``GET/POST/PATCH/DELETE /rest/v1/<table>``
* filters ``col=eq.value``, ``or=(a.eq.x,b.eq.y)``, ``order=col.desc``, ``limit``
* ``Prefer: return=representation`` and ``Prefer: count=exact`` (+ ``Range``)
* unique violations -> 409 with ``{"code": "23505"}``
* missing table -> 404 with ``{"code": "42P01"}``
* ``POST /storage/v1/object/<bucket>/<path>`` and the public read URL

Run it with::

    python tests/mock_supabase.py --port 54321 --key test-key
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

TABLES = ("bglabs_users", "bglabs_audio", "bglabs_images", "bglabs_voices", "bglabs_projects")
UNIQUE = {
    "bglabs_users": ["email", "username"],
}
JSONB_COLUMNS = {"settings"}

app = FastAPI(title="Mock Supabase")

DATA: Dict[str, List[Dict[str, Any]]] = {t: [] for t in TABLES}
SEQUENCES: Dict[str, int] = {t: 0 for t in TABLES}
OBJECTS: Dict[str, bytes] = {}
CONTENT_TYPES: Dict[str, str] = {}
API_KEY = "test-key"
REQUEST_LOG: List[str] = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unauthorized() -> JSONResponse:
    return JSONResponse(status_code=401, content={"code": "PGRST301", "message": "invalid api key"})


def _check_key(request: Request) -> Optional[JSONResponse]:
    key = request.headers.get("apikey") or ""
    auth = request.headers.get("authorization") or ""
    if key != API_KEY or not auth.endswith(API_KEY):
        REQUEST_LOG.append(f"UNAUTHORIZED {request.method} {request.url.path}")
        return _unauthorized()
    return None


def _match(row: Dict[str, Any], column: str, op: str, value: str) -> bool:
    actual = row.get(column)
    if op == "eq":
        if isinstance(actual, bool):
            return str(actual).lower() == value.lower()
        return str(actual) == value
    if op == "neq":
        return str(actual) != value
    if op == "is":
        return actual is None if value == "null" else str(actual) == value
    if op == "gt":
        return str(actual) > value
    if op == "lt":
        return str(actual) < value
    return True


def _apply_filters(rows: List[Dict[str, Any]], params: Dict[str, str]) -> List[Dict[str, Any]]:
    result = list(rows)
    for key, value in params.items():
        if key in ("select", "order", "limit", "offset"):
            continue
        if key == "or":
            inner = value.strip()
            if inner.startswith("(") and inner.endswith(")"):
                inner = inner[1:-1]
            conditions = [c for c in inner.split(",") if c]
            parsed = []
            for condition in conditions:
                parts = condition.split(".", 2)
                if len(parts) == 3:
                    parsed.append(parts)
            if parsed:
                result = [r for r in result if any(_match(r, c, o, v) for c, o, v in parsed)]
            continue
        if "." in str(value):
            op, raw = str(value).split(".", 1)
        else:
            op, raw = "eq", str(value)
        result = [r for r in result if _match(r, key, op, raw)]
    return result


def _apply_order_limit(rows: List[Dict[str, Any]], params: Dict[str, str]) -> List[Dict[str, Any]]:
    result = list(rows)
    order = params.get("order")
    if order:
        for clause in reversed(order.split(",")):
            bits = clause.strip().split(".")
            column = bits[0]
            descending = len(bits) > 1 and bits[1].lower().startswith("desc")
            result.sort(key=lambda r: (r.get(column) is None, r.get(column)), reverse=descending)
    if params.get("limit"):
        try:
            result = result[: int(params["limit"])]
        except ValueError:
            pass
    return result


def _serialize(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for column in JSONB_COLUMNS:
        if column in out and not isinstance(out[column], (dict, list, type(None))):
            try:
                out[column] = json.loads(out[column])
            except (TypeError, ValueError):
                pass
    return out


@app.api_route("/rest/v1/{table}", methods=["GET", "POST", "PATCH", "DELETE"])
async def rest(table: str, request: Request) -> Response:
    denied = _check_key(request)
    if denied:
        return denied

    params = {k: v for k, v in request.query_params.items()}
    REQUEST_LOG.append(f"{request.method} /rest/v1/{table}?{request.url.query}")

    if table not in DATA:
        return JSONResponse(status_code=404, content={
            "code": "42P01", "message": f"relation 'public.{table}' does not exist",
        })

    prefer = request.headers.get("prefer", "")
    rows = DATA[table]

    if request.method == "GET":
        matched = _apply_order_limit(_apply_filters(rows, params), params)
        total = len(matched)
        response = JSONResponse(content=[_serialize(r) for r in matched])
        if "count=exact" in prefer:
            start = 0
            stop = max(0, min(total, len(matched)) - 1)
            response.headers["content-range"] = f"{start}-{stop}/{total}"
        return response

    body = await request.body()
    try:
        payload = json.loads(body) if body else {}
    except ValueError:
        return JSONResponse(status_code=400, content={"code": "PGRST102", "message": "invalid json"})

    if request.method == "POST":
        items = payload if isinstance(payload, list) else [payload]
        created = []
        for item in items:
            for column in UNIQUE.get(table, []):
                if column in item:
                    clash = next(
                        (r for r in rows if str(r.get(column, "")).lower() == str(item[column]).lower()),
                        None,
                    )
                    if clash:
                        return JSONResponse(status_code=409, content={
                            "code": "23505",
                            "message": f'duplicate key value violates unique constraint "{table}_{column}_key"',
                            "details": f"Key ({column})=({item[column]}) already exists.",
                        })
            SEQUENCES[table] += 1
            row = {
                "id": SEQUENCES[table],
                "created_at": _now(),
                **{k: v for k, v in item.items()},
            }
            if table == "bglabs_projects":
                row.setdefault("updated_at", row["created_at"])
            rows.append(row)
            created.append(_serialize(row))
        if "return=representation" in prefer:
            return JSONResponse(status_code=201, content=created)
        return Response(status_code=201)

    # PATCH / DELETE
    matched = _apply_filters(rows, params)
    matched_ids = {id(r) for r in matched}
    affected = [_serialize(r) for r in matched]

    if request.method == "PATCH":
        for row in matched:
            row.update(payload)
            if table == "bglabs_projects":
                row["updated_at"] = _now()
        if "return=representation" in prefer:
            return JSONResponse(status_code=200, content=[_serialize(r) for r in matched])
        return Response(status_code=204)

    DATA[table] = [r for r in rows if id(r) not in matched_ids]
    if "return=representation" in prefer:
        return JSONResponse(status_code=200, content=affected)
    return Response(status_code=204)


@app.post("/rest/v1/rpc/{function}")
async def rpc(function: str, request: Request) -> Response:
    denied = _check_key(request)
    if denied:
        return denied
    REQUEST_LOG.append(f"POST /rest/v1/rpc/{function}")
    return JSONResponse(content={"ok": True, "function": function})


@app.get("/storage/v1/object/public/{bucket}/{path:path}")
async def storage_public(bucket: str, path: str) -> Response:
    key = f"{bucket}/{path}"
    REQUEST_LOG.append(f"GET public {key}")
    if key in OBJECTS:
        return Response(content=OBJECTS[key], media_type=CONTENT_TYPES.get(key, "application/octet-stream"))
    return JSONResponse(status_code=404, content={"statusCode": "404", "error": "Not found"})


@app.api_route("/storage/v1/object/{bucket}/{path:path}", methods=["POST", "PUT", "GET"])
async def storage_object(bucket: str, path: str, request: Request) -> Response:
    denied = _check_key(request)
    if denied:
        return denied
    key = f"{bucket}/{path}"
    REQUEST_LOG.append(f"{request.method} /storage/v1/object/{key}")
    if request.method in ("POST", "PUT"):
        OBJECTS[key] = await request.body()
        CONTENT_TYPES[key] = request.headers.get("content-type", "application/octet-stream")
        return JSONResponse(status_code=200, content={"Key": key})
    if key in OBJECTS:
        return Response(content=OBJECTS[key], media_type=CONTENT_TYPES.get(key, "application/octet-stream"))
    return JSONResponse(status_code=404, content={"statusCode": "404", "error": "Not found"})


@app.get("/_mock/stats")
async def mock_stats() -> Dict[str, Any]:
    return {
        "tables": {t: len(rows) for t, rows in DATA.items()},
        "objects": len(OBJECTS),
        "requests": len(REQUEST_LOG),
        "last_requests": REQUEST_LOG[-25:],
    }


@app.post("/_mock/reset")
async def mock_reset() -> Dict[str, Any]:
    for table in TABLES:
        DATA[table] = []
        SEQUENCES[table] = 0
    OBJECTS.clear()
    CONTENT_TYPES.clear()
    REQUEST_LOG.clear()
    return {"ok": True}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=54321)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--key", default="test-key")
    args = parser.parse_args()

    global API_KEY
    API_KEY = args.key

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
