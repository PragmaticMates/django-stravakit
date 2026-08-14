"""Minimal URLconf for the tests that resolve a URL.

The admin actions finish with ``redirect(...)``, and Django's ``resolve_url`` tries
``reverse()`` on whatever it is handed before falling back to treating it as a path — which
needs a urlconf to exist at all, even when the value is already a plain URL.
"""
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
