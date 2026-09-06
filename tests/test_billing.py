from datetime import date, datetime, timedelta, timezone

from app.models.reading_window import ReadingWindow
from app.models.tariff_config import TariffConfig
from app.services.billing import (
    DEFAULT_FIXED_CHARGE,
    DEFAULT_SLABS,
    compute_bill_amount,
    generate_bill_for_cycle,
)


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _default_tariff() -> TariffConfig:
    """Transient (non-persisted) tariff matching the documented default:
    0-100 kWh @ Rs.5.00, 101-300 @ Rs.7.50, 300+ @ Rs.10.00, Rs.50 fixed."""
    return TariffConfig(slabs=DEFAULT_SLABS, fixed_charge=DEFAULT_FIXED_CHARGE)


def _seed_tariff(db_session, admin_id, effective_from: date) -> TariffConfig:
    tariff = TariffConfig(
        effective_from=effective_from,
        slabs=DEFAULT_SLABS,
        fixed_charge=DEFAULT_FIXED_CHARGE,
        created_by=admin_id,
    )
    db_session.add(tariff)
    db_session.commit()
    db_session.refresh(tariff)
    return tariff


def _add_window(db_session, meter_id, window_start: datetime, energy_kwh: float) -> ReadingWindow:
    window = ReadingWindow(
        meter_id=meter_id,
        window_start=window_start,
        window_end=window_start + timedelta(minutes=15),
        avg_voltage=230.0,
        avg_current=10.0,
        avg_power=2300.0,
        power_variance=1.0,
        reading_count=5,
        energy_kwh=energy_kwh,
        is_anomaly=False,
    )
    db_session.add(window)
    db_session.flush()
    return window


def test_compute_bill_amount_spans_all_three_slabs():
    tariff = _default_tariff()
    # 100 kWh @ 5.00 = 500.00
    # 200 kWh @ 7.50 = 1500.00 (units 101-300)
    # 50 kWh @ 10.00 = 500.00 (units 301-350)
    # + Rs.50 fixed charge
    # total = 500 + 1500 + 500 + 50 = 2550.00
    assert compute_bill_amount(350, tariff) == 2550.00


def test_compute_bill_amount_within_first_slab_only():
    tariff = _default_tariff()
    # 60 kWh @ 5.00 = 300.00 + Rs.50 fixed = 350.00
    assert compute_bill_amount(60, tariff) == 350.00


def test_compute_bill_amount_at_exact_slab_boundary():
    tariff = _default_tariff()
    # Exactly 100 kWh should be entirely at the first slab's rate (0-100 inclusive).
    assert compute_bill_amount(100, tariff) == 550.00  # 100*5 + 50 fixed


def test_generate_bill_for_cycle_matches_seeded_energy(db_session, seed_users_and_meters):
    admin = seed_users_and_meters["admin"]
    meter_a = seed_users_and_meters["meter_a"]
    cycle_start = date(2026, 1, 1)
    cycle_end = date(2026, 1, 31)
    _seed_tariff(db_session, admin.id, date(2025, 12, 1))

    _add_window(db_session, meter_a.id, datetime(2026, 1, 5, tzinfo=timezone.utc), 40.0)
    _add_window(db_session, meter_a.id, datetime(2026, 1, 15, tzinfo=timezone.utc), 60.0)
    # Outside the cycle — must not be counted.
    _add_window(db_session, meter_a.id, datetime(2026, 2, 1, tzinfo=timezone.utc), 1000.0)
    db_session.commit()

    bill, error = generate_bill_for_cycle(db_session, meter_a.id, cycle_start, cycle_end)

    assert error is None
    assert bill is not None
    assert float(bill.units_consumed_kwh) == 100.0
    assert float(bill.amount) == 550.00  # 100 kWh entirely in slab 1: 100*5 + 50
    assert bill.has_no_readings is False


def test_duplicate_bill_generation_rejected_by_db_constraint(db_session, seed_users_and_meters):
    admin = seed_users_and_meters["admin"]
    meter_a = seed_users_and_meters["meter_a"]
    cycle_start = date(2026, 1, 1)
    cycle_end = date(2026, 1, 31)
    _seed_tariff(db_session, admin.id, date(2025, 12, 1))
    _add_window(db_session, meter_a.id, datetime(2026, 1, 5, tzinfo=timezone.utc), 40.0)
    db_session.commit()

    first_bill, first_error = generate_bill_for_cycle(db_session, meter_a.id, cycle_start, cycle_end)
    assert first_bill is not None
    assert first_error is None

    second_bill, second_error = generate_bill_for_cycle(db_session, meter_a.id, cycle_start, cycle_end)
    assert second_bill is None
    assert second_error is not None
    assert "already exists" in second_error

    from app.models.bill import Bill

    count = (
        db_session.query(Bill)
        .filter(Bill.meter_id == meter_a.id, Bill.cycle_start == cycle_start)
        .count()
    )
    assert count == 1


def test_zero_reading_cycle_still_produces_a_bill(db_session, seed_users_and_meters):
    admin = seed_users_and_meters["admin"]
    meter_a = seed_users_and_meters["meter_a"]
    cycle_start = date(2026, 3, 1)
    cycle_end = date(2026, 3, 31)
    _seed_tariff(db_session, admin.id, date(2025, 12, 1))
    # No reading_windows for meter_a in this cycle at all.

    bill, error = generate_bill_for_cycle(db_session, meter_a.id, cycle_start, cycle_end)

    assert error is None
    assert bill is not None
    assert float(bill.units_consumed_kwh) == 0.0
    assert float(bill.amount) == DEFAULT_FIXED_CHARGE  # just the fixed charge
    assert bill.has_no_readings is True


def test_get_bills_for_meter_ownership(client, db_session, seed_users_and_meters):
    admin = seed_users_and_meters["admin"]
    meter_a = seed_users_and_meters["meter_a"]
    _seed_tariff(db_session, admin.id, date(2025, 12, 1))
    _add_window(db_session, meter_a.id, datetime(2026, 1, 5, tzinfo=timezone.utc), 40.0)
    db_session.commit()
    generate_bill_for_cycle(db_session, meter_a.id, date(2026, 1, 1), date(2026, 1, 31))

    owner_resp = client.get(f"/api/bills/{meter_a.id}", headers=auth_headers(seed_users_and_meters["token_a"]))
    assert owner_resp.status_code == 200
    assert len(owner_resp.json()) == 1

    other_resp = client.get(f"/api/bills/{meter_a.id}", headers=auth_headers(seed_users_and_meters["token_b"]))
    assert other_resp.status_code == 403


def test_bill_pdf_download_ownership(client, db_session, seed_users_and_meters):
    admin = seed_users_and_meters["admin"]
    meter_a = seed_users_and_meters["meter_a"]
    _seed_tariff(db_session, admin.id, date(2025, 12, 1))
    _add_window(db_session, meter_a.id, datetime(2026, 1, 5, tzinfo=timezone.utc), 40.0)
    db_session.commit()
    bill, _ = generate_bill_for_cycle(db_session, meter_a.id, date(2026, 1, 1), date(2026, 1, 31))

    other_resp = client.get(
        f"/api/bills/{bill.id}/pdf", headers=auth_headers(seed_users_and_meters["token_b"])
    )
    assert other_resp.status_code == 403

    owner_resp = client.get(
        f"/api/bills/{bill.id}/pdf", headers=auth_headers(seed_users_and_meters["token_a"])
    )
    assert owner_resp.status_code == 200
    assert owner_resp.headers["content-type"] == "application/pdf"
    assert owner_resp.content[:4] == b"%PDF"
