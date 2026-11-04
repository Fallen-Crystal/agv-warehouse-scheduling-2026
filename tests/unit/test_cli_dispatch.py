"""CLI subcommands and handlers stay in sync."""

import argparse
import unittest

from agv.cli import COMMANDS, build_parser


class CliDispatchTests(unittest.TestCase):
    def test_every_subcommand_has_one_handler(self):
        parser = build_parser()
        subparsers = next(
            action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
        )
        self.assertEqual(set(subparsers.choices), set(COMMANDS))
        self.assertTrue(all(callable(handler) for handler in COMMANDS.values()))


if __name__ == "__main__":
    unittest.main()
