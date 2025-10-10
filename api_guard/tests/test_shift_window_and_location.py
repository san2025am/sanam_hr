
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()

class ShiftWindowLocationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='g1', password='p')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_me_contains_shift_fields(self):
        resp = self.client.get('/auth/guard/me/')
        self.assertIn(resp.status_code, (200, 201))
        data = resp.json()
        payload = data.get('data') if isinstance(data, dict) and 'data' in data else data
        self.assertIn('unrestricted', payload)
        self.assertIn('pre_shift_buffer_minutes', payload)

    def test_check_requires_coordinates(self):
        resp = self.client.post('/attendance/check/', data={'action': 'checkin'})
        self.assertEqual(resp.status_code, 400)
