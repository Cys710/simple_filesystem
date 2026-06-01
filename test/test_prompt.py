import importlib.util
import os
import sys
import unittest
from unittest.mock import patch


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJECT_ROOT, "src")

sys.path.insert(0, SRC)


@unittest.skipUnless(
    importlib.util.find_spec("prompt_toolkit"),
    "prompt-toolkit is not installed",
)
class TestPromptCompleter(unittest.TestCase):
    def test_replaces_active_token_and_appends_space(self):
        from prompt_toolkit.document import Document

        from cli.completion import CommandCompleter
        from cli.prompt import PromptCompleter

        completer = PromptCompleter(CommandCompleter(lambda: None))

        results = list(completer.get_completions(Document("mon"), None))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].text, "monitor ")
        self.assertEqual(results[0].start_position, -3)

    def test_prompt_reader_uses_readline_style_completion(self):
        from prompt_toolkit.shortcuts import CompleteStyle

        from cli.completion import CommandCompleter
        from cli.prompt import PromptReader

        with patch("cli.prompt.PromptSession") as session:
            PromptReader(CommandCompleter(lambda: None))

        self.assertEqual(
            session.call_args.kwargs["complete_style"],
            CompleteStyle.READLINE_LIKE,
        )


if __name__ == "__main__":
    unittest.main()
