import re
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from flask_migrate import upgrade

from app import create_app
from farmer_tools import local_today
from models import Crop, Farm, db


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
        dashboard = client.get("/dashboard").data
        self.assertNotIn(b'href="/diseases/diagnose"', dashboard)
        self.assertNotIn(b'href="/inputs"', dashboard)
        self.assertNotIn(b'href="/chatbot"', dashboard)
        self.assertIn(b"AI Recommendations", dashboard)
        self.assertIn(b"Farm Alerts", dashboard)
        self.assertEqual(client.get("/diseases/diagnose").location, "/diseases#crop-disease-scanner")
        health_page = client.get("/diseases")
        self.assertIn(b"Crop disease scanner", health_page.data)
        self.assertIn("'wasm-unsafe-eval'", health_page.headers["Content-Security-Policy"])
        self.assertEqual(self.app.test_client().get("/diseases/diagnose").status_code, 302)
        self.assertEqual(self.submit(client, "/crops", {
            "farm_id": farm_id, "crop_name": "Beans", "growth_stage": "Maturity",
            "health_status": "Under treatment", "notes": "Optional planting date",
        }).status_code, 303)
        self.assertEqual(client.get("/inputs").location, "/farms#farm-inputs")
        farm_page = client.get("/farms").data
        self.assertIn(b"Add a farm", farm_page)
        self.assertIn(b"Farm input records", farm_page)
        self.assertIn(b"Record a farm input", farm_page)
        crop_id = re.search(rb'<option value="(\d+)">Beans', farm_page)[1].decode()
        input_response = self.submit(client, "/inputs", {
            "farm_id": farm_id, "crop_id": crop_id, "input_type": "Seeds", "input_date": "2025-02-01",
        }, "/farms")
        self.assertEqual(input_response.status_code, 303)
        self.assertEqual(input_response.location, "/farms#farm-inputs")
        self.assertIn(b"Seeds", client.get("/farms").data)
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
        geocoding, forecast = Mock(), Mock()
        geocoding.json.return_value = {"results": [{"name": "Nairobi", "latitude": -1.29, "longitude": 36.82}]}
        forecast.json.return_value = {
            "current": {"temperature_2m": 22, "relative_humidity_2m": 65},
            "daily": {
                "time": ["2026-01-01", "2026-01-02", "2026-01-03"],
                "temperature_2m_max": [25, 25, 26],
                "temperature_2m_min": [15, 16, 17],
                "precipitation_probability_max": [30, 40, 20],
            },
        }
        with patch("original_workflows.requests.get", side_effect=[geocoding, forecast]):
            weather = self.submit(client, "/weather", {"farm_id": farm_id})
        self.assertIn(b"Three-day outlook", weather.data)
        self.assertIn(b"Nairobi", weather.data)
        missing = client.get("/page-does-not-exist")
        self.assertEqual(missing.status_code, 404)
        self.assertIn(b"Return to the portal", missing.data)
        self.assertEqual(self.submit(client, "/logout", {}, "/dashboard").status_code, 303)
        self.assertIn(b"You have signed out.", client.get("/login").data)

    def test_farmer_tools(self):
        client = self.register("tools-farmer@example.com")
        outsider = self.register("tools-outsider@example.com")
        farm = self.add_farm(client, "Waterfield")
        farm_id = farm.rsplit("/", 1)[-1]
        target = f"farm:{farm_id}"
        today = local_today()
        details = {"target": target, "water_amount": "600", "unit": "L", "applied_on": today.isoformat()}
        self.assertIn(b"Save irrigation", client.get("/irrigation").data)
        saved = self.submit(client, "/irrigation", details)
        self.assertEqual(saved.status_code, 303)
        self.assertIn(b"600 L", client.get(saved.location).data)
        self.assertEqual(self.submit(outsider, "/irrigation", details).status_code, 404)
        self.assertNotIn(b"600 L", outsider.get("/irrigation").data)
        self.assertEqual(self.submit(client, "/crops", {
            "farm_id": farm_id, "crop_name": "Maize", "growth_stage": "Flowering",
            "health_status": "Healthy",
        }).status_code, 303)
        with self.app.app_context():
            crop_id = db.session.scalar(db.select(Crop.id).filter_by(farm_id=int(farm_id)))
        entry = {"crop_id": crop_id, "water_amount": "2.5", "unit": "m3", "applied_on": today.isoformat()}
        self.assertEqual(self.submit(client, "/irrigation", entry).status_code, 303)
        self.assertIn(b"3,100 L", client.get("/irrigation").data)
        self.assertNotIn(b"2,500 L", outsider.get("/irrigation").data)
        self.assertEqual(self.submit(outsider, "/irrigation", entry).status_code, 404)
        self.assertEqual(outsider.get(f"/recommendations?crop_id={crop_id}&area_acres=0.5").status_code, 404)
        forecast = [(today + timedelta(days=offset), 5, 2, 65, 33, 20) for offset in range(3)]
        with patch("farmer_tools.fetch_forecast", return_value=forecast):
            self.assertEqual(self.submit(client, "/recommendations", {
                "crop_id": crop_id, "area_acres": "0.5", "efficiency": "80",
            }).status_code, 303)
            response = client.get(f"/recommendations?crop_id={crop_id}")
            self.assertIn(b"31,645 L", response.data)
            self.assertIn(b"31,645 L", client.get(f"/irrigation?crop_id={crop_id}").data)
            self.assertIn(b"High of 33 C forecast", response.data)
            self.assertIn(b"Due today", client.get(f"/alerts?farm_id={farm_id}").data)
            self.assertEqual(self.submit(client, f"/alerts/{crop_id}/checked", {},
                                         f"/alerts?farm_id={farm_id}").status_code, 303)
            self.assertIn((today + timedelta(days=3)).isoformat().encode(),
                          client.get(f"/alerts?farm_id={farm_id}").data)
            self.assertEqual(self.submit(outsider, f"/alerts/{crop_id}/checked", {}, "/alerts").status_code, 404)
        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            self.assertEqual(client.get("/chatbot").location, "/recommendations#ai-chatbot")
            ai_page = client.get("/recommendations").data
            self.assertIn(b"<title>AI Recommendations</title>", ai_page)
            self.assertIn(b"Next irrigation estimate", ai_page)
            self.assertIn(b"AI Chatbot", ai_page)
            response = self.submit(client, "/chatbot", {"question": "When should I water my maize?"}, "/recommendations")
            self.assertIn(b"Built-in farming guide", response.data)
            self.assertIn(b'action="/recommendations#ai-recommendation"', response.data)
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            with patch("farming_chat.generated_answer", return_value="Inspect three plants.") as generate:
                response = self.submit(client, "/chatbot", {"question": "How should I scout crops?"}, "/recommendations")
                self.assertIn(b"AI answer", response.data)
                generate.assert_called_once_with("How should I scout crops?", "test-key")
