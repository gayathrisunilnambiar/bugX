# Sentinel Bisect report

## Confirmed introducing commit

`4d55af94be70f9781f97dac95343a0231d1a4d1c`

## Search timeline

```text
FLAKY 1b1e9dca495f  flaky  (3 runs, retry 0)
PASS bba11ea5357a  pass  (3 runs, retry 0)
      ^ substituted for flaky 1b1e9dca495f (routed around to keep searching)
FAIL 4d55af94be70  fail  (3 runs, retry 0)
PASS 670ff966b587  pass  (3 runs, retry 0)
```

Flaky commits observed: 1b1e9dca495f. They were excluded from trusted pass/fail boundary decisions.

The search routed around one or more persistently-flaky commits by substituting an adjacent commit as the decision point.
