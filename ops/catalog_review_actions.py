from __future__ import annotations


def classify_action_command(command: str) -> dict:
    if " verify" in command:
        kind = "verify"
    elif " repair" in command or (" apply " in command and "--dry-run" not in command):
        kind = "mutate"
    elif " apply " in command and "--dry-run" in command:
        kind = "narrow"
    elif " list " in command:
        kind = "inspect"
    else:
        kind = "inspect"
    intent = {
        "inspect": "gather-evidence",
        "narrow": "reduce-review-scope",
        "mutate": "change-review-state",
        "verify": "check-artifact-health",
    }[kind]
    return {
        "kind": kind,
        "intent": intent,
        "command": command,
        "dryRunSafe": kind in {"inspect", "narrow", "verify"},
    }


def build_action_ref(command: str | None) -> dict | None:
    if not command:
        return None
    return classify_action_command(command)


def build_action_bundle(*, primary_command: str | None, followup_command: str | None) -> list[dict]:
    actions: list[dict] = []
    if primary_command:
        primary_action = classify_action_command(primary_command)
        primary_action["role"] = "primary"
        actions.append(primary_action)
    if followup_command:
        followup_action = classify_action_command(followup_command)
        followup_action["role"] = "followup"
        actions.append(followup_action)
    return actions


def build_action_plan(
    *,
    primary_command: str | None,
    followup_command: str | None,
    source: str = "ad-hoc",
    source_mode: str | None = None,
) -> dict:
    actions = build_action_bundle(
        primary_command=primary_command,
        followup_command=followup_command,
    )
    plan = {
        "source": source,
        "sourceMode": source_mode,
        "primary": None,
        "followup": None,
        "actions": actions,
    }
    if actions:
        plan["primary"] = actions[0]
    if len(actions) > 1:
        plan["followup"] = actions[1]
    return plan


def with_starter_plan(
    playbook: dict,
    *,
    primary_command: str | None,
    followup_command: str | None,
    source_mode: str | None = None,
) -> dict:
    starter_plan = build_action_plan(
        primary_command=primary_command,
        followup_command=followup_command,
        source="playbook",
        source_mode=source_mode or playbook.get("mode"),
    )
    enriched = dict(playbook)
    enriched["starterPlan"] = starter_plan
    enriched["firstAction"] = starter_plan["primary"]
    enriched["firstCommand"] = starter_plan["primary"]["command"] if starter_plan["primary"] else None
    return enriched


def with_starter_plan_from_actions(
    playbook: dict,
    recommended_actions: list[dict],
    *,
    source_mode: str | None = None,
) -> dict:
    primary_action = next(
        (
            action for action in recommended_actions
            if action.get("commandAction", {}).get("kind") == "inspect"
        ),
        recommended_actions[0] if recommended_actions else None,
    )
    followup_action = next(
        (
            action for action in recommended_actions
            if primary_action and action.get("command") != primary_action.get("command")
        ),
        None,
    )
    return with_starter_plan(
        playbook,
        primary_command=primary_action.get("command") if primary_action else None,
        followup_command=followup_action.get("command") if followup_action else None,
        source_mode=source_mode,
    )


def with_action_plan_fields(payload: dict, action_plan: dict) -> dict:
    enriched = dict(payload)
    enriched["actionPlan"] = action_plan
    enriched["recommendedCommand"] = action_plan["primary"]["command"] if action_plan["primary"] else None
    enriched["followupCommand"] = action_plan["followup"]["command"] if action_plan["followup"] else None
    enriched["actionCommands"] = action_plan["actions"]
    return enriched
