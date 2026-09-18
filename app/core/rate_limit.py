from slowapi import Limiter
from slowapi.util import get_remote_address

# Per-IP rate limiting for endpoints that only need a plain request limiter
# (e.g. /refresh).
#
# The login endpoint's own 5-attempts/60s lockout is NOT built on this
# limiter -- it needs asymmetric "hit on failure, clear on success"
# semantics, which a blanket per-endpoint request limiter cannot express.
# See app.services.auth_service.check_login_throttle instead.
limiter = Limiter(key_func=get_remote_address)
