# An open-source approval policy for human in the loop vs human on the loop

The distinction between human in the loop and human on the loop is usually
settled in a meeting, then lost in a settings screen. This repository makes the
decision a file: one `kortix.yaml` that says, per action, whether the agent
runs, waits for a person, or is refused, plus a short script that evaluates
sample calls against it so you can see which calls a reviewer would be shown
before anyone connects a real account.

It is a companion to
[human in the loop vs human on the loop](https://humanintheloopvshumanontheloop.com),
and the policy format is
[Kortix](https://kortix.com), the open-source AI Operating System.

## The distinction is per action, not per system

Human in the loop (HITL) means a person decides before the action runs. Human on
the loop (HOTL) means the system acts and a person supervises, with the power to
stop, override or change the rule. Neither is a property of "the agent". A
support agent that reads an inbox and refunds a charge needs the first for the
refund and can live with the second for the read. Written as a per-action
policy, the two models stop competing and become two rows in the same file.

Two failure modes follow, and the file has to answer both:

- **In the loop fails through fatigue.** A reviewer who approves a long run of
  correct proposals stops reading closely, and the approval becomes delay
  without safety. The fix is not more approvals; it is approvals bound to the
  exact call and its arguments, so a blanket yes is not available.
- **On the loop fails through silence.** A supervisor who is never told which
  call crossed a line cannot intervene. The fix is a rule narrow enough that the
  crossing produces a held call or a block, not a log line nobody reads.

## What the file says

`kortix.yaml` in this repository is the whole example. Its shape:

```yaml
policy:
  default_mode: risk          # reads run, writes and destructive actions wait

policies:                     # project-wide, fully qualified patterns
  - match: "*.*delete*"
    action: block
  - match: "stripe.refund"
    action: require_approval
    conditions:
      - arg: amount
        match: "[0-9][0-9][0-9][0-9]*"

connectors:
  - slug: gmail
    policies:                 # relative to the connector, first match wins
      - match: "send_email"
        action: always_run
        conditions:
          - arg: to
            match: "*@yourcompany.com"
      - match: "send_*"
        action: require_approval
      - match: "get_*"
        action: always_run
```

The three actions are Allow (`always_run`), Ask (`require_approval`) and Block
(`block`), and Kortix evaluates them in a fixed order, first match wins: the
project's `policies`, then the connector's own `policies`, then
`sensitive: true` on the connector (every remaining action needs approval,
reads included), then `policy.default_mode`. `allow_all` is the default and
runs every action no rule matched. `risk` runs reads and holds writes and
destructive actions.

Rules can test the call's arguments, which is what makes a narrow rule cheaper
than a review meeting: `arg` is a dot path into the arguments, `match` is a
glob (case-insensitive) or a `/regex/` in slashes, and a rule holds up to ten
conditions that must all match. A missing argument never matches, so a negated
condition on it holds. A malformed condition fails closed: it never opens an
action.

## Run the check

```bash
uv run --with pyyaml python check_calls.py
```

Expected output, which the script asserts against `expected.txt`:

```
read-inbox        run      gmail rule get_*
reply-internal    run      gmail rule send_email
reply-external    held     gmail rule send_*
read-balance      run      stripe rule get_*
refund-small      held     stripe rule create_refund
refund-large      held     project-wide rule stripe.refund
delete-customer   blocked  project-wide rule *.*delete*
```

Read the second and third rows together. The same action, `gmail.send_email`,
runs for an internal recipient and is held for an external one, because the
first matching rule carries the argument condition. Delete the specific
`send_email` rule and both calls are held: that is the rule order doing the
work, not the intent of whoever wrote the connector grant.

The fifth and sixth rows show why the argument condition belongs in a
project-wide rule. `stripe.create_refund` is already held by the connector, but
`stripe.refund` is a second action on the same object, and a policy that names
one action and not its sibling holds nothing. The project-wide rule catches
both and can test the amount.

## What happens when Ask fires

An Ask is not a notification. The call returns `202` with
`status: "pending_approval"`, an `approval_url`, an `approval_summary` and an
`execution_id`; nothing ran. The approval covers one exact request, the same
connector, action, arguments and account, so a changed argument needs a new
decision. After approval, the identical call runs once if it repeats within
fifteen minutes. A held call expires when nobody decides it within 24 hours (or
the project's `approvals.ttl`) and the session does not resume, so the agent
asks again with a new call. There is no session-wide approval: an action that
must run unattended needs an Allow rule, and that is a decision to write down
rather than a default to inherit.

## Where this fits in Kortix

Kortix keeps the agents, skills, memory and connector rules as files in a git
repository the company owns, and every session runs on its own cloud computer.
Approval gates are off until you set them. A change to the policy is a change to
a file, so it arrives as a diff a colleague can review: session work reaches
main through a change request and merge is default-deny for agents. Run it on
Kortix Cloud, in your VPC, or on your own on-prem network.

- Source of the policy semantics:
  [connectors](https://kortix.com/docs/connect/connectors)
- [Kortix on GitHub](https://github.com/kortix-ai/suna)
- [kortix.com](https://kortix.com)

`check_calls.py` is a reading aid, not the product: it replays the documented
rule order over a fixed list of calls, and its `default_mode: risk` heuristic
treats actions whose names start with `get_`, `list_`, `search_`, `retrieve` or
`read_` as reads. Kortix itself decides that, and it decides on live calls.

## Where the site takes each case further

The site that goes with this repo makes the same argument one question at a time. If the definition is the part you need, [what human in the loop means for an agent](https://humanintheloopvshumanontheloop.com/human-in-the-loop) is the page that starts from the approve-before-act model. For the other mode, [human on the loop](https://humanintheloopvshumanontheloop.com/human-on-the-loop) covers supervision with the power to stop a call, which is the mode this repo's Allow rows run under. The third position, where a person sets the goal and reads the outcome, is [human over the loop](https://humanintheloopvshumanontheloop.com/human-over-the-loop). When the argument in this repo has to become a decision for your own agent, [how to choose between the two models](https://humanintheloopvshumanontheloop.com/how-to-choose) turns the table above into questions about your own calls. And the mechanics of the held call, from the `202` record to the 24-hour expiry, are on the [approval workflow page](https://humanintheloopvshumanontheloop.com/approval-workflow).
