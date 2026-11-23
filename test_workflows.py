import re
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from flask_migrate import upgrade

from app import create_app
from models import Farm, db


class FarmWorkflows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = cls.enterClassContext(TemporaryDirectory())
        database = (Path(directory) / "test.sqlite3").as_posix()
        cls.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "only-for-disposable-integration-tests",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database}",
            "SESSION_COOKIE_SECURE": False,
        })
        with cls.app.app_context():
            cls.addClassCleanup(db.engine.dispose)
            upgrade()

    def submit(self, client, path, data, form_page=None):
        response = client.get(form_page or path)
        self.assertEqual(response.status_code, 200)
        token = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        self.assertIsNotNone(token)
        return client.post(path, data={"csrf_token": token[1].decode(), **data})

    def register(self, email):
        client = self.app.test_client()
        credentials = {"email": email, "password": "test-password-1234"}
        self.assertEqual(self.submit(client, "/signup", {
            **credentials, "full_name": email, "is_admin": "true",
        }).status_code, 303)
        self.assertEqual(self.submit(client, "/login", credentials).status_code, 303)
        return client

    def add_farm(self, client, name):
        response = self.submit(client, "/farms", {"farm_name": name, "location": "Nairobi", "farm_size": "1.5"})
        self.assertEqual(response.status_code, 303)
        self.assertIn(name.encode(), client.get("/farms").data)
        with self.app.app_context():
            farm_id = db.session.scalar(db.select(Farm.id).filter_by(name=name))
        return f"/farms/{farm_id}"

    def test_farm_crop_health_and_authorization(self):
        first = self.register("farmer1@example.com")
        second = self.register("farmer2@example.com")
        farm = self.add_farm(first, "Riverside")
        other_farm = self.add_farm(second, "Hilltop")
        self.assertEqual(first.get("/admin").status_code, 403)
        self.assertEqual(second.get(farm).status_code, 404)
        self.assertEqual(first.post(farm + "/crops").status_code, 400)
        self.assertEqual(self.submit(second, farm + "/crops", {}, other_farm).status_code, 404)

        crop = {
            "name": "Maize", "planted_on": "2025-01-01", "harvest_on": "2025-08-01",
            "stage": "Seedling", "health": "Healthy",
        }
        self.assertEqual(self.submit(first, farm + "/crops", crop, farm).status_code, 303)
        crop_id = re.search(rb'<option value="(\d+)"[^>]*>Maize', first.get(farm).data)[1].decode()
        self.assertEqual(self.submit(first, farm + "/crops/" + crop_id, {
            "stage": "Harvested", "health": "Healthy", "harvest_on": "2025-08-01",
        }).status_code, 303)
        self.assertIn(b"Harvested", first.get(farm).data)
        record = {"crop": crop_id, "category": "Fertiliser", "product": "Compost", "applied_on": "2025-02-01"}
        self.assertEqual(self.submit(first, farm + "/inputs", record, farm).status_code, 303)
        self.assertEqual(self.submit(second, other_farm + "/inputs", record, other_farm).status_code, 422)
        self.assertEqual(self.submit(first, farm + "/cases", {
            "crop": crop_id, "title": "Leaf discolouration", "symptoms": "Yellow spots",
            "reported_on": date.today().isoformat(),
        }, farm).status_code, 303)
        case = re.search(rb'href="(/farms/\d+/cases/\d+)">Leaf discolouration', first.get(farm).data)[1].decode()
        self.assertEqual(self.submit(first, case, {"status": "Recovered", "notes": "New leaves are clear"}).status_code, 303)
        self.assertIn(b"New leaves are clear", first.get(case).data)
        self.assertEqual(second.get(case).status_code, 404)

        geo = Mock()
        geo.json.return_value = {"results": [{"name": "Nairobi", "latitude": -1.29, "longitude": 36.82}]}
        forecast = Mock()
        forecast.json.return_value = {"daily": {
            "time": ["2025-02-01"], "temperature_2m_min": [15], "temperature_2m_max": [27],
            "precipitation_probability_max": [13],
        }}
        with patch("farms.requests.get", side_effect=[geo, forecast]):
            response = first.get(farm + "/weather")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"13%", response.data)
        self.assertIn(b"27 &deg;C", response.data)

    def test_admin_and_login_limit(self):
        runner = self.app.test_cli_runner()
        command = runner.invoke(args=[
            "create-admin", "--email", "admin@example.com", "--name", "Administrator",
        ], input="test-password-1234\ntest-password-1234\n")
        self.assertEqual(command.exit_code, 0, command.output)
        client = self.app.test_client()
        self.assertEqual(self.submit(client, "/login", {
            "email": "admin@example.com", "password": "test-password-1234", "role": "admin",
        }).status_code, 303)
        self.assertIn(b"Recently registered farmers", client.get("/admin").data)
        self.assertIn(b"Crop disease scanner", client.get("/admin").data)
        self.assertIn(b'capture="environment"', client.get("/diseases/diagnose").data)
        self.assertEqual(client.get("/dashboard").status_code, 403)
        self.assertEqual(client.get("/healthz").json, {"status": "ok"})

        blocked_client = self.app.test_client()
        with patch("app.DUMMY_PASSWORD_HASH", "unused"):
            for _ in range(30):
                response = blocked_client.get("/login")
                token = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)[1].decode()
                denied = blocked_client.post("/login", data={"csrf_token": token},
                                             environ_overrides={"REMOTE_ADDR": "192.0.2.5"})
                self.assertEqual(denied.status_code, 401)
            limited = blocked_client.post("/login", data={"csrf_token": token},
                                          environ_overrides={"REMOTE_ADDR": "192.0.2.5"})
        self.assertEqual(limited.status_code, 429)

    def test_original_navigation_and_forms(self):
        client = self.register("original-workflow@example.com")
        farm = self.add_farm(client, "Meadow")
        farm_id = farm.rsplit("/", 1)[-1]
        self.assertIn(b"Welcome to your farming workspace", client.get("/dashboard").data)
        self.assertIn(b"Crop disease scanner", client.get("/dashboard").data)
        self.assertEqual(client.get("/diseases/diagnose").status_code, 200)
        self.assertEqual(self.app.test_client().get("/diseases/diagnose").status_code, 302)
        self.assertEqual(self.submit(client, "/crops", {
            "farm_id": farm_id, "crop_name": "Beans", "growth_stage": "Maturity",
            "health_status": "Under treatment", "notes": "Optional planting date",
        }).status_code, 303)
        crop_id = re.search(rb'<option value="(\d+)">Beans', client.get("/inputs").data)[1].decode()
        self.assertEqual(self.submit(client, "/inputs", {
            "farm_id": farm_id, "crop_id": crop_id, "input_type": "Seeds", "input_date": "2025-02-01",
        }).status_code, 303)
        self.assertEqual(self.submit(client, "/diseases", {
            "farm_id": farm_id, "crop_id": crop_id, "issue_name": "Leaf spots",
            "reported_date": date.today().isoformat(),
        }).status_code, 303)
        health = client.get("/diseases").data
        update = re.search(rb'action="(/diseases/\d+/update)"', health)[1].decode()
        self.assertEqual(self.submit(client, update, {"status": "Recovered"}, "/diseases").status_code, 303)
        self.assertIn(b"Healthy", client.get("/crops").data)
        self.assertIn(b"Recovered:", client.get("/diseases").data)
        self.assertIn(b"Check weather for a farm", client.get("/weather").data)
