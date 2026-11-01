from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


class AccountDeletionTokenAuthentication(TokenAuthentication):
    """An existing token may identify an inactive user only for account deletion.

    The deletion view still requires the current password and explicit confirmation.
    All other endpoints retain DRF's normal inactive-user rejection.
    """

    def authenticate_credentials(self, key):
        model = self.get_model()
        try:
            token = model.objects.select_related('user').get(key=key)
        except model.DoesNotExist:
            raise AuthenticationFailed('Invalid token.')
        return token.user, token
