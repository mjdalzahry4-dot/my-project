from datetime import timedelta

from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


class ExpiringTokenAuthentication(TokenAuthentication):
    """DRF token auth with a bounded lifetime for browser-issued tokens."""

    keyword = "Token"
    token_lifetime = timedelta(hours=12)

    def authenticate_credentials(self, key):
        token_model = self.get_model()
        try:
            token = token_model.objects.select_related("user").get(key=key)
        except token_model.DoesNotExist as exc:
            raise AuthenticationFailed("رمز الدخول غير صالح.") from exc
        user = token.user
        if not user.is_active or getattr(user, "account_status", None) != "active":
            token.delete()
            raise AuthenticationFailed("الحساب غير نشط.")
        if token.created <= timezone.now() - self.token_lifetime:
            token.delete()
            raise AuthenticationFailed("انتهت صلاحية تسجيل الدخول. سجّل الدخول مجددًا.")
        return user, token
