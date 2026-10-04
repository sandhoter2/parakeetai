from django.http import HttpResponse


class ExtCorsMiddleware:
    """CORS + CSRF bypass for Chrome extension and ngrok access (dev server only)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Bypass any residual CSRF checks (CsrfViewMiddleware is removed from
        # MIDDLEWARE, but set these flags defensively in case it's ever re-added)
        request.csrf_processing_done = True
        request._dont_enforce_csrf_checks = True

        if request.method == 'OPTIONS':
            response = HttpResponse()
        else:
            response = self.get_response(request)

        origin = request.headers.get('Origin', '')
        response['Access-Control-Allow-Origin'] = origin or '*'
        response['Access-Control-Allow-Headers'] = 'Content-Type, X-Ext-Token, X-CSRFToken'
        response['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
        response['Access-Control-Allow-Credentials'] = 'true'

        return response
