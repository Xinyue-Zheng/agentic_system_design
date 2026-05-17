import threading

_cache = {}
_lock = threading.Lock()

def get_cached(namespace: str, key: str, compute_fn):
    with _lock:
        if key in _cache.get(namespace, {}):
            return _cache[namespace][key]
    result = compute_fn()
    with _lock:
        _cache.setdefault(namespace, {})
        if key not in _cache[namespace]:
            _cache[namespace][key] = result
    return result

def clear_cache(namespace: str = None):
    with _lock:
        if namespace:
            _cache.pop(namespace, None)
        else:
            _cache.clear()
