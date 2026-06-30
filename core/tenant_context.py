from threading import local

_context = local()


def set_current_tenant(tenant):
    _context.tenant = tenant


def get_current_tenant():
    return getattr(_context, "tenant", None)


def clear_current_tenant():
    if hasattr(_context, "tenant"):
        delattr(_context, "tenant")