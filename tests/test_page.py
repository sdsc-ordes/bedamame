import page_counts


def test_architecture_page_counts_are_current():
    page = page_counts.PAGE.read_text()
    assert page_counts.fill(page) == page, "the counts are stale: run `just page-counts`"
