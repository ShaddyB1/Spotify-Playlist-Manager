from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify
import logging

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self):
        self.requests = {}
        self.WINDOW_SIZE = timedelta(minutes=1)
        self.MAX_REQUESTS = 100  # Adjust based on Spotify API limits

    def is_rate_limited(self, key):
        now = datetime.now()
        if key not in self.requests:
            self.requests[key] = []
        
        # Remove old requests
        self.requests[key] = [time for time in self.requests[key] 
                            if now - time < self.WINDOW_SIZE]
        
        # Check if limit exceeded
        if len(self.requests[key]) >= self.MAX_REQUESTS:
            return True
        
        # Add new request
        self.requests[key].append(now)
        return False

rate_limiter = RateLimiter()

def rate_limit(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if rate_limiter.is_rate_limited(request.remote_addr):
            logger.warning(f"Rate limit exceeded for IP {request.remote_addr}")
            return jsonify({
                'error': 'Rate limit exceeded. Please try again later.',
                'retry_after': 60
            }), 429
        return f(*args, **kwargs)
    return decorated_function