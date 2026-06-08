from cachetools import TTLCache

# Specialized caches with 5-minute TTL (300 seconds)
# auth_cache for is_user_authorized
auth_cache = TTLCache(maxsize=1000, ttl=300)
# user_cache for get_user_firstname
user_cache = TTLCache(maxsize=1000, ttl=300)
# media_cache for media lists and details
media_cache = TTLCache(maxsize=1000, ttl=300)

# Generic cache (kept for compatibility or miscellaneous data)
cache = TTLCache(maxsize=1000, ttl=300)

def invalidate_cache():
    """Clears in-memory caches for media and generic data. Auth/User caches kept unless specified."""
    auth_cache.clear()
    user_cache.clear()
    media_cache.clear()
    cache.clear()
