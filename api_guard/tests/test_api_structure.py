
from django.test import TestCase
from importlib import import_module

class ApiStructureTests(TestCase):
    def test_views_importable(self):
        mod = import_module('api_guard.views')
        # Ensure key classes exist
        expected = [
            'GuardLoginAndProfileView',
            'GuardMeView',
            'AttendanceCheckAPIView',
            'GuardReportListCreateView',
            'GuardRequestListCreateView',
        ]
        for name in expected:
            self.assertTrue(hasattr(mod, name), f"Missing view: {name}")
