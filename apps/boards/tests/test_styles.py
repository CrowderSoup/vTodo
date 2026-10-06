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


def test_mobile_nav_filter_bar_wraps_to_its_own_row():
    """On narrow screens the board's Archive/Filters bar must drop to a row of its
    own below the brand/hamburger/avatar row -- sharing one non-wrapping row with
    them overflowed and visually overlapped the brand (nav items don't shrink
    below their content's min-content width by default)."""
    css = CSS_PATH.read_text()

    assert "@media (max-width: 820px)" in css
    assert "flex-wrap: wrap;\n    border-radius: 16px;" in css
    assert "flex-basis: 100%;" in css


def test_nav_filter_slot_spaces_its_buttons():
    """Filters and Archive done cards sit side by side in the header; without a
    gap they butt right up against each other."""
    css = CSS_PATH.read_text()

    assert (
        ".nav-filter-slot {\n"
        "  display: flex;\n"
        "  align-items: center;\n"
        "  gap: 0.5rem;\n"
    ) in css
