from services.permissions import IsServiceManager


class IsQuoteManager(IsServiceManager):
    """Teklif yetkisi mevcut servis yonetim yetkisini takip eder."""

