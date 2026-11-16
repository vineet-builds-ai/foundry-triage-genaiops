PY ?= python3
export PYTHONPATH := src

.PHONY: install test gate gate-regressed demo serve smoke clean

install:
	$(PY) -m pip install -r requirements-dev.txt

test:
	$(PY) -m pytest -q

# Evaluate the current agent version against the acceptance thresholds.
gate:
	$(PY) -m evals.run_gate --manifest agent/agent.yaml --env acceptance

# Evaluate the deliberately regressed version. Expected to FAIL (exit 1).
gate-regressed:
	$(PY) -m evals.run_gate --manifest agent/agent.regressed.yaml --env acceptance

# Full side-by-side demo: a passing gate, then a blocked regression.
demo:
	$(PY) demo/run_demo.py

# Run the HTTP service locally (offline backend unless FOUNDRY_PROJECT_ENDPOINT is set).
serve:
	$(PY) -m uvicorn triage.api:app --port 8000

# Smoke test a running service. URL defaults to the local one.
URL ?= http://127.0.0.1:8000
smoke:
	$(PY) scripts/smoke_test.py --url $(URL)

clean:
	rm -rf evals/_runs demo/_scratch
