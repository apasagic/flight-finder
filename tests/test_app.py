from datetime import date
import unittest

import app


class AppHelpersTests(unittest.TestCase):
    def test_parse_destinations_normalizes_and_deduplicates(self):
        self.assertEqual(app.parse_destinations("lca, PFO lca, ecn"), ["LCA", "PFO", "ECN"])

    def test_build_cli_args_includes_constraints(self):
        args = app.build_cli_args(
            {
                "origin": "ber",
                "destinations": ["LCA", "PFO"],
                "departure_start": date(2027, 10, 1),
                "departure_end": date(2027, 10, 20),
                "min_stay": 5,
                "max_stay": 7,
                "max_stops": 1,
                "max_duration_minutes": 480,
                "max_layover_minutes": 150,
                "workers": 4,
                "roundtrip_mode": "full",
                "output_dir": "results",
                "cache_dir": "cache",
            }
        )
        self.assertIn("BER", args)
        self.assertEqual(args[args.index("--max-layover-minutes") + 1], "150")
        self.assertEqual(args[args.index("--roundtrip-mode") + 1], "full")

    def test_demo_bundle_contains_both_ticket_strategies(self):
        bundle = app.demo_result_bundle()
        self.assertTrue(bundle["example"])
        self.assertGreater(len(bundle["individual"]), 0)
        self.assertGreater(len(bundle["roundtrip"]), 0)


if __name__ == "__main__":
    unittest.main()
