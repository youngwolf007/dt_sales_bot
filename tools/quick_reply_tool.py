from agents import function_tool


@function_tool
def offer_quick_replies(options: list[str]) -> str:
    """
    Call this whenever you end your reply with a question that has a small
    number of clear, discrete answer choices (e.g. "Would you like the
    proposal emailed, or more technical detail first?", "Shall I go ahead
    and send it?"). Provide 2-4 short reply labels (a few words each) that
    map directly to the choices you just offered — the customer will see
    these as clickable buttons alongside your message, so word them the way
    the customer would answer (e.g. "Send the proposal", "More detail"),
    not as descriptions of the choice.

    Do NOT call this for open-ended questions (e.g. "tell me about your
    business") or when there's no natural small set of discrete answers.

    Args:
        options: 2-4 short reply labels matching the choices you just offered.
    """
    return "Quick reply options noted."
