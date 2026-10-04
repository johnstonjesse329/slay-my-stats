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
    if fmt in ("diff()", "inverseDiff()", "percentMore()", "percentLess()"):
        return f"{{{{{name}}}}}"
    if fmt.startswith("cond:"):
        # {Var:cond:>1?one|many}  /  {Var:cond:one|many}
        # The comparison is optional; without one the variable's own truthiness
        # decides. The branch survives to render time because the choice depends
        # on the variable's value, exactly like plural/show.
        body = fmt[len("cond:"):]
        test, has_test, branches = body.partition("?")
        if not has_test:
            branches, test = test, ""
        first, second = _split_branches(branches)
        prefix = f"{test}?" if test else ""
        return (f"{{{{{name}:cond:{prefix}"
                f"{convert_tokens(first, name)}|{convert_tokens(second, name)}}}}}")
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


def _top_blocks(text: str):
    """The payload of each top-level {...}, in order."""
    out, i = [], 0
    while i < len(text):
        if text[i] == "{":
            end = _closing_brace(text, i)
            if end < 0:
                break
            out.append(text[i + 1:end])
            i = end + 1
        else:
            i += 1
    return out


def _split_top(arg: str):
    """Split on | at brace depth 0."""
    parts, depth, last = [], 0, 0
    for i, ch in enumerate(arg):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == "|" and depth == 0:
            parts.append(arg[last:i])
            last = i + 1
    parts.append(arg[last:])
    return parts


def unwrap_choices(text: str):
    """Recover the branches of a description built only from dropped constructs.

    Some cards carry no flat description at all: Mad Science's string is one
    choose() over the rolled card type plus a HasRider block naming eight riders,
    so convert_tokens() correctly returns "" for the whole thing. This walks that
    structure instead and hands back each branch's own text, still in {{token}}
    form so the renderers substitute the real numbers.

    Returns (choose_branches, named_branches); each is a list of (name, text) with
    empty branches dropped. Named blocks whose body is itself a construct (the
    trailing "???" placeholders) are skipped rather than returned as riders.
    """
    chooses, named = [], []
    if not text:
        return chooses, named
    for block in _top_blocks(text):
        head, sep, rest = block.partition(":")
        if not sep:
            continue
        # Test the prefix, not a substring: the template's trailing CardType
        # choose() block is nested *inside* the HasRider block, so searching the
        # whole payload for "choose(" would misread the rider list as a choose.
        if rest.lstrip().startswith("choose("):
            rest = rest.lstrip()
            options = rest.split("choose(", 1)[1].split(")", 1)[0].split("|")
            branches = rest.split("):", 1)[1] if "):" in rest else ""
            for option, branch in zip(options, _split_top(branches)):
                body = clean_desc(branch).strip()
                if body:
                    chooses.append((option, body))
        elif head.isalpha():
            for inner in _top_blocks(rest):
                name, sep2, body_raw = inner.partition(":")
                if not sep2 or not name.isalpha() or "choose(" in body_raw or "???" in body_raw:
                    continue
                body = clean_desc(_split_top(body_raw)[0]).strip()
                if body:
                    named.append((name, body))
    return chooses, named

