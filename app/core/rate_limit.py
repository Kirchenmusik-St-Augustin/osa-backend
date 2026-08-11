from slowapi import Limiter
from slowapi.util import get_remote_address

# Per-IP rate limiting for endpoints with no Legacy equivalent (e.g. /refresh
# -- Legacy has no JWT refresh concept at all). 1:1 vb-api pattern.
#
# The login endpoint's own 5-attempts/60s lockout is NOT built on this
# limiter -- it must match Legacy's asymmetric "hit on failure, clear on
# success" RateLimiter semantics exactly (hard business-result parity, see
# the Schritt-2 plan), which a blanket per-endpoint request limiter cannot
# express. See app.services.auth_service.check_login_throttle instead.
limiter = Limiter(key_func=get_remote_address)
