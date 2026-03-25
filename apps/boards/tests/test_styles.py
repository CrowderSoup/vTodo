from pathlib import Path


CSS_PATH = Path(__file__).resolve().parents[3] / "static" / "app.css"


def test_inline_task_edit_form_stacks_two_column_fields():
    css = CSS_PATH.read_text()

    assert (
        ".task-card--editing .form-grid--two {\n"
        "  grid-template-columns: 1fr;\n"
        "}\n"
    ) in css


def test_mobile_two_column_form_grid_stacks_fields():
    css = CSS_PATH.read_text()

    assert "@media (max-width: 640px)" in css
    assert (
        "  .form-grid--two {\n"
        "    grid-template-columns: 1fr;\n"
        "  }\n"
    ) in css
