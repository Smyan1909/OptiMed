from datetime import datetime, timedelta, timezone

import pytest 

from optimed.core.domain import (
    PatientContext,
    Encounter,
    BedState,
    BedStatus,
    EncounterStatus,
    InfoEvent,
    EventType,
    Notification,
    NotificationStatus,
    Channel,
    CommThread,
    KPIEvent,
    Alert,
    Severity,
)

# ----------------------------------------------------------------------------
# Fixtures -------------------------------------------------------------------
# ----------------------------------------------------------------------------

NOW = datetime.now(timezone.utc)

@pytest.fixture
def patient_ctx() -> PatientContext:
    return PatientContext(
        patient_id="P123",
        name="Anna",
        age=67,
        sex="F",
        care_unit="Ward A",
        vitals={"hr": "72"},
        labs={"K⁺": "6.2"},
        updated_at=NOW,
    )

@pytest.fixture
def bed_state() -> BedState:
    return BedState(
        bed_id="A12",
        care_unit="Ward A",
        status=BedStatus.VACANT,
        since=NOW - timedelta(minutes=42),
    )

# ----------------------------------------------------------------------------
# PatinentContext Tests ---------------------------------------------------
# ----------------------------------------------------------------------------

def test_patient_critical_lab_detection(patient_ctx: PatientContext):
    assert patient_ctx.has_critical_lab() is True
    msgs = patient_ctx.critical_lab_msgs()
    assert len(msgs) == 1 and "Potassium" in msgs[0]


# ----------------------------------------------------------------------------
# BedState Tests -------------------------------------------------------------
# ----------------------------------------------------------------------------

def test_bed_idle_minutes(bed_state: BedState):
    assert bed_state.idle_minutes(NOW) == 42

# ----------------------------------------------------------------------------
# Encounter Tests -----------------------------------------------------------
# ----------------------------------------------------------------------------

def test_encounter_los_calculation():
    enc = Encounter(encounter_id="E1",
        patient_id="P123",
        status=EncounterStatus.IN_PROGRESS,
        admit_ts=NOW - timedelta(days=2, hours=3),
        discharge_ts=None,
        bed_history=[],
    )
    los = enc.length_of_stay(NOW)
    assert los.days == 2 and los.seconds // 3600 == 3

# ----------------------------------------------------------------------------
# InfoEvent Tests -----------------------------------------------------------
# ----------------------------------------------------------------------------

def test_infoevent_routing():
    event = InfoEvent(
        event_id="EVT1",
        patient_id="P123",
        type=EventType.LAB_CRIT,
        payload_json="{}",
        created_at=NOW,
    )

    policy = {EventType.LAB_CRIT: ["RN1", "MD1"]}
    assert event.route_targets(policy) == ["RN1", "MD1"]

# ----------------------------------------------------------------------------
# Notification Tests --------------------------------------------------------
# ----------------------------------------------------------------------------

def test_notification_acknowledgment():
    n = Notification(
        notification_id="N1",
        event_id="EVT1",
        recipient_ids=["RN1"],
        channel=Channel.TEAMS,
        delivered_at=NOW,
    )
    n2 = n.acknowledge(NOW + timedelta(seconds=30))
    assert n2.status == NotificationStatus.ACK
    assert n2.ack_at == NOW + timedelta(seconds=30)
    # original immutable
    assert n.status == NotificationStatus.DELIVERED

# ----------------------------------------------------------------------------
# CommThread Tests ----------------------------------------------------------
# ----------------------------------------------------------------------------

def test_commthread_add_notification():
    n = Notification(
        notification_id="N2",
        event_id="EVT1",
        recipient_ids=["RN1"],
        channel=Channel.IN_APP,
        delivered_at=NOW,
    )
    thread = CommThread(thread_id="T1")
    thread2 = thread.add_notification(n)
    assert len(thread2.notifications) == 1
    assert thread.notifications == []  # immutability

# ----------------------------------------------------------------------------
# KPIEvent Tests -----------------------------------------------------------
# ----------------------------------------------------------------------------

def test_kpievent_roundtrip():
    kpi = KPIEvent(metric="AAT", value=82.0, unit="s", recorded_at=NOW)
    raw = kpi.model_dump()
    kpi2 = KPIEvent.model_validate(raw)
    assert kpi == kpi2

def test_alert_escalate():
    a = Alert(alert_id="AL1", message="Low battery", severity=Severity.LOW, created_at=NOW)
    a2 = a.escalate()
    assert a2.severity == Severity.MEDIUM
    # second escalate reaches HIGH
    assert a2.escalate().severity == Severity.HIGH