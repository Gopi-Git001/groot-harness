"""Registered-but-unimplemented tools. Each tells the agent to proceed without it."""


def make_stub(name: str, available_in: str):
    def stub(ctx, **_args) -> str:
        return (
            f"Tool '{name}' is registered but not implemented until {available_in}. "
            "Proceed without it, and state in your rationale what you would have checked."
        )

    return stub
