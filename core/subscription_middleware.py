from django.http import JsonResponse
from rest_framework.authtoken.models import Token


class SubscriptionAccessMiddleware:
    """Blocks protected API use for tenants whose trial or membership has ended."""

    allowed_paths = {
        '/api/accounts/auth/check/',
        '/api/accounts/auth/me/',
        '/api/accounts/auth/logout/',
        '/api/accounts/auth/delete-account/',
        '/api/config/public/company/',
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/api/') and request.path not in self.allowed_paths:
            header = request.headers.get('Authorization', '')
            if header.startswith('Token '):
                token = Token.objects.select_related('user__tenant').filter(key=header[6:].strip()).first()
                tenant = getattr(getattr(token, 'user', None), 'tenant', None)
                if tenant:
                    subscription = tenant.subscription_info()
                    if not subscription['is_active']:
                        return JsonResponse(
                            {
                                'detail': 'Firma üyeliğinin süresi doldu. Yenileme için destek ekibiyle iletişime geçin.',
                                'account_status': 'subscription_expired',
                                'subscription': subscription,
                            },
                            status=403,
                        )
        return self.get_response(request)