import unittest

from gt7dashboard import gt7help


class TestGt7Help(unittest.TestCase):
    def test_get_help_text_resource_uses_stable_ascii_icon(self):
        html = gt7help.get_help_text_resource("foo")

        self.assertIn(">?</div>", html)
        self.assertIn("border-radius:50%", html)
        self.assertNotIn("?⃝", html)

    def test_get_help_text_resource_escapes_tooltip_quotes(self):
        html = gt7help.get_help_text_resource('say "hello"')

        self.assertIn('title="say &quot;hello&quot;"', html)
