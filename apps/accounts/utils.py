from django.utils.http import url_has_allowed_host_and_scheme


def safe_next_url(request, candidate: str | None) -> str:
    """Returns candidate if it's a safe same-site redirect target, else ''."""
    if not candidate:
        return ""
    if url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return ""
