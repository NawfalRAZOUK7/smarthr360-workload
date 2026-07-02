# smarthr360-workload

**Mental workload microservice of the SmartHR360 platform (Module 1).**
Implements the cahier des charges "Calculateur de charge mentale":
real cognitive load beyond hours worked, burnout-risk alerts, and
rebalancing recommendations.

Part of [SmartHR360](https://github.com/NawfalRAZOUK7/smarthr360).

## The scoring model

Five dimensions (rapport §3.2), each normalized 0..1, weighted into a
0-100 score:

| Dimension | Source | Weight |
|---|---|---|
| Work volume | open tasks' estimated hours vs 40h capacity (+15% penalty on unplanned tasks) | 0.30 |
| Cognitive complexity | average task complexity (1-5) | 0.20 |
| Deadline pressure | share of open tasks due within 3 days | 0.20 |
| Interruptions & meetings | latest daily workday signal | 0.15 |
| Self-reported stress | latest daily signal (1-5) | 0.15 |

Levels: `<50 OK` · `50-70 ELEVATED` · `70-85 HIGH (warning alert)` ·
`≥85 BURNOUT_RISK (critical alert)`. Alerts carry actionable
recommendations (delegate, renegotiate deadlines, block focus time…).

## API

| Endpoint | Who | Purpose |
|---|---|---|
| `POST/GET /api/workload/tasks/` | self; managers may assign/read others | task management |
| `POST/GET /api/workload/signals/` | self-reported | daily meetings/interruptions/stress |
| `POST /api/workload/scores/compute/` | self; managers via `?user_id=` | run the engine |
| `GET /api/workload/scores/` | self / managers | score history |
| `GET /api/workload/alerts/` + `POST …/acknowledge/` | employees see own; managers acknowledge | alerting |
| `GET /api/workload/team-overview/?user_ids=…` | managers/HR | latest score per employee |

Identity: RS256 JWT from smarthr360-auth, verified locally
(`smarthr360-jwt-auth`); users exist here only as `user_id` (ADR-005).

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate && python manage.py runserver 0.0.0.0:8005
```

Tests: `python manage.py test` (10 tests: engine correctness + API authorization)
