# Disabled supervised battery commissioning rehearsal

`supervised-commissioning-fake-v1` is a local operator wrapper around the existing
`DisabledExecutor`, `Journal` and exact `FakeTransport` type. It is not wired to
the collector, dashboard, configuration or Home Assistant. There is no live mode,
network client, scheduler, credentials, generic service endpoint or return-command
transport. Importing it performs no I/O. Production and research rules are unchanged.

A commissioning intent has a distinct purpose and exact approval binding. It is
not an economic recommendation. The synthetic values in tests are test inputs,
not proposed inverter/site permissions or Gate B limits. Export is explicitly
unsupported by this wrapper. Every physical action remains blocked until its
separate approved Gate B manifest supplies the actual interface, installed source,
limits, valid window, ownership, feedback and termination/recovery evidence.

## Operator seam

An explicit `Envelope` binds source/interface/ordinary-state descriptions,
allowed modes, capacity and SOC bounds, send-time freshness, feedback timeout,
approval age, exact import price, separate site import/export caps and independent
recovery description. It has no installation defaults. Fake send-time freshness,
feedback and approval limits may be at most 60 seconds; this is a local refusal
ceiling, not a verified engineering requirement. The proposed real send-time
requirement and actual source cadence must be resolved in the Gate B manifest.
The research SOC freshness rule remains 600 seconds.

`propose()` returns the complete intent/envelope and approval binding. `approve()`
requires that exact binding, original actor, valid clock and unexpired window.
`reject()` sends nothing. `dispatch()` requires fresh advancing post-approval
physical-frame evidence, original device/owner/generation, exactly one declared
owner, permitted mode, grid/health/service availability, unchanged price/input
binding, verified independent device expiry and a verified recovery contract.
It checks capacity/SOC/reserve, battery power/energy/cost/throughput and separate
site-flow limits. The charging energy bound uses conservative stored-energy
headroom rather than inventing an efficiency. Actual AC/DC meanings and losses
remain a Gate B source/physical-validation requirement.

The exact-type fake transport guard rejects arbitrary objects and subclasses.
No boolean, snapshot or permission switch can enable a real transport. A reachable
human recovery route is recorded separately; it never sets device expiry verified.
The existing adapter therefore refuses a no-device-expiry route. A later owner
approved supervised human-recovery route needs an explicit adapter amendment;
it is not silently admitted by this rehearsal.

## Feedback, termination and restart

ACKNOWLEDGED means a fake write receipt, never physical success. The initial
physical-effect deadline is anchored to SENT. Fresh optimistic state without a
measured charging effect cannot reset that deadline. Charging requires positive
battery charging power or positive cumulative charge/stored-energy evidence;
self-declared success with zero delivery remains ACKNOWLEDGED. Preservation's
zero-discharge effect is distinct. Battery AC magnitude/direction, cumulative
energy/throughput, stored energy, positive import-cost exposure, and net site
import/export are separate fields. Gross positive import exposure is nonnegative;
it is not net billing or a savings calculation.

Each accepted feedback device frame must advance. Invalid/future/stale samples,
clock discontinuity, malformed numbers, exceeded site/battery/energy/cost/SOC
bounds, regressing cumulative evidence, missing service/grid/BMS health or an
unexpected mode stop the rehearsal and require human recovery. Missing delivery
values remain missing; unknown delivery is never replaced by zero. A power-time
upper bound rejects impossible cumulative delivery (1e-9 kWh numeric tolerance).
UTC is canonical internally; fixture parser offsets normalize to UTC before
approval hashing. Direct non-UTC API evidence fails closed.

The journal retains PROPOSED, APPROVED, PRECHECKED, SENT, ACKNOWLEDGED,
EFFECT_OBSERVED, COMPLETED, EXPIRED, UNKNOWN_DELIVERY and the existing
RESTORE_FAILED state (reported meaning RETURN_FAILED). Completion/expiry requires
fresh witnessed ordinary state before NEUTRAL_STATE_VERIFIED. Return is an
observation/reconciliation operation here, not an unverified automatic command.
Lost acknowledgement and restart after SENT never retry. At most one active
intent is permitted by the existing journal uniqueness rule.

A newer manual owner/generation wins and prevents restoration. ABORTED remains
held for explicit human reconciliation and a new owner review; this wrapper has
no automatic release/recovery-after-override path. Restart before send requires
a new intent; persisted approval is not a queue. Database failure raises/refuses;
software on the unavailable host cannot enforce inverter expiry. Fakes do not
validate a device protocol, fail-safe, acknowledgement or physical response.

## CLI

`tools/rehearse_supervised_pilot.py` accepts bounded explicit JSON fixtures and an
owned `*.pilot.sqlite3` journal. Existing unowned databases are refused before any
schema mutation. It reads no environment/production settings. Fixtures are strict
constructor-shaped JSON, at most 16 KiB. Fields are never guessed or defaulted.

Commands are `propose --fixture`, `reject --key`, `approve --key --binding
--operator`, `rehearse --key --binding --operator --state-fixture`,
`record-feedback --key --fixture`, and `status --key`. All mutating approval/time
commands require explicit aware synthetic `--at`; proposal/approval/rehearsal also
require `--monotonic`. `rehearse` performs exact approval and one fake dispatch in
the same process. `approve` records approval only; a later process cannot dispatch
that approval after restart. `--lost-ack` injects ambiguity without retry.

A status record contains the proposed action, exact maxima, expiry, approval
identity, current lifecycle, safety reasons and effect/recovery evidence. No CLI
command can address a physical device. Evidence records are at most 16 KiB and
256 per intent, with indexed bounded reads. On exhaustion, evidence is not silently
pruned; the local rehearsal refuses and requires human review.

The tests cover approval/replay/rejection, price/input change, capacity saturation,
expiry, partial/unknown delivery, duplicate intent, lost ACK, no retry, unexpected
flow, manual override, network/HA/app/DB outages, clock jumps, restart, optimistic
ACK with no measured effect, missing feedback and failed/witnessed return. These
are software rehearsal results, not real protocol or physical certification.
