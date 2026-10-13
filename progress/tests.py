from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from datetime import date
from users.models import User, UserProfile
from progress.models import BodyMeasurement


class WeightHeightValidationTests(TestCase):
    """BUG-21: weight/height accepted negative, zero, or absurd values end-to-end,
    silently corrupting downstream BMI/TDEE calculations."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email='bounds@example.com', username='bounds', password='testpassword123')
        self.client.force_authenticate(self.user)

    def test_negative_weigh_in_is_rejected(self):
        res = self.client.post('/api/progress/weight/', {'date': '2026-01-01', 'weight_kg': -70}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_zero_weigh_in_is_rejected(self):
        res = self.client.post('/api/progress/weight/', {'date': '2026-01-01', 'weight_kg': 0}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_absurd_weigh_in_is_rejected(self):
        res = self.client.post('/api/progress/weight/', {'date': '2026-01-01', 'weight_kg': 5000}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_plausible_weigh_in_is_accepted(self):
        res = self.client.post('/api/progress/weight/', {'date': '2026-01-01', 'weight_kg': 82.5}, format='json')
        self.assertEqual(res.status_code, 201, res.data)

    def test_profile_rejects_negative_and_absurd_height_and_weight(self):
        res = self.client.patch('/api/auth/me/', {'profile': {'height_cm': -5}}, format='json')
        self.assertEqual(res.status_code, 400)
        res = self.client.patch('/api/auth/me/', {'profile': {'height_cm': 0}}, format='json')
        self.assertEqual(res.status_code, 400)
        res = self.client.patch('/api/auth/me/', {'profile': {'height_cm': 900}}, format='json')
        self.assertEqual(res.status_code, 400)
        res = self.client.patch('/api/auth/me/', {'profile': {'weight_kg': -1}}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_profile_accepts_plausible_height_and_weight(self):
        res = self.client.patch('/api/auth/me/', {'profile': {'height_cm': 178, 'weight_kg': 82.5}}, format='json')
        self.assertEqual(res.status_code, 200, res.data)

    def test_profile_rejects_future_date_of_birth(self):
        res = self.client.patch('/api/auth/me/', {'profile': {'date_of_birth': '2099-01-01'}}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_profile_rejects_implausibly_old_date_of_birth(self):
        res = self.client.patch('/api/auth/me/', {'profile': {'date_of_birth': '1850-01-01'}}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_profile_rejects_implausibly_young_date_of_birth(self):
        from datetime import date
        too_young = date.today().replace(year=date.today().year - 1)
        res = self.client.patch('/api/auth/me/', {'profile': {'date_of_birth': too_young.isoformat()}}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_profile_accepts_plausible_date_of_birth(self):
        res = self.client.patch('/api/auth/me/', {'profile': {'date_of_birth': '1995-06-15'}}, format='json')
        self.assertEqual(res.status_code, 200, res.data)


class WeightEntryRetryTests(TestCase):
    """A retried weigh-in write (BUG-11 offline-queue support: same user, same date) must
    not 500 on the unique(user, date) constraint — it should upsert instead."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email='weightretry@example.com', username='weightretry', password='testpassword123')
        self.client.force_authenticate(self.user)

    def test_retried_weigh_in_same_date_upserts_instead_of_500(self):
        res1 = self.client.post('/api/progress/weight/', {'date': '2026-02-05', 'weight_kg': 80}, format='json')
        self.assertEqual(res1.status_code, 201, res1.data)
        res2 = self.client.post('/api/progress/weight/', {'date': '2026-02-05', 'weight_kg': 81.5}, format='json')
        self.assertEqual(res2.status_code, 201, res2.data)
        self.assertEqual(res1.data['id'], res2.data['id'])
        self.assertEqual(self.user.weight_entries.count(), 1)
        self.assertEqual(self.user.weight_entries.get().weight_kg, 81.5)

    def test_exact_retry_with_identical_payload_is_a_no_op(self):
        res1 = self.client.post('/api/progress/weight/', {'date': '2026-02-06', 'weight_kg': 75, 'notes': 'morning'}, format='json')
        res2 = self.client.post('/api/progress/weight/', {'date': '2026-02-06', 'weight_kg': 75, 'notes': 'morning'}, format='json')
        self.assertEqual(res2.status_code, 201, res2.data)
        self.assertEqual(res1.data['id'], res2.data['id'])
        self.assertEqual(self.user.weight_entries.count(), 1)


class BodyMeasurementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="athlete@example.com",
            username="athlete",
            password="securepassword123"
        )
        self.client.force_authenticate(user=self.user)

    def test_create_body_measurement(self):
        payload = {
            "date": "2026-09-18",
            "neck_cm": 38.5,
            "shoulders_cm": 122.0,
            "chest_cm": 104.5,
            "waist_cm": 82.0,
            "hips_cm": 98.0,
            "arms_cm": 38.0,
            "biceps_left_cm": 38.0,
            "biceps_right_cm": 38.2,
            "forearms_cm": 31.0,
            "thighs_cm": 59.0,
            "thigh_left_cm": 59.0,
            "thigh_right_cm": 59.2,
            "calves_cm": 38.0,
            "calf_left_cm": 38.0,
            "calf_right_cm": 38.1,
            "notes": "Feeling lean and strong"
        }
        res = self.client.post("/api/progress/measurements/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["shoulders_cm"], 122.0)
        self.assertEqual(res.data["biceps_right_cm"], 38.2)

        measurement = BodyMeasurement.objects.get(id=res.data["id"])
        self.assertEqual(measurement.neck_cm, 38.5)
        self.assertEqual(measurement.user, self.user)

    def test_list_and_delete_measurements(self):
        m = BodyMeasurement.objects.create(
            user=self.user,
            date=date(2026, 9, 10),
            chest_cm=102.0,
            waist_cm=84.0,
            shoulders_cm=120.0
        )
        res = self.client.get("/api/progress/measurements/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data.get("results", res.data)
        self.assertGreaterEqual(len(results), 1)

        del_res = self.client.delete(f"/api/progress/measurements/{m.id}/")
        self.assertEqual(del_res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(BodyMeasurement.objects.filter(id=m.id).exists())


class DailyLogTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="runner@example.com",
            username="runner",
            password="securepassword123"
        )
        self.client.force_authenticate(user=self.user)

    def test_create_daily_log(self):
        payload = {
            "date": "2026-09-15",
            "steps": 8500,
            "sleep_hours": 8.0,
            "sleep_quality": 4,
            "energy_level": 4,
            "recovery_notes": "Optimal recovery, feeling energetic."
        }
        res = self.client.post("/api/progress/daily/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["steps"], 8500)
        self.assertEqual(res.data["sleep_hours"], 8.0)
        self.assertEqual(res.data["energy_level"], 4)

    def test_update_existing_daily_log_on_post(self):
        payload1 = {
            "date": "2026-09-16",
            "steps": 7000,
            "sleep_hours": 7.5,
        }
        res1 = self.client.post("/api/progress/daily/", payload1, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # Update later in the day with additional energy and notes
        payload2 = {
            "date": "2026-09-16",
            "steps": 9200,
            "energy_level": 5,
            "recovery_notes": "Hit evening step walk target."
        }
        res2 = self.client.post("/api/progress/daily/", payload2, format="json")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["steps"], 9200)
        self.assertEqual(res2.data["sleep_hours"], 7.5)
        self.assertEqual(res2.data["energy_level"], 5)
        self.assertEqual(res2.data["recovery_notes"], "Hit evening step walk target.")

    def test_filter_by_date(self):
        self.client.post("/api/progress/daily/", {"date": "2026-09-17", "steps": 6000}, format="json")
        self.client.post("/api/progress/daily/", {"date": "2026-09-18", "steps": 8000}, format="json")

        res = self.client.get("/api/progress/daily/?date=2026-09-18")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data.get("results", res.data)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["steps"], 8000)

