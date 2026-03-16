import unittest

import qrcode_gui


class QrcodeGuiLogicTests(unittest.TestCase):
    def test_importing_module_does_not_start_gui(self):
        self.assertIsNone(qrcode_gui.root)

    def test_build_proxy_url_quotes_reserved_characters(self):
        url = qrcode_gui.build_proxy_url(
            {
                "ip": "2001:db8::1",
                "port": "1080",
                "user": "user/name",
                "pwd": "p#word",
            },
            "note a/b#1",
        )

        self.assertEqual(
            url,
            "socks5://user%2Fname:p%23word@[2001:db8::1]:1080#note%20a%2Fb%231",
        )

    def test_get_exportable_rows_only_returns_connected_rows(self):
        row_mapping = {
            "a": {"original_text": "row-a", "test_status": qrcode_gui.TEST_STATUS_CONNECTED},
            "b": {"original_text": "row-b", "test_status": qrcode_gui.TEST_STATUS_DISCONNECTED},
            "c": {"original_text": "row-c", "test_status": qrcode_gui.TEST_STATUS_UNTESTED},
        }

        exportable = qrcode_gui.get_exportable_rows(row_mapping)

        self.assertEqual([row["original_text"] for row in exportable], ["row-a"])

    def test_apply_test_result_to_row_ignores_stale_run(self):
        row = {
            "latency": "-",
            "test_status": qrcode_gui.TEST_STATUS_UNTESTED,
            "active_test_run_id": 2,
        }

        applied = qrcode_gui.apply_test_result_to_row(
            row,
            "12 ms",
            qrcode_gui.TEST_STATUS_CONNECTED,
            run_id=1,
        )

        self.assertFalse(applied)
        self.assertEqual(row["latency"], "-")
        self.assertEqual(row["test_status"], qrcode_gui.TEST_STATUS_UNTESTED)
        self.assertEqual(row["active_test_run_id"], 2)

        applied = qrcode_gui.apply_test_result_to_row(
            row,
            "12 ms",
            qrcode_gui.TEST_STATUS_CONNECTED,
            run_id=2,
        )

        self.assertTrue(applied)
        self.assertEqual(row["latency"], "12 ms")
        self.assertEqual(row["test_status"], qrcode_gui.TEST_STATUS_CONNECTED)
        self.assertIsNone(row["active_test_run_id"])


if __name__ == "__main__":
    unittest.main()
