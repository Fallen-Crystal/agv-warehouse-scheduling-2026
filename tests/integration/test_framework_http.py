"""Malformed archives return actionable HTTP errors and do not wedge the viewer."""

import json
import threading
import unittest
from copy import deepcopy
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agv.warehouse.mixed import generate_current
from agv.web.app import create_server


class ImportHTTPContracts(unittest.TestCase):
    def test_invalid_archive_then_valid_archive(self):
        with patch("agv.web.app.make_html", return_value="<html></html>"):
            server = create_server()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/api/load"
            good = generate_current(task_count=0, vehicles=1).to_dict()
            bad = deepcopy(good)
            bad["map_info"] = []
            for payload in (bad, {"scenario": good, "config": {"algorithm": []}}):
                request = Request(
                    url, json.dumps(payload).encode(), {"Content-Type": "application/json"}
                )
                with self.assertRaises(HTTPError) as raised:
                    urlopen(request, timeout=15)
                self.assertEqual(raised.exception.code, 400)
                self.assertIn("error", json.loads(raised.exception.read()))
            request = Request(url, json.dumps(good).encode(), {"Content-Type": "application/json"})
            with urlopen(request, timeout=15) as response:
                result = json.load(response)["result"]
            self.assertTrue(result["feasible"])
            self.assertTrue(result["score_valid"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
