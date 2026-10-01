"""
Turns the game's SmartFormat description strings into the {{token}} grammar the
site and the card baker render.

    {Var} {Var:diff()} {Var:inverseDiff()}   -> {{Var}}
    {Var:energyIcons(1)}                     -> {{Var:energy}}
    {Var:starIcons()} {singleStarIcon}       -> {{Var:stars}}
    {Var:plural:one|many}                    -> {{Var:plural:one|many}}
    {Var:show:yes|no}                        -> {{Var:show:yes|no}}

plural/show MUST survive to render time rather than being resolved here: which
branch applies depends on the variable's value, and a card's base and upgraded
forms share one desc string with different vars ({Combats:plural:combat|combats}
is "combat" at 1 and "combats" at 5).

A branch can hold tokens of its own -- "{VoidFormPower:plural:card|{VoidFormPower:
diff()} cards}", or "{Combats:plural:combat|{} combats}" where the empty {} means
the enclosing variable -- so the output nests the same way and the renderers
(substituteDescVars in js/run-detail.js, expand_desc in bake_finished_cards.py)
recurse into the branch they pick.

Anything else in braces (choose(), cond:, ...) is dropped.
"""
import re

_NAME = re.compile(r"[A-Za-z_]+\Z")


def _closing_brace(text: str, start: int) -> int:
    """Index of the } matching the { at `start`, or -1."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_branches(arg: str) -> tuple[str, str]:
    """Splits "one|many" at the first | that isn't inside a nested {...}."""
    depth = 0
    for i, ch in enumerate(arg):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == "|" and depth == 0:
            return arg[:i], arg[i + 1:]
    return arg, ""


def _convert_token(payload: str, outer: str | None) -> str:
    name, has_format, fmt = payload.partition(":")
    if not name:
        name = outer or ""  # {} / {:diff()}: the enclosing plural's variable
    if not _NAME.match(name):
        return ""
    if not has_format:
        return "{{singleStarIcon:stars}}" if name == "singleStarIcon" else f"{{{{{name}}}}}"
    if fmt in ("diff()", "inverseDiff()"):
        return f"{{{{{name}}}}}"
    if re.fullmatch(r"energyIcons\(\d*\)", fmt):
        return f"{{{{{name}:energy}}}}"
    if fmt == "starIcons()":
        return f"{{{{{name}:stars}}}}"
    kind, has_arg, arg = fmt.partition(":")
    if kind in ("plural", "show") and has_arg:
        first, second = _split_branches(arg)
        return f"{{{{{name}:{kind}:{convert_tokens(first, name)}|{convert_tokens(second, name)}}}}}"
    return ""


def convert_tokens(text: str, outer: str | None = None) -> str:
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "{":
            end = _closing_brace(text, i)
            if end >= 0:
                out.append(_convert_token(text[i + 1:end], outer))
                i = end + 1
                continue
        elif ch != "}":
            out.append(ch)
        i += 1
    return "".join(out)


def extract_incombat(text: str) -> str:
    """Replace {InCombat:\n(content)|} with just the content (always show it in our UI)."""
    # Match the whole outer block manually since content has nested braces
    out = []
    i = 0
    while i < len(text):
        if text[i:].startswith("{InCombat:"):
            j = _closing_brace(text, i)
            if j < 0:
                j = len(text)
            block = text[i + 1:j]  # contents between outer { }
            # block looks like: InCombat:\n(Hits {Var:diff()} text|)
            # strip "InCombat:" prefix and extract content before the trailing "|"
            inner = block[len("InCombat:"):]
            # drop trailing "|" (the else-branch is always empty)
            if inner.endswith("|"):
                inner = inner[:-1]
            # strip wrapping \n( ... ) if present
            inner = inner.strip()
            if inner.startswith("(") and inner.endswith(")"):
                inner = inner[1:-1]
            out.append("\n(" + inner + ")")
            i = j + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def clean_desc(text: str) -> str:
    """Raw localization string -> {{token}} text with every BBCode tag stripped.
    A caller that wants to keep a tag's meaning (the baker and [gold]) swaps it
    for something that isn't [tag]-shaped before calling."""
    if not text:
        return ""
    text = convert_tokens(extract_incombat(text))
    # Strip [gold]...[/gold] BBCode tags — keep inner text
    text = re.sub(r"\[/?[a-zA-Z_]+\]", "", text)
    # Collapse whitespace artifacts
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
