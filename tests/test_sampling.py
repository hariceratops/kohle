import pytest

pytestmark = pytest.mark.skip(reason="scaffold: filled in by issues 045-046")


def test_sample_dates_are_the_15th_and_month_end_plus_final_row_at_to():
    # TODO(045)
    ...


def test_working_day_excludes_weekends_state_holidays_and_dec_24_and_31():
    # TODO(046): Bavaria vs Berlin on 2029-05-31; December 2028 lands on 29 Dec
    ...


def test_holidays_package_accepts_all_sixteen_state_codes():
    # TODO(046)
    ...


def test_snapshot_per_date_equals_aggregate_by_unit_of_the_prefix():
    # TODO(045)
    ...
