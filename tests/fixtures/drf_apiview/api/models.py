from django.conf import settings
from django.db import models


class Order(models.Model):
    """Unmanaged: the fixture never creates tables or runs queries."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta:
        managed = False
        app_label = "api"
