import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from splitbill import storage, web
from splitbill.ledger import Ledger


class TestApiFunctions(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger()
        for n in ["Alice", "Bob", "Carol"]:
            self.ledger.add_person(n)

    def test_preview_does_not_modify_ledger(self):
        body = {"payer": "1", "amount": "300", "participants": ["1", "2", "3"], "method": "equal"}
        pv = web.api_expense_preview(self.ledger, body)
        self.assertEqual(pv["shares"], {"Alice": "100", "Bob": "100", "Carol": "100"})
        self.assertEqual(self.ledger.expenses, [])

    def test_add_expense_then_state_balances(self):
        body = {"payer": "Alice", "amount": "300", "participants": ["Alice", "Bob", "Carol"]}
        web.api_expense_add(self.ledger, body)
        state = web.api_state(self.ledger, {})
        self.assertEqual(state["balances"]["Alice"], "200")
        self.assertEqual(len(state["suggestions"]), 2)

    def test_ratio_and_fixed(self):
        base = {"payer": "Alice", "amount": "300", "participants": ["Alice", "Bob"]}
        ratio = web.api_expense_preview(
            self.ledger, {**base, "method": "ratio", "values": {"Alice": "2", "Bob": "1"}}
        )
        self.assertEqual(ratio["shares"], {"Alice": "200", "Bob": "100"})
        with self.assertRaises(ValueError):
            web.api_expense_preview(
                self.ledger, {**base, "method": "fixed", "values": {"Alice": "100", "Bob": "100"}}
            )

    def test_rejects_bad_numbers(self):
        for bad in ["abc", "NaN", "Infinity", "-5", "0", ""]:
            with self.assertRaises(ValueError, msg=bad):
                web.api_expense_preview(
                    self.ledger, {"payer": "1", "amount": bad, "participants": ["1"]}
                )

    def test_rejects_empty_participants_and_unknown_person(self):
        with self.assertRaises(ValueError):
            web.api_expense_preview(self.ledger, {"payer": "1", "amount": "10", "participants": []})
        with self.assertRaises(ValueError):
            web.api_expense_preview(
                self.ledger, {"payer": "1", "amount": "10", "participants": ["99"]}
            )

    def test_payment_flow_and_self_payment_rejected(self):
        web.api_expense_add(
            self.ledger, {"payer": "1", "amount": "100", "participants": ["1", "2"]}
        )
        pid = web.api_payment_add(self.ledger, {"payer": "2", "payee": "1", "amount": "50"})["id"]
        self.assertEqual(web.api_state(self.ledger, {})["balances"]["Bob"], "-50")
        web.api_payment_confirm(self.ledger, {"id": pid})
        self.assertEqual(web.api_state(self.ledger, {})["balances"]["Bob"], "0")
        with self.assertRaises(ValueError):
            web.api_payment_add(self.ledger, {"payer": "1", "payee": "1", "amount": "5"})

    def test_payment_reject_route(self):
        pid = web.api_payment_add(self.ledger, {"payer": "2", "payee": "1", "amount": "50"})["id"]
        web.api_payment_reject(self.ledger, {"id": pid})
        payment = web.api_state(self.ledger, {})["payments"][0]
        self.assertTrue(payment["rejected"])
        self.assertFalse(payment["confirmed"])
        with self.assertRaises(ValueError):
            web.api_payment_confirm(self.ledger, {"id": pid})

    def test_group_save_and_delete(self):
        web.api_group_save(self.ledger, {"name": "班底", "members": ["1", "2"]})
        self.assertEqual(self.ledger.resolve_group("班底"), ["Alice", "Bob"])
        web.api_group_delete(self.ledger, {"name": "班底"})
        self.assertEqual(self.ledger.groups, {})

    def test_name_too_long_rejected(self):
        with self.assertRaises(ValueError):
            web.api_add_person(self.ledger, {"name": "x" * 31})


class TestHttpServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "ledger.json")
        self.token = "testkey"
        self.server = web.LedgerServer(("127.0.0.1", 0), Ledger(), self.token, self.path)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, path, body=None, key="testkey"):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, headers={"X-Key": key})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_index_page_served_without_key(self):
        with urllib.request.urlopen(self.base + "/") as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("聚會拆帳", resp.read().decode("utf-8"))

    def test_api_requires_key(self):
        self.assertEqual(self.call("/api/state", key="wrong")[0], 401)
        self.assertEqual(self.call("/api/person/add", {"name": "A"}, key="")[0], 401)
        self.assertEqual(self.call("/api/state")[0], 200)

    def test_mutation_is_saved_to_file(self):
        status, data = self.call("/api/person/add", {"name": "Alice"})
        self.assertEqual((status, data["code"]), (200, "1"))
        self.assertEqual(storage.load(self.path).people, ["Alice"])

    def test_error_returns_400_with_message(self):
        status, data = self.call("/api/person/add", {"name": ""})
        self.assertEqual(status, 400)
        self.assertIn("不可為空", data["error"])

    def test_unknown_route_and_bad_json(self):
        self.assertEqual(self.call("/api/nope", {})[0], 404)
        req = urllib.request.Request(
            self.base + "/api/person/add", data=b"{not json", headers={"X-Key": self.token}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)

    def test_static_path_traversal_not_possible(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/../web.py")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
