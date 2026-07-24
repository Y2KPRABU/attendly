import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

streamlit_stub = types.ModuleType("streamlit")
streamlit_stub.session_state = {}
streamlit_stub.query_params = {}
streamlit_stub.markdown = lambda *args, **kwargs: None
streamlit_stub.html = lambda *args, **kwargs: None
streamlit_stub.warning = lambda *args, **kwargs: None
streamlit_stub.info = lambda *args, **kwargs: None
streamlit_stub.table = lambda *args, **kwargs: None
streamlit_stub.header = lambda *args, **kwargs: None
streamlit_stub.form = lambda *args, **kwargs: None
streamlit_stub.form_submit_button = lambda *args, **kwargs: False
streamlit_stub.radio = lambda *args, **kwargs: None
streamlit_stub.text_input = lambda *args, **kwargs: ""
streamlit_stub.number_input = lambda *args, **kwargs: 0
streamlit_stub.success = lambda *args, **kwargs: None
streamlit_stub.rerun = lambda *args, **kwargs: None
streamlit_stub.set_page_config = lambda *args, **kwargs: None
streamlit_stub.components = types.SimpleNamespace(v1=types.SimpleNamespace())
sys.modules.setdefault("streamlit", streamlit_stub)
sys.modules.setdefault("streamlit.components", types.ModuleType("streamlit.components"))
sys.modules.setdefault("streamlit.components.v1", types.ModuleType("streamlit.components.v1"))

import streamlit_app


class RenderInfoHtmlTests(unittest.TestCase):
    def test_render_info_html_handles_title_case_row_keys(self):
        event = {"id": "Ev001", "name": "Family"}
        registrations = [
            {"response": "Yes", "main_name": "Demo attendee", "adult_count": 2, "child_count": 1}
        ]

        with patch.object(streamlit_app, "load_static_html", return_value="<table>{rows}</table>"), patch.object(
            streamlit_app.st, "html"
        ) as mock_html:
            streamlit_app.render_info_html(event, registrations)

        self.assertTrue(mock_html.called)
        rendered_html = mock_html.call_args.args[0]
        self.assertIn("Demo attendee", rendered_html)
        self.assertIn("Yes", rendered_html)


if __name__ == "__main__":
    unittest.main()
