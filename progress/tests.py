from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from datetime import date
from users.models import User
from progress.models import BodyMeasurement

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

