import logging
import sys
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import time
from collections import defaultdict
from datetime import datetime, timedelta
import asyncio


# Configure logging
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("bg_labs.log")
        ]
    )
    
    # Set specific loggers
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


logger = logging.getLogger("bg_labs")


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        requests_per_minute: int = 60,
        requests_per_hour: int = 1000,
        exempt_paths: list = None
    ):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        self.exempt_paths = exempt_paths or ["/health", "/docs", "/openapi.json", "/redoc"]
        self.minute_buckets: dict = defaultdict(list)
        self.hour_buckets: dict = defaultdict(list)
        self._cleanup_task = None
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limiting for exempt paths
        if request.url.path in self.exempt_paths:
            return await call_next(request)
        
        # Get client identifier (IP + User ID if authenticated)
        client_ip = request.client.host
        user_id = getattr(request.state, "user_id", None)
        identifier = f"{user_id}:{client_ip}" if user_id else client_ip
        
        now = time.time()
        minute_ago = now - 60
        hour_ago = now - 3600
        
        # Clean old entries
        self.minute_buckets[identifier] = [
            t for t in self.minute_buckets[identifier] if t > minute_ago
        ]
        self.hour_buckets[identifier] = [
            t for t in self.hour_buckets[identifier] if t > hour_ago
        ]
        
        # Check limits
        if len(self.minute_buckets[identifier]) >= self.requests_per_minute:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Too many requests. Limit: {self.requests_per_minute}/minute",
                    "retry_after": 60
                },
                headers={"Retry-After": "60"}
            )
        
        if len(self.hour_buckets[identifier]) >= self.requests_per_hour:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Hourly limit reached. Limit: {self.requests_per_hour}/hour",
                    "retry_after": 3600
                },
                headers={"Retry-After": "3600"}
            )
        
        # Record request
        self.minute_buckets[identifier].append(now)
        self.hour_buckets[identifier].append(now)
        
        # Process request
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        
        # Log request
        logger.info(
            f"{request.method} {request.url.path} - "
            f"Status: {response.status_code} - "
            f"Time: {process_time:.3f}s - "
            f"Client: {identifier}"
        )
        
        # Add rate limit headers
        response.headers["X-RateLimit-Limit-Minute"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining-Minute"] = str(
            max(0, self.requests_per_minute - len(self.minute_buckets[identifier]))
        )
        response.headers["X-RateLimit-Limit-Hour"] = str(self.requests_per_hour)
        response.headers["X-RateLimit-Remaining-Hour"] = str(
            max(0, self.requests_per_hour - len(self.hour_buckets[identifier]))
        )
        response.headers["X-Process-Time"] = str(process_time)
        
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        
        # Log request
        logger.info(
            f"Incoming: {request.method} {request.url.path} "
            f"from {request.client.host}"
        )
        
        try:
            response = await call_next(request)
            process_time = time.time() - start_time
            
            # Log response
            logger.info(
                f"Outgoing: {request.method} {request.url.path} - "
                f"Status: {response.status_code} - "
                f"Time: {process_time:.3f}s"
            )
            
            return response
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                f"Error: {request.method} {request.url.path} - "
                f"Error: {str(e)} - "
                f"Time: {process_time:.3f}s",
                exc_info=True
            )
            raise


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=()"
        
        return response


# Rate limit decorators for specific endpoints
def rate_limit(requests: int = 10, period: int = 60):
    """Decorator for endpoint-specific rate limiting"""
    def decorator(func: Callable):
        call_counts = defaultdict(list)
        
        async def wrapper(*args, **kwargs):
            # Extract request from args
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            
            if request:
                identifier = f"{func.__name__}:{request.client.host}"
                now = time.time()
                period_ago = now - period
                
                call_counts[identifier] = [
                    t for t in call_counts[identifier] if t > period_ago
                ]
                
                if len(call_counts[identifier]) >= requests:
                    raise HTTPException(
                        status_code=429,
                        detail=f"Rate limit exceeded for this endpoint. Limit: {requests}/{period}s"
                    )
                
                call_counts[identifier].append(now)
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


from fastapi import HTTPException