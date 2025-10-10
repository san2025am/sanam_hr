
from django.test import TestCase, Client
from django.urls import reverse, resolve, NoReverseMatch

# List of URL paths to probe (GET). We assert not 404 (allow 200/401/403/405).
PROBE_PATHS = [
    '/auth/guard/login/',
    '/auth/guard/me/',
    '/auth/password/forgot/username/',
    '/auth/password/reset/username/',
    '/attendance/check/',
    '/attendance/resolve-location/',
    '/attendance/location-ping/',
    '/guards/reports/',
    '/guards/requests/',
    '/guards/advances/',
    '/guards/tasks/',
    '/guards/uniform-items/',
    '/attendance/last/',
]

class UrlsExistenceTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_urls_not_404(self):
        for path in PROBE_PATHS:
            resp = self.client.get(path)
            self.assertNotEqual(resp.status_code, 404, f"{path} should be routed (got 404)")
