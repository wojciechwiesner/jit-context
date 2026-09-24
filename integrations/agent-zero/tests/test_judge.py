from jev_bridge.judge import classify_turn, fact_hit, tokens

FACTS = [
    {"key": "phase_6_module", "value": "audit_exporter.py"},
    {"key": "phase_5_module", "value": "settlement_pipeline.py"},
    {"key": "phase_4_module", "value": "psp_gateway.py"},
    {"key": "phase_3_module", "value": "fraud_detector.py"},
]

def test_tokens_filters_stopwords():
    t = tokens("The phase_6_module and audit_exporter are deployed")
    assert "phase_6_module" in t and "the" not in t

def test_helpful_when_facts_echoed():
    resp = "W module audit_exporter.py oraz psp_gateway.py dodałem telemetry"
    assert classify_turn(FACTS, resp) == "HELPFUL"

def test_neutral_when_no_overlap():
    assert classify_turn(FACTS, "answer about cooking pasta carbonara recipe") == "NEUTRAL"

def test_neutral_when_no_facts():
    assert classify_turn([], "anything") == "NEUTRAL"

def test_harmful_on_invariant_flags():
    assert classify_turn(FACTS, "phase_6_module audit_exporter used here", invariant_flags=1) == "HARMFUL"
