from rest_framework import permissions


class IsInventoryManager(permissions.IsAuthenticated):
    pass
