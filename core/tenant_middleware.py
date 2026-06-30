from core.tenant_context import set_current_tenant, clear_current_tenant


class TenantContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = None

        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            tenant = getattr(user, "tenant", None)

        set_current_tenant(tenant)

        try:
            response = self.get_response(request)
            return response
        finally:
            clear_current_tenant()