PY ?= python3
export PYTHONPATH := src

.PHONY: install test gate gate-regressed demo clean

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

clean:
	rm -rf evals/_runs demo/_scratch
