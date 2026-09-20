"""Flask extensions, created unbound and attached in the app factory."""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    get_remote_address,
    default_limits=["500 per day"],
    storage_uri="memory://",
)
