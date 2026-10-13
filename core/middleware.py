from django.utils import timezone as django_timezone
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken


class TimezoneMiddleware:
    """Activates the authenticated user's IANA timezone for the duration of the
    request, so every timezone-aware 'today' computation (Django's
    timezone.localdate(), and Postgres __date lookups on datetime fields)
    resolves against the member's local date instead of server UTC.

    Runs independent JWT authentication here because Django's middleware stack
    executes before DRF wraps the request and resolves request.user.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.jwt_auth = JWTAuthentication()

    def __call__(self, request):
        tz_name = None
        try:
            result = self.jwt_auth.authenticate(request)
        except (TokenError, InvalidToken):
            result = None
        if result is not None:
            user, _ = result
            profile = getattr(user, 'profile', None)
            tz_name = getattr(profile, 'timezone', None)

        if tz_name:
            COMMON_TIMEZONE_ALIASES = {
                'Asia/Calcutta': 'Asia/Kolkata',
                'Asia/Katmandu': 'Asia/Kathmandu',
                'Asia/Saigon': 'Asia/Ho_Chi_Minh',
                'US/Eastern': 'America/New_York',
                'US/Central': 'America/Chicago',
                'US/Mountain': 'America/Denver',
                'US/Pacific': 'America/Los_Angeles',
            }
            canonical_tz = COMMON_TIMEZONE_ALIASES.get(tz_name, tz_name)
            try:
                django_timezone.activate(canonical_tz)
            except Exception:
                django_timezone.deactivate()
        else:
            django_timezone.deactivate()

        try:
            return self.get_response(request)
        finally:
            django_timezone.deactivate()


class ApiVersionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith('/api/'):
            response['X-API-Version'] = '1'
            response['Vary'] = 'X-API-Version'
        return response
