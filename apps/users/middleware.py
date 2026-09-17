from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone


class TimezoneMiddleware:
    """Activates the logged-in user's timezone for the duration of the request,
    so date.today()-equivalents (timezone.localdate(), timezone.localtime())
    reflect the user's local day instead of the server's (UTC)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tzname = getattr(getattr(request, "user", None), "timezone", None)
        if tzname:
            try:
                timezone.activate(ZoneInfo(tzname))
            except ZoneInfoNotFoundError:
                timezone.deactivate()
        else:
            timezone.deactivate()
        return self.get_response(request)
