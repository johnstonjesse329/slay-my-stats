"""
Reads the decompiled game code (pck_recover_full/src/Core/Models) for what
the power curve needs and writes power_data.json:

  cards      — who it targets, what playing it does (attack/block/draw/energy,
               hit count, powers applied and on whom, orbs, Shivs, playing
               the top of the draw pile...), a calculated card's bonus per
               stack of a power (Bully: per Vulnerable), how it draws (a
               full hand, Pillage's run of Attacks, only if a condition
               holds, keeping or discarding what it drew), what it exhausts
               and what it gains per card exhausted (Fiend Fire, Second
               Wind), how it changes cards mid-fight (Rampage and Thrash
               grow, Claw grows every copy, Molten Fist doubles Vulnerable,
               Armaments upgrades, Primal Force transforms, Stoke generates,
               Howl from Beyond plays from the exhaust pile), what it does
               with orbs (channel, evoke, passive, slots), and the synergy
               keys it produces and consumes
  relics     — the synergy keys it produces and consumes, its damage mods,
               and its draw and energy: extra or fewer cards in the hand
               draw, on which turns (every N, from turn N, elite fights
               only), draws and energy on a trigger (exhaust, kill, playing
               a card type...), start-of-turn choices (Gambling Chip), and
               orb hooks (Cracked Core's Lightning, Runic Capacitor's slots)
  powers     — damage/block/HP-loss mods (flat or percent, on the owner's
               attacks or on hits it takes), the same draw and energy
               fields per stack (Vicious, Dark Embrace, Demesne...), orb
               hooks (Loop, Coolant, Storm...), and synergy keys
  monsters   — HP and every move's intents, attacks with per-hit damage and
               hit count, base and at the ascension that raises them
  encounters — the monsters each encounter can spawn

The numbers on cards and relics stay in card_data.json / relic_data.json;
this adds the structure those files can't show. A synergy key links an
enabler to a payoff: Dominate produces "power:Vulnerable" and Bully consumes
it; Blade Dance produces "shiv" and Accuracy consumes it; a discard card
produces "discard" and Sly cards and Tingsha consume it. Regex over
decompiled C#, so a first pass: read the output, don't trust it blindly.

Run after a game update, once the PCK extraction is refreshed.
"""
import json
import re
from pathlib import Path

from pck_root import find_pck_root

ROOT = Path(__file__).resolve().parent.parent
MODELS = find_pck_root() / "src" / "Core" / "Models"
OUT = ROOT / "power_data.json"


def game_id(class_name: str) -> str:
    """BladeDance -> BLADE_DANCE, TwigSlimeS -> TWIG_SLIME_S, the way the game
    turns a model's class name into its id."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", class_name)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)
    return s.upper()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def method_bodies(src: str, name: str) -> str:
    """The text of every override of `name` in a class (brace-matched), so a
    damage hook's direction checks are read from that hook only."""
    return "\n".join(braced(src, m.end())
                     for m in re.finditer(rf"override (?:async )?[\w<>?]+ {name}\(", src))


def braced(src: str, pos: int) -> str:
    """The brace-matched block that opens after `pos`."""
    start = src.find("{", pos)
    depth, i = 0, start
    while i < len(src):
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        if depth == 0:
            break
        i += 1
    return src[start:i]


def call_args(src: str, pos: int) -> list[str]:
    """The top-level arguments of the call that opens at or after `pos`."""
    i = src.find("(", pos) + 1
    depth, args, cur = 1, [], []
    while i < len(src) and depth:
        ch = src[i]
        depth += (ch in "([{") - (ch in ")]}")
        if depth == 0 or (ch == "," and depth == 1):
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    return args


def amount(arg: str):
    """What a Draw/GainBlock/GainEnergy/Apply argument gives: "Amount" (a
    power's own stack), a var name, a literal, or None for a formula."""
    arg = re.sub(r"^\((?:decimal|int)\)", "", arg.strip())
    if arg == "base.Amount":
        return "Amount"
    m = re.fullmatch(r"base\.DynamicVars(?:\.(\w+)|\[\"(\w+)\"\])(?:\.\w+)?", arg)
    if m:
        return m.group(1) or m.group(2)
    m = re.fullmatch(r"(\d+)m?", arg)
    return int(m.group(1)) if m else None


def draw_count(src: str, pos: int):
    """How many cards the Draw call at `pos` draws (see amount). A local
    count is looked up (Prepared's cardCount); topping up to a full hand is
    "fullHand" (Scrawl); a one-card Draw in a loop counts the loop's var
    (Restlessness, Centennial Puzzle)."""
    args = call_args(src, pos)
    if len(args) < 3:
        loop = re.search(r"for \(int i = 0; (?:\(decimal\))?i < base\.DynamicVars(?:\.(\w+)|\[\"(\w+)\"\])", src)
        return (loop.group(1) or loop.group(2)) if loop else 1
    arg = args[1]
    local = re.fullmatch(r"[a-z]\w*", arg) and re.search(rf"int {arg} = (.+?);", src)
    if local:
        return "fullHand" if "MaxCardsInHand" in local.group(1) else amount(local.group(1))
    return amount(arg)


# ---------------------------------------------------------------------------
# Synergy keys shared by cards, relics and powers

def consumed_keys(src: str) -> set[str]:
    keys = {f"power:{p}" for p in re.findall(r"(?:GetPower|GetPowerAmount|HasPower)<(\w+)Power>", src)}
    played = method_bodies(src, "AfterCardPlayed") + method_bodies(src, "BeforeCardPlayed")
    for card_type, key in (("Attack", "attacks"), ("Skill", "skills"), ("Power", "powers")):
        if f"CardType.{card_type}" in played:
            keys.add(key)
    for pattern, key in (
        (r"AfterCardDiscarded|CardKeyword\.Sly", "discard"),
        (r"AfterCardExhausted", "exhaust"),
        (r"CardTag\.Shiv", "shiv"),
        (r"CardTag\.Strike", "strike"),
        (r"CardTag\.OstyAttack", "osty"),
        (r"ShouldClearBlock|AfterBlockCleared", "block"),
        (r"AfterCardDrawn", "draw"),
        (r"AfterStarsSpent", "stars"),
        (r"AfterCardGeneratedForCombat", "generated"),
        (r"AfterShuffle", "shuffle"),
    ):
        if re.search(pattern, src):
            keys.add(key)
    return keys


def produced_keys(src: str) -> set[str]:
    keys = set()
    for pattern, key in (
        (r"CardCmd\.Discard|FromHandForDiscard", "discard"),
        (r"CardCmd\.Exhaust\b|CardKeyword\.Exhaust", "exhaust"),
        (r"Shiv\.CreateInHand", "shiv"),
        (r"\w*Cmd\.GainBlock\(", "block"),
        (r"\w*Cmd\.Draw\(", "draw"),
        (r"\w*Cmd\.GainStars\(", "stars"),
        (r"\w*Cmd\.Summon\(", "osty"),
        (r"AddGeneratedCards?ToCombat|CreateInHand", "generated"),
    ):
        if re.search(pattern, src):
            keys.add(key)
    return keys


def applied_powers(src: str) -> dict[str, str]:
    """Power -> "self" or "enemy", from each PowerCmd.Apply<X>(ctx, target, ...)."""
    out = {}
    # Your creature under a local's name (Prolong's `creature`).
    mine = set(re.findall(r"Creature (\w+) = base\.Owner\.Creature;", src))
    # The first argument is the choice context: a name, or `new X()`.
    for name, target in re.findall(r"PowerCmd\.Apply<(\w+)Power>\(\s*(?:new \w+\(\)|\w+),\s*([^,]+),", src):
        # A power's own Owner is its creature (Demon Form -> Strength).
        side = "self" if re.search(r"Owner\.Creature|player\.Creature|^base\.Owner$", target.strip()) \
            or target.strip() in mine else "enemy"
        out[name] = "both" if out.get(name, side) != side else side
    return out


COMBAT_HOOKS = ("AfterRoomEntered", "BeforeCombatStart")
TURN_HOOKS = {"start": ("BeforeSideTurnStart", "AfterSideTurnStart", "AfterBlockCleared", "AfterEnergyReset",
                        "AfterEnergyResetLate", "AfterPlayerTurnStart", "AfterPlayerTurnStartLate"),
              "end": ("BeforeSideTurnEnd", "BeforeSideTurnEndEarly", "AfterSideTurnEnd")}


def turn_gate(body: str) -> dict:
    """Which turns a hook fires on, from its TurnNumber check: {"on": 2},
    {"from": 2}, {"until": 2} (inclusive), or {} for every turn. A check
    that bails out (`if (TurnNumber < 3) return`) fires on the other turns.
    The bound can be a var (Ring of the Drake: until its Turns var)."""
    m = re.search(r"TurnNumber (==|!=|<=|>=|<|>) (\d+|base\.DynamicVars\[\"(\w+)\"\]\.\w+)\)\s*\{?\s*(return)?", body)
    if not m:
        return {}
    op, bail = m.group(1), bool(m.group(4))
    if bail:
        op = {"<": ">=", "<=": ">", ">": "<=", ">=": "<", "==": "!=", "!=": "=="}[op]
    if m.group(3):  # a var: only the bounds that need no arithmetic
        return {"<=": {"until": m.group(3)}, ">=": {"from": m.group(3)}}.get(op, {})
    n = int(m.group(2))
    return {"==": {"on": n}, "<=": {"until": n}, "<": {"until": n - 1},
            ">=": {"from": n}, ">": {"from": n + 1}, "!=": {"from": 2} if n == 1 else {}}.get(op, {})


def stack_amount(body: str, effect: dict) -> bool:
    """Whether a power's effect gives its own stack (base.Amount): Demon
    Form's Strength, Plating's block. Reverts (-base.Amount) and counts
    (Tender's cards played) aren't, and the sim leaves those out."""
    if "power" in effect:
        m = re.search(rf"PowerCmd\.Apply<{effect['power']}Power>\((?:new \w+\(\)|\w+),\s*[^,]+,\s*([^,]+),", body)
        return bool(m) and m.group(1).strip() == "base.Amount"
    call = {"block": r"CreatureCmd\.GainBlock\(base\.Owner, base\.Amount\b", "energy": r"PlayerCmd\.GainEnergy\(base\.Amount\b",
            "draw": r"CardPileCmd\.Draw\([^;]*base\.Amount\b", "damage": r"CreatureCmd\.Damage\([^;]*base\.Amount\b",
            "stars": r"PlayerCmd\.GainStars\(base\.Amount\b", "forge": r"ForgeCmd\.Forge\(base\.Amount\b"}
    return any(k in effect and re.search(pat, body) for k, pat in call.items())


def turn_effects(src: str, power: bool = False) -> list[dict]:
    """What a relic does at the start (`at: start`) or end of a turn: powers
    it applies, damage it deals (`aoe` when it hits every enemy), block it
    gives, energy or draws, with the turns it fires on (see turn_gate).
    Combat start counts as turn 1 (Anchor, Vajra), as does a turn hook gated
    on it (Bag of Marbles); Horn Cleat is turn 2, Captain's Wheel turn 3.
    End-of-turn block can hang on a condition: `if: noBlock` (Orichalcum),
    `if: noAttack` (Ripple Basin), `per: cardInHand` (Cloak Clasp).
    Powers read the same way (Demon Form: Strength at start, Plating: block
    at end), skipping hooks only enemies run (Plating's opening block). A
    power's effects also note `stack` when they give the power's own amount
    (see stack_amount) and `once` when the power then removes itself
    (Block Next Turn). `summon` raises Osty by a var (Bound Phylactery:
    at combat start and each later turn). `stars` gains the Regent's stars
    (Divine Right at combat start, Lunar Pastry each turn's end, Genesis),
    `forge` forges the Sovereign Blade (Fencing Manual, Furnace)."""
    out = []
    hooks = [("start", h) for h in COMBAT_HOOKS] + [(at, h) for at, hs in TURN_HOOKS.items() for h in hs]
    for at, hook in hooks:
        body = method_bodies(src, hook)
        if not body or (hook == "AfterRoomEntered" and "CombatRoom" not in body) \
                or re.search(r"if \(base\.Owner\.IsPlayer\)\s*\{?\s*return", body):
            continue
        first = len(out)
        base = {"at": at, **({"on": 1} if hook in COMBAT_HOOKS else turn_gate(body))}
        if "RoomType.Elite" in body:
            base["elite"] = True  # Booming Conch: elite fights only
        for power, side in applied_powers(body).items():
            if re.search(rf"PowerCmd\.Apply<{power}Power>\([^;]*-base\.DynamicVars\[\"\w+Applied\"\]", body):
                continue  # Monologue taking back the turn's Strength (its strPerPlay rule)
            out.append({**base, "power": power, "side": side})
        # Crimson Mantle's damage is to its owner, not an enemy; Parrying
        # Shield picks one enemy out of HittableEnemies.
        if "CreatureCmd.Damage(" in body and not re.search(r"CreatureCmd\.Damage\(\w+, base\.Owner,", body):
            aoe = "HittableEnemies" in body and "NextItem(" not in body
            out.append({**base, "damage": "aoe" if aoe else "single"})
        for call, key in (("CreatureCmd.GainBlock", "block"), ("PlayerCmd.GainEnergy", "energy"),
                          ("CardPileCmd.Draw", "draw"), ("PlayerCmd.GainStars", "stars"), ("ForgeCmd.Forge", "forge")):
            # Dark Embrace's end-of-turn draw is its exhaust trigger, held
            # back for cards Ethereal exhausted (see triggers).
            if call in body and not (key == "draw" and "etherealCount" in body):
                entry = {**base, key: True}
                if key == "block" and at == "end":
                    if "Creature.Block > 0" in src:
                        entry["if"] = "noBlock"
                    elif "CardType.Attack" in body:
                        entry["if"] = "noAttack"
                    elif "PileType.Hand" in body:
                        entry["per"] = "cardInHand"
                out.append(entry)
        # Bound Phylactery summons through a helper it awaits.
        summon = body + "".join(braced(src, m.end()) for name in re.findall(r"await (\w+)\(\);", body)
                                for m in [re.search(rf"private async Task {name}\(\)", src)] if m)
        m = re.search(r"OstyCmd\.Summon\(", summon)
        if m:
            out.append({**base, "summon": amount(call_args(summon, m.start())[2]) or 1})
        if power:
            for entry in out[first:]:
                if stack_amount(body, entry):
                    entry["stack"] = True
                elif "power" in entry and re.search(
                        rf"PowerCmd\.Apply<{entry['power']}Power>\([^,]+, base\.Owner, -base\.Amount,", body):
                    entry["stack"], entry["sign"] = True, -1  # Wraith Form: its stack of Dexterity lost
                if "PowerCmd.Remove(this)" in body:
                    entry["once"] = True
    return out


def damage_mods(src: str) -> list[dict]:
    """What a power or relic changes: damage/block, flat ("add") or percent
    ("mul"), and whose — "out" when it checks the owner is the dealer (the
    owner's own attacks: Strength, Weak), "in" when it checks the owner is the
    target (hits the owner takes: Vulnerable, Tungsten Rod)."""
    mods = []
    for hook, stat, op in (
        ("ModifyDamageAdditive", "damage", "add"),
        ("ModifyDamageMultiplicative", "damage", "mul"),
        ("ModifyBlockAdditive", "block", "add"),
        ("ModifyBlockMultiplicative", "block", "mul"),
        ("ModifyHpLostAfterOsty", "hpLost", "add"),
        ("ModifyHpLostBeforeOsty", "hpLost", "add"),
    ):
        body = method_bodies(src, hook)
        if not body:
            continue
        side = None
        if re.search(r"dealer != base\.Owner|base\.Owner != dealer|dealer != base\.Owner\.Creature", body):
            side = "out"
        elif re.search(r"target != base\.Owner|base\.Owner != target|target != base\.Owner\.Creature", body):
            side = "in"
        mods.append({"stat": stat, "op": op, "side": side})
    # Thorns-style: hits back each time the owner is hit, so worth more
    # against many small hits than one big one.
    hit = method_bodies(src, "BeforeDamageReceived") + method_bodies(src, "AfterDamageReceived")
    if re.search(r"CreatureCmd\.Damage\([^;]*dealer", hit):
        mods.append({"stat": "retaliate", "op": "add", "side": "in"})
    return mods


# hook, event, the check in its body that picks the event out
TRIGGERS = (
    ("AfterPowerAmountChanged", "vulnerable", r"is VulnerablePower"),
    ("AfterCardExhausted", "exhaust", ""),
    ("AfterCardDrawn", "drawStatus", r"Type == CardType\.Status"),
    ("AfterCardDrawn", "drawEthereal", r"CardKeyword\.Ethereal"),
    ("AfterCardDrawn", "drawExtra", r"!fromHandDraw"),
    ("AfterCardDrawn", "draw", r"^(?![\s\S]*(?:fromHandDraw|CardType\.Status|CardKeyword\.Ethereal))"),
    ("AfterDamageGiven", "attackHit", r"IsPoweredAttack\(\) && result\.UnblockedDamage > 0"),
    ("AfterCardPlayed", "play", ""),
    ("AfterDeath", "kill", r"\.Side != base\.Owner"),
    ("AfterDamageReceived", "hpLoss", r"UnblockedDamage > 0"),
    ("AfterHandEmptied", "handEmpty", ""),
    ("AfterBlockGained", "blockGained", r"creature == base\.Owner"),
    ("AfterCardGeneratedForCombat", "statusMade", r"Type == CardType\.Status"),
    ("AfterPowerAmountChanged", "doomApplied", r"power is DoomPower"),
    ("AfterPowerAmountChanged", "debuffApplied", r"PowerType\.Debuff && power\.Owner\.IsEnemy"),
    ("BeforeCardPlayed", "play", r"GainBlock\(|GainStars\("),
    ("AfterStarsGained", "starsGained", ""),
    ("AfterStarsSpent", "starsSpent", ""),
    ("AfterCardGeneratedForCombat", "generated", r"^(?![\s\S]*CardType\.Status)[\s\S]*creator(?:\.Creature)? == base\.Owner"),
)


def triggers(src: str, power: bool = False) -> list[dict]:
    """Draw, block or energy on an event other than a turn's start or end:
    Vicious draws when you apply Vulnerable, Dark Embrace when a card is
    exhausted, Feel No Pain blocks then, Gremlin Horn draws and gains energy
    on a kill, Unceasing Top draws on an empty hand. Each amount is "Amount"
    (the power's stack), a var name or a literal. `type` filters played cards
    (Game Piece: Powers); `every` is a counter's var (Iron Club: every Cards
    plays; Joss Paper: every ExhaustAmount exhausts); `perTurn` / `perCombat`
    cap it (Iteration; Centennial Puzzle). On "play" a relic's draws are
    all that's read: the per-attack counters (Kunai, Ornamental Fan) are
    read from "attacks"; a power's block and damage count too (Rage: block
    per Attack; Serpent Form: a hit per card). `damage` is a hit on a random
    enemy (Juggernaut: on gaining block), `poison` Poison on one (`aoe`:
    every enemy, Corrosive Wave on any draw; `onTarget`: the one just hit,
    Envenom on an attack's unblocked hit). Speedster hits on draws outside
    the hand draw ("drawExtra"); Smokestack hits every enemy when you make
    a status ("statusMade"). A countdown's `every` can be a literal
    (Automation: every 10 draws; Cacophony: 33; Panache: every 5 plays;
    `turnReset` when the count starts over each turn, as Panache's does);
    `cardIs` names the only card that sets it off (Haunt: Soul; Devour
    Life summons on it) and `starsSpent` asks that the card spent stars
    (Black Hole); `keyword` / `minCost` (a var) filter played cards before
    they resolve (Spirit of Ash: Ethereal; Danse Macabre: Energy or more).
    Shroud blocks when you apply Doom ("doomApplied"), Sleight of Flesh hits
    the enemy you debuff ("debuffApplied", onTarget); `summon` raises Osty.
    The Regent's: Black Hole hits every enemy on gaining stars
    ("starsGained"); Child of the Stars blocks its stack per star spent
    ("starsSpent", `perStar`), Mini Regent gains `strength` on the first
    spend each turn, Galactic Dust blocks every Stars stars; Arsenal gains
    Strength and Pillar of Creation / Regalite block when you make a card
    ("generated"); The Sealed Throne gains `stars` before each card. `snapshot`
    reads the amount as a card starts, so the card that applies the power
    doesn't set it off (Serpent Form, Afterimage)."""
    out = []
    for hook, event, check in TRIGGERS:
        body = method_bodies(src, hook)
        if not body or (check and not re.search(check, body)):
            continue
        # A private helper it awaits (Joss Paper's DrawIfThresholdMet).
        for name in re.findall(r"await (\w+)\(", body):
            m = re.search(rf"private (?:async )?[\w<>?]+ {name}\(", src)
            if m:
                body += braced(src, m.end())
        entry = {"on": event}
        m = re.search(r"cardPlay\.Card\.Type == CardType\.(\w+)", body) \
            or re.search(r"cardPlay\.Card\.Type != CardType\.(\w+)", method_bodies(src, "BeforeCardPlayed"))
        if m:
            entry["type"] = m.group(1)
        for call, key, arg in (("CardPileCmd.Draw(", "draw", None), ("GainBlock(", "block", 1),
                               ("PlayerCmd.GainEnergy(", "energy", 0), ("CreatureCmd.Damage(", "damage", 2),
                               ("PowerCmd.Apply<PoisonPower>(", "poison", 2), ("OstyCmd.Summon(", "summon", 2),
                               ("PlayerCmd.GainStars(", "stars", 0), ("PowerCmd.Apply<StrengthPower>(", "strength", 2)):
            i = body.find(call)
            if i < 0 or (event == "play" and key != "draw" and not (power and key in ("block", "damage", "energy", "summon", "stars"))) \
                    or (key == "strength" and event not in ("starsSpent", "generated")):
                continue
            args = call_args(body, i)
            if key == "block" and re.match(r"base\.Amount \* amount$", args[1].strip()):
                entry["perStar"] = True  # Child of the Stars: its stack per star spent
            if key in ("damage", "poison"):
                if re.search(r"(?:base|Card)\.Owner(\.Creature)?$", args[1].strip()):
                    continue  # it hurts its owner (Crimson Mantle; Galvanic, the card's player)
                if "HittableEnemies" in args[1] and "NextItem(" not in body:
                    entry["aoe"] = True
                if args[1].strip() in ("target", "power.Owner") and "NextItem(" not in body:
                    entry["onTarget"] = True
                # Charon's Ashes reads its Damage var into a local first.
                local = re.match(r"(\w+)\.BaseValue$", args[2].strip())
                if local and re.search(rf"DamageVar {local.group(1)} = base\.DynamicVars\.Damage;", body):
                    args[2] = "base.DynamicVars.Damage"
            n = draw_count(body, i) if key == "draw" else amount(args[arg])
            if re.search(r"amountsForPlayedCards\.Add\(cardPlay\.Card, base\.Amount\)", src) \
                    and (n is None or re.search(r"for \(int i = 0; i < \w+; i\+\+\)", body)):
                n = "Amount"  # Serpent Form, Subroutine: its stack as the card was played
            entry[key] = 1 if n is None else n
        if len(entry) == 1 + ("type" in entry) + ("perStar" in entry):
            continue
        if "HappenedThisTurn" in body or (event in ("starsSpent", "generated") and "UsedThisTurn" in body):
            entry["perTurn"] = 1  # Mini Regent, Regalite: the first each turn
        if "StarsSpent +=" in body:  # Galactic Dust: Block every Stars stars spent
            entry["every"] = "Stars"
            if "block" in entry and re.search(r"DynamicVars\.Block\.IntValue", body):
                entry["block"] = "Block"
        if "UsedThisCombat" in body:
            entry["perCombat"] = 1
        every = re.search(r"int intValue = base\.DynamicVars\.(\w+)\.IntValue;[^}]*% intValue == 0", body) \
            or re.search(r"< base\.DynamicVars\[\"(\w+)\"\]", body)
        if every:
            entry["every"] = every.group(1)
        # A countdown: Cacophony's Cards var, Panache's CardsLeft, Automation's
        # private cardsLeft reset to a constant.
        every = re.search(r"DynamicVars(?:\.(\w+)|\[\"(\w+)\"\])\.BaseValue--", body)
        if every:
            name = every.group(1) or every.group(2)
            lead = "" if every.group(1) else rf'"{name}", '
            m = re.search(rf"new \w*Var\({lead}(\d+)m?\)", src)
            entry["every"] = int(m.group(1)) if m else name
        m = re.search(r"cardsLeft = (\d+);", body)
        if m and "cardsLeft--" in body:
            entry["every"] = int(m.group(1))
        if every or m:  # Panache: the count starts over each turn
            ends = method_bodies(src, "AfterSideTurnEnd") + method_bodies(src, "BeforeSideTurnStart")
            if re.search(r"(?:BaseValue|cardsLeft) = \d+m?;", ends):
                entry["turnReset"] = True
        m = re.search(r"cardPlay\.Card is (\w+)", body)
        if m:  # Haunt: only a Soul
            entry["cardIs"] = re.sub(r"(?<!^)([A-Z])", r"_\1", m.group(1)).upper()
        if event == "play" and "StarsSpent" in body:  # Black Hole: a card that spent stars
            entry["starsSpent"] = True
        m = re.search(r"cardPlay\.Card\.Keywords\.Contains\(CardKeyword\.(\w+)\)", body)
        if m:  # Spirit of Ash: Ethereal cards
            entry["keyword"] = m.group(1)
        m = re.search(r"EnergyCost\.GetResolved\(\) >= base\.DynamicVars\.(\w+)", body)
        if m:  # Danse Macabre: cards that cost its Energy var or more
            entry["minCost"] = m.group(1)
        if event == "play" and "amountsForPlayedCards.Add" in method_bodies(src, "BeforeCardPlayed"):
            entry["snapshot"] = True  # Serpent Form: not the card that applied it, at the amount before
        out.append(entry)
    return out


def hand_draw(src: str) -> dict | None:
    """A ModifyHandDraw override: the turns it applies on (turn_gate), and
    `less` when it takes cards away (Big Mushroom, Mind Rot), `elite` for
    elite fights only (Booming Conch), `ifPlayedAtMost` the var capping last
    turn's plays (Pocketwatch), `every` the var of a turn counter (Pendulum:
    every Turns turns), `flat` when a power gives a fixed number whatever
    its stack (Clarity: its stack is how long it lasts)."""
    body = method_bodies(src, "ModifyHandDraw")
    if not body:
        return None
    hd = turn_gate(body)
    if re.search(r"(?:count|cardsToDraw) - ", body):
        hd["less"] = True
    if "RoomType.Elite" in body:
        hd["elite"] = True
    m = re.search(r"_cardsPlayedLastTurn > base\.DynamicVars\[\"(\w+)\"\]", body)
    if m:
        hd["ifPlayedAtMost"] = m.group(1)
    if "TurnsSeen" in body:
        hd["every"] = "Turns"
    m = re.search(r"count \+ (\d+)m", body)
    if m:
        hd["flat"] = int(m.group(1))
    return hd


def turn_start_choice(src: str) -> str | None:
    """A card you give up at the start of each turn, after the draw: Tools
    of the Trade discards ("discard"), Tyranny and Toasty Mittens exhaust,
    Gambling Chip swaps out what you like on turn 1 ("mulligan")."""
    body = method_bodies(src, "AfterPlayerTurnStart")
    if "DiscardAndDraw" in body:
        return "mulligan"
    if "FromHandForDiscard" in body:
        return "discard"
    if "CardSelectCmd.FromHand(" in body and "CardCmd.Exhaust" in body:
        return "exhaust"
    return None


def blocks_draws(src: str) -> bool:
    """Draws outside the turn's hand draw do nothing: Fiddle, No Draw."""
    return "fromHandDraw" in method_bodies(src, "ShouldDraw")


# ---------------------------------------------------------------------------
# Cards

CTOR = re.compile(r"base\((-?\d+|[\w.]+), CardType\.(\w+), CardRarity\.(\w+), TargetType\.(\w+)\)")


def scan_card(src: str) -> dict:
    card = {}
    m = CTOR.search(src)
    if m:
        card["target"] = m.group(4)
    play = method_bodies(src, "OnPlay")
    exhausted = re.search(r"int (\w+) = [^;]*;\s*foreach \(CardModel item in list\)\s*\{\s*await CardCmd\.Exhaust", play)
    attacks = re.findall(r"DamageCmd\.Attack\(.*?(?:;|\n\s*\n)", src, re.S)
    if attacks:
        hit = re.search(r"WithHitCount\(([^)]+)\)", src)
        if hit:
            n = hit.group(1).strip()
            var = re.search(r"DynamicVars(?:\.|\[\")(\w+)", n)
            # Fiend Fire and Flak Cannon hit once per card they exhausted.
            card["hits"] = int(n) if n.isdigit() else (var.group(1) if var else
                                                       "exhausted" if exhausted and n == exhausted.group(1) else "varies")
        if "TargetingAllOpponents" in src:
            card["aoe"] = True
        elif "TargetingRandomOpponents" in src:
            card["random"] = True
    # Echoing Slash hits every enemy with a bare Damage call, not an attack command.
    if re.search(r"CreatureCmd\.Damage\([^,]+, base\.CombatState\?*\.HittableEnemies", src):
        card["aoe"] = True
    # Omnislice: what the hit dealt also lands on every other enemy.
    if "GetTeammatesOf" in src and "CreatureCmd.Damage(" in src:
        card["splash"] = True
    # Calculated damage/block that adds a bit per stack of a power, on the
    # target (Bully: per Vulnerable) or the player (Expect a Fight: per
    # Strength). Other formulas (cards drawn, exhaust pile...) are left out.
    calc = re.search(r"Calculated(?:Damage|Block)Var\([^)]*\)\.WithMultiplier\([^;]*?"
                     r"(target\?|Owner\.Creature)\.GetPowerAmount<(\w+)Power>", src)
    if calc:
        card["perStack"] = {"power": calc.group(2), "on": "target" if calc.group(1) == "target?" else "self"}
    does = [verb for verb, pattern in (
        ("attack", r"DamageCmd\.Attack\("),
        ("damage", r"CreatureCmd\.Damage\("),
        ("block", r"\w*Cmd\.GainBlock\("),
        ("draw", r"\w*Cmd\.Draw\("),
        ("energy", r"\w*Cmd\.GainEnergy\("),
        ("discard", r"CardCmd\.Discard|FromHandForDiscard"),
        ("exhaustOther", r"CardCmd\.Exhaust\b"),
        ("stars", r"\w*Cmd\.GainStars\("),
        ("forge", r"\w*Cmd\.Forge\("),
        ("summon", r"\w*Cmd\.Summon\("),
        ("upgrade", r"CardCmd\.Upgrade\("),
    ) if re.search(pattern, src)]
    if re.search(r"CardPileCmd\.AutoPlayFromDrawPile\(", play):  # not I Am Invincible's, from a hook
        does.append("autoplay")
    if does:
        card["does"] = does
    m = re.search(r"int (\w+) = ResolveEnergyXValue\(\);\s*if \(\1 >= base\.DynamicVars\.(\w+)\.IntValue\)\s*\{\s*\1 \*= 2;", play)
    if m:
        card["xDoubleAt"] = m.group(2)  # Heavenly Drill: X doubled at 4 or more
    if "forceExhaust: true" in src:
        card["autoplayExhausts"] = True  # Havoc exhausts the card it plays
    card.update(card_draw(src, play))
    how = exhausts(src, play)
    if how:
        card["exhausts"] = how
        if "IsUpgraded" in play and "CardSelectCmd.FromHand(" in play and "NextItem(" in play:
            card["exhaustsUp"] = "pick"  # True Grit: random, upgraded you pick
        # Second Wind: block for each card it exhausts.
        if re.search(r"foreach \(CardModel item in .+?\)\s*\{\s*await CardCmd\.Exhaust[^}]*GainBlock", play):
            card["blockPer"] = "exhausted"
    powers = applied_powers(src)
    if powers:
        card["applies"] = powers
        # How much of each: a var name or a literal (Relax: its Energy and
        # Cards vars for Energy Next Turn and Draw Cards Next Turn).
        amounts, lowers = {}, {}
        local = {name: a or b for name, a, b in
                 re.findall(r"int (\w+) = base\.DynamicVars(?:\.(\w+)|\[\"(\w+)\"\])\.IntValue;", src)}
        for m in re.finditer(r"PowerCmd\.Apply<(\w+)Power>\(", src):
            args = call_args(src, m.start())
            if len(args) > 2 and args[2].strip().startswith("-"):
                # A loss (Friendship's and Shared Fate's Strength, Resonance's -1
                # on every enemy): {power: {side: amount}}, the side "enemies"
                # when it goes to each of them, not the target.
                arg, target = args[2].strip()[1:], args[1].strip()
                n = amount(arg) or local.get(arg) or "X"
                side = "self" if re.search(r"Owner\.Creature|player\.Creature", target) \
                    else "enemy" if target == "cardPlay.Target" else "enemies"
                lowers.setdefault(m.group(1), {})[side] = n
                continue
            n = amount(args[2]) if len(args) > 2 else None
            if n is None and len(args) > 2:
                n = local.get(args[2].strip())  # Putrefy's Power var
            if n is None and len(args) > 2 and re.fullmatch(r"\w+\.Block", args[2].strip()):
                n = "block"  # Prolong: your block when played
            if n is not None:
                amounts.setdefault(m.group(1), n)
        if amounts:
            card["amounts"] = amounts
        if lowers:
            card["lowers"] = lowers
    orbs = sorted(set(re.findall(r"Channel<(\w+)Orb>", src)))
    if orbs:
        card["orbs"] = orbs
    ops = orb_ops(play)
    if ops:
        card["orbOps"] = ops
    makes = sorted({game_id(c) for c in re.findall(r"(\w+)\.CreateInHand", src)}
                   | {game_id(c) for c in re.findall(r"CreateCard<(\w+)>", src)})
    if makes:
        card["makes"] = makes
    card.update(in_combat_changes(src, play))
    card.update(calculated(src))
    card.update(conditions(src, play))
    card.update(generators(src, play))
    card.update(card_loops(src, play))
    card.update(pile_moves(src, play))
    card.update(necro(src, play))
    card.update({k: v for k, v in regent(src, play).items()
                 if not (k == "turnsInto" and "transforms" in card)})  # Primal Force's own key
    # Infernal Blade's randomFree and Bundle of Joy's makesRandom are read already.
    card.update({k: v for k, v in colorless(src, play).items()
                 if not (k == "makesRandom" and ("randomFree" in card or "makesRandom" in card))})
    if "HasSeekingEdge" in play:  # Sovereign Blade: all enemies only under Seeking Edge
        card.pop("aoe", None)
    if card.get("blockFrom") and "block" in card.get("does", []):
        card["does"].remove("block")
    # Its HpLoss var is HP you lose (Bloodletting), not what a power it
    # applies deals (Haunt).
    if re.search(r"CreatureCmd\.Damage\(\w+, base\.Owner\.Creature, base\.DynamicVars\.HpLoss", src):
        card["losesHp"] = True
    tags = card_tags(src)
    if tags:
        card["tags"] = tags
    return card


def necro(src: str, play: str) -> dict:
    """Necrobinder card effects: `killsOsty` (Sacrifice, Bone Shards),
    `doomFromDamage` (Blight Strike: Doom of the damage it dealt),
    `doomKill` (End of Days kills what its Doom dooms at once),
    `freeAfterOsty` (Flatten costs 0 once Osty has attacked this turn),
    `costDownEthereal` the var it costs less by per Ethereal card played
    this fight (Banshee's Cry), and `puts` for the Souls it makes (Grave
    Warden, Reave: Cards of them into the draw pile; Severance: one each into
    the draw pile, discard pile and hand; Dirge: X of them)."""
    out = {}
    if "CreatureCmd.Kill(base.Owner.Osty)" in play:
        out["killsOsty"] = True
    if re.search(r"PowerCmd\.Apply<DoomPower>\([^;]*TotalDamage", play):
        out["doomFromDamage"] = True
    if "DoomPower.DoomKill(" in play:
        out["doomKill"] = True
    if "EnergyCost.SetThisTurn(0)" in src and "e.Actor == base.Owner.Osty" in src:
        out["freeAfterOsty"] = True
    m = re.search(r"WasEthereal[\s\S]*EnergyCost\.AddThisCombat\(-\w+ \* base\.DynamicVars\.(\w+)", src)
    if m:
        out["costDownEthereal"] = m.group(1)
    m = re.search(r"Soul\.Create\(base\.Owner, ([^,]+), base\.CombatState\)", play)
    if m:
        n = amount(m.group(1))
        n = n if n is not None else "X" if m.group(1).strip() == "xValue" else "varies"
        local = re.search(r"(\w+) = Soul\.Create\(", play)
        name = local.group(1) if local else None
        adds = [(a, pile) for a, pile in re.findall(r"AddGeneratedCards?ToCombat\(([^;]*?), PileType\.(\w+)", play)
                if "Soul.Create(" in a or (name and re.fullmatch(rf"{name}(\[\d+\])?", a.strip()))]
        out["puts"] = [{"id": "SOUL", "pile": pile, "n": 1 if "[" in a else n} for a, pile in adds]
    return out


def regent(src: str, play: str) -> dict:
    """Regent card effects: `multiplayerOnly` (dead in a solo run: Plot,
    Largesse), `turnsInto` {into, from: hand / draw, n: 1, a var or "any",
    up: upgraded when this card is} (Begone, Charge, Guards), `forge` its
    var (Sovereign Blade's damage; `bladeToHand` first for Summon Forth),
    `starsIfKill` (Knockout Blow), `resultPile` where it goes once played
    instead of the discard pile (Shining Strike: on top of the draw pile;
    Particle Wall: back to the hand), `putBack` a var of cards from the hand
    back on top of the draw pile after it draws (Glimmer, Photon Cut),
    `playsSkill` a Skill in hand autoplayed a var of times (Decisions,
    Decisions), `fromExhaustStart` (Bombardment plays itself from the
    exhaust pile each turn), `autoplaysTop` (I Am Invincible plays itself
    from the top of the draw pile at the turn's end), `endsTurn` (Void
    Form), `returnsOnSkills` {every: var} (Make It So back to the hand on
    every that-many-th Skill of a turn), `onDraw` {cost: -1} (Kingly Kick)
    or {dmg: var} (Kingly Punch), `makesRandom` {pool, n, choose, up} for
    random cards of a pool into the hand (Bundle of Joy, Manifest
    Authority, Quasar: 1 of 3), `clones` {of: Colorless, n: var} (Heirloom
    Hammer) and `blockFrom` a power whose stack is its block (Sovereign
    Blade: Parry)."""
    out = {}
    if "CardMultiplayerConstraint.MultiplayerOnly" in src:
        out["multiplayerOnly"] = True
    m = re.search(r"CreateCard<(\w+)>\(base\.Owner\);\s*if \(base\.IsUpgraded\)[\s\S]*?CardCmd\.Transform\(", play) \
        or re.search(r"CardCmd\.TransformTo<(\w+)>\(", play)
    if m:
        sel = re.search(r"FromHand\(prefs: new CardSelectorPrefs\([^,]+, (\d+)(?:, (\d+))?\)", play)
        frm = "draw" if "PileType.Draw.GetPile" in play else "hand"
        n = re.search(r"CardSelectorPrefs\([^,]+, base\.DynamicVars\.(\w+)\.IntValue\)", play)
        n = n.group(1) if n else "any" if sel and sel.group(2) else 1
        out["turnsInto"] = {"into": game_id(m.group(1)), "from": frm, "n": n, "up": "IsUpgraded" in play}
        t = re.search(r"Hand\.GetPile\(base\.Owner\)\.Cards\.Where\([^;]*c\.Type == CardType\.(\w+)\)", play)
        if t and "CardSelectCmd." not in play:  # Compact: every Status in hand
            out["turnsInto"].update(n="all", type=t.group(1))
    m = re.search(r"ForgeCmd\.Forge\(base\.DynamicVars\.(\w+)", play)
    if m:
        out["forge"] = m.group(1)
    if "AllCards.OfType<SovereignBlade>()" in play and "PileType.Hand)" in play:
        out["bladeToHand"] = True
    if "WasTargetKilled" in play and "GainStars(" in play:
        out["starsIfKill"] = True
    m = re.search(r"pileType == PileType\.Discard\)\s*\{\s*\w+\.pileType = PileType\.(\w+);", src)
    if m:
        out["resultPile"] = m.group(1)
    m = re.search(r"CardSelectorPrefs\([^,]+, base\.DynamicVars\[\"(\w+)\"\]\.IntValue\)[\s\S]*PileType\.Draw, CardPilePosition\.Top", play)
    if m and "CardPileCmd.Draw(" in play:
        out["putBack"] = m.group(1)
    m = re.search(r"c\.Type == CardType\.Skill[\s\S]*for \(int i = 0; i < base\.DynamicVars\.(\w+)\.IntValue; i\+\+\)\s*\{\s*await CardCmd\.AutoPlay", play)
    if m:
        out["playsSkill"] = m.group(1)
    if "PileType.Exhaust" in method_bodies(src, "AfterAutoPrePlayPhaseEnteredEarly") and "CardCmd.AutoPlay(" in src:
        out["fromExhaustStart"] = True
    if "Cards.FirstOrDefault() == this" in method_bodies(src, "AfterAutoPostPlayPhaseEntered"):
        out["autoplaysTop"] = True
    if "PlayerCmd.EndTurn(" in play:
        out["endsTurn"] = True
    m = re.search(r"CardType\.Skill[\s\S]*% base\.DynamicVars\.(\w+)\.IntValue == 0[\s\S]*CardPileCmd\.Add\(this, PileType\.Hand\)",
                  method_bodies(src, "AfterCardPlayedLate"))
    if m:
        out["returnsOnSkills"] = {"type": "Skill", "every": m.group(1)}
    drawn = method_bodies(src, "AfterCardDrawn")
    if "card != this" in drawn:
        if "EnergyCost.AddThisCombat(-1)" in drawn:
            out["onDraw"] = {"cost": -1}
        elif (m := re.search(r"DynamicVars\[\"(\w+)\"\]\.BaseValue;\s*base\.DynamicVars\.Damage\.BaseValue \+=", drawn)):
            out["onDraw"] = {"dmg": m.group(1)}
    m = re.search(r"GetDistinctForCombat\(base\.Owner, ModelDb\.CardPool<(\w+)CardPool>\(\)[^;]*?, "
                  r"(\d+|base\.DynamicVars\.(\w+)\.IntValue), ", play)
    if m and "PileType.Hand" in play:
        n = int(m.group(2)) if m.group(2).isdigit() else m.group(3)
        choose = "FromChooseACardScreen" in play
        out["makesRandom"] = {"pool": m.group(1), "n": 1 if choose else n, **({"choose": n} if choose else {}),
                              "up": "CardCmd.Upgrade(" in play}
    m = re.search(r"VisualCardPool\.Is(\w+)[\s\S]*for \(int i = 0; i < base\.DynamicVars\.(\w+)\.IntValue; i\+\+\)\s*\{\s*"
                  r"CardModel \w+ = selection\.CreateClone\(\)", play)
    if m:
        out["clones"] = {"of": m.group(1), "n": m.group(2)}
    if "GetOwnerParryAmount(this) > 0m" in play:
        out["blockFrom"] = "Parry"
    return out


def regent_relic(src: str) -> dict:
    """Regent relic effects: `nthFree` a var for the card of a turn that
    costs no energy or stars (Brilliant Scarf: the 5th), `openMakes` {pool,
    n} random cards of a pool into the hand on turn 1 (Orange Dough: 2
    Colorless), `tagMult` {tag, by} for damage and block of cards with a tag
    (Vitruvian Minion: Minion cards x2)."""
    out = {}
    if "TryModifyStarCost" in src and "TryModifyEnergyCostInCombatLate" in src and "CardsPlayedThisTurn" in src:
        m = re.search(r"new CardsVar\((\d+)\)", src)
        out["nthFree"] = "Cards" if m else 1
    body = method_bodies(src, "AfterSideTurnStart")
    m = re.search(r"ModelDb\.CardPool<(\w+)CardPool>\(\)[^;]*base\.DynamicVars\.(\w+)\.IntValue", body)
    if m and "TurnNumber <= 1" in body and "PileType.Hand" in body:
        out["openMakes"] = {"pool": m.group(1), "n": m.group(2)}
    m = re.search(r"Tags\.Contains\(CardTag\.(\w+)\)\)\s*\{\s*return 1m;\s*\}\s*return (\d+)m;", method_bodies(src, "ModifyDamageMultiplicative"))
    if m:
        out["tagMult"] = {"tag": m.group(1), "by": int(m.group(2))}
    return out


def in_combat_changes(src: str, play: str) -> dict:
    """What a card changes for the rest of the fight: `grows` its own damage
    by a var each play (Rampage) or by the attack it exhausted (Thrash),
    `growsAll` every copy's (Claw), `doubles` a power on the target (Molten
    Fist: Vulnerable), `upgrades` / `upgradesUp` cards in hand ("pick" one,
    or the whole "hand": Armaments), `transforms` a card type in hand into
    another card (Primal Force: Attacks into Giant Rock), `generates` random
    cards of your pool, one per card it exhausted (Stoke), and
    `fromExhaust`: plays itself from the exhaust pile at the end of the
    turn (Howl from Beyond)."""
    out = {}
    m = re.search(r"DynamicVars\.Damage\.BaseValue \+= base\.DynamicVars\[\"(\w+)\"\]\.BaseValue", play)
    if m:
        out["grows"] = m.group(1)
    elif re.search(r"DynamicVars\.Damage\.BaseValue \+= damage;", play) and "CardCmd.Exhaust" in play:
        out["grows"] = "exhausted"
    m = re.search(r"AllCards\.OfType<(\w+)>\(\);\s*decimal \w+ = base\.DynamicVars\[\"(\w+)\"\]", play)
    if m:
        out["growsAll"] = m.group(2)
    m = re.search(r"int (\w+) = [^;]*GetPowerAmount<(\w+)Power>\(\)[^;]*;\s*if \(\1 > 0\)\s*\{\s*"
                  r"await PowerCmd\.Apply<\2Power>\([^,]+, [^,]+, \1,", play)
    if m:
        out["doubles"] = m.group(2)
    hand_up = re.search(r"PileType\.Hand\.GetPile\(base\.Owner\)\.Cards[^;{]*\)\)\s*\{\s*CardCmd\.Upgrade\(item\)", play)
    if "FromHandForUpgrade" in play:
        out["upgrades"] = "pick"
        if hand_up and re.search(r"if \(base\.IsUpgraded\)\s*\{\s*foreach", play):
            out["upgradesUp"] = "hand"
    elif hand_up:
        out["upgrades"] = "hand"
    m = re.search(r"PileType\.Hand\.GetPile\(base\.Owner\)\.Cards\.Where\([^;]*c\.Type == CardType\.(\w+)\)[^;]*;"
                  r"[^}]*CreateCard<(\w+)>", play)
    if m and "CardCmd.Transform(" in play:
        out["transforms"] = {"type": m.group(1), "into": game_id(m.group(2))}
    if re.search(r"int (\w+) = list\.Count;.*CardFactory\.GetForCombat\([^;]*CardPool[^;]*, \1,", play, re.S):
        out["generates"] = "exhausted"
    if "PileType.Exhaust" in method_bodies(src, "AfterAutoPostPlayPhaseEntered") and "CardCmd.AutoPlay" in src:
        out["fromExhaust"] = True
    return out


# What a calculated var counts (the body of its WithMultiplier) -> what the sim counts
CALC_OF = (
    (r"^PileType\.Exhaust\.GetPile\(card\.Owner\)\.Cards\.Count\)$", "exhaustPile"),   # Ashen Strike
    (r"AllCards\.Count\(\(CardModel c\) => c\.Tags\.Contains\(CardTag\.Strike\)\)", "strikes"),  # Perfected Strike
    (r"^card\.Owner\.Creature\.Block\)$", "block"),                                    # Body Slam
    (r"e\.Receiver == card\.Owner\.Creature && e\.Result\.UnblockedDamage > 0", "timesHurt"),  # Tear Asunder
    (r"CardPlaysFinished.*HappenedThisTurn.*CardType\.Attack", "attacksThisTurn"),    # Finisher
    (r"CardPlaysFinished.*HappenedThisTurn.*CardType\.Skill", "skillsThisTurn"),
    (r"CardDrawnEntry.*HappenedThisTurn.*!e\.FromHandDraw", "drawnThisTurnExtra"),
    (r"CardDrawnEntry.*HappenedThisTurn", "drawnThisTurn"),
    (r"CardDrawnEntry", "drawnThisCombat"),                                           # Murder
    (r"CardDiscardedEntry.*HappenedThisTurn", "discardedThisTurn"),                   # Memento Mori
    (r"^PileType\.Draw\.GetPile\(card\.Owner\)\.Cards\.Count\)$", "drawPile"),         # Mind Blast
    (r"^PileType\.Discard\.GetPile\(card\.Owner\)\.Cards\.Count\(\)\)$", "discardPile"),  # Stack
    (r"PileType\.Hand\.GetPile\(card\.Owner\)\.Cards\.Count\(\(CardModel c\) => c\.Type == CardType\.Skill\)", "skillsInHand"),
    (r"Enemies\.Where.*Sum.*GetPowerAmount<PoisonPower>", "poisonAll"),                # Mirage
    (r"^target\?\.Powers\.Count", "targetPowers"),                                    # Rend
    (r"PileType\.Hand\.GetPile\(card\.Owner\)\.Cards\.Count;[\s\S]*num--", "handOthers"),  # Precise Cut
    (r"from orb in .*OrbQueue\.Orbs", "uniqueOrbs"),                                  # Compile Driver
    (r"OrbQueue\.Orbs\.Count\)$", "orbs"),                                            # Barrage
    (r"OrbChanneledEntry.*e\.Orb is LightningOrb", "lightningChanneled"),             # Voltaic
    (r"EnergySpentEntry[\s\S]*HappenedThisTurn", "energySpentThisTurn"),              # Helix Drill
    (r"osty\.CurrentHp", "ostyHp"),                                                   # Unleash
    (r"Osty\.MaxHp \* 3", "ostyMax3"),                                                # Sacrifice
    (r"osty\.MaxHp", "ostyMax"),                                                      # Protector
    (r"CardTag\.OstyAttack\) && c != card", "ostyAttackCards"),                       # Squeeze
    (r"ExhaustPile\.Cards\.Count\(\(CardModel c\) => c is Soul\)", "exhaustedSouls"),  # Soul Storm
    (r"CreatureAttackedEntry.*e\.Actor == card\.Owner\.Osty.*HappenedThisTurn", "ostyAttacksThisTurn"),  # Rattle
    (r"CardPlayFinishedEntry.*e\.WasEthereal", "etherealPlayed"),                     # Pull from Below
    (r"GetPowerAmount<DoomPower>[\s\S]*Math\.Floor", "targetDoomTens"),               # No Escape
    (r"StarsModifiedEntry", "starsGainedThisTurn"),                                   # Radiate
    (r"CardGeneratedEntry.*c\.Creator == card\.Owner", "generatedThisCombat"),        # Supermassive
    (r"CanonicalStarCost >= 0 \|\| c\.HasStarCostX", "starCards"),                    # Crescent Spear
    (r"DamageReceivedEntry.*e\.Receiver == target.*IsPoweredAttack.*HappenedThisTurn", "targetHitsThisTurn"),  # Beat Into Shape
    (r"^CombatManager\.Instance\.History\.CardPlaysFinished\.Count\(\)\)$", "cardsPlayed"),  # Gold Axe
)


def calculated(src: str) -> dict:
    """A calculated var past a power's stack (see scan_card's perStack):
    `calc` {to: "dmg" / "block" / "hits", of: what it counts (CALC_OF),
    plus: a constant the count starts from}. It comes to CalculationBase +
    the extra var (ExtraDamage, else CalculationExtra) times the count:
    Ashen Strike's 6 + 3 per card in the exhaust pile, Tear Asunder's hits
    1 + the times you took unblocked damage. `to` can also be "draw"
    (Compile Driver), "power:<name>" for a power's amount (Synchronize),
    "count" for a loop's (Voltaic) or "forge" (Beat Into Shape). Osty's HP /
    max HP (Unleash, Protector; Sacrifice's block is 3x his max HP), Osty
    attacks this turn (Rattle), Ethereal cards played (Pull from Below), the
    target's Doom in tens (No Escape), stars gained this turn (Radiate),
    cards made this fight (Supermassive), cards with a star cost (Crescent
    Spear), the target's hits taken this turn (Beat Into Shape) and cards
    played this fight (Gold Axe) are counted."""
    m = re.search(r"new (Calculated\w*)Var\((?:\"(\w+)\")?[^)]*\)(?:\.FromOsty\(\))?\.WithMultiplier\(\(CardModel \w+, Creature\?? ?\w*\) => (.*)", src)
    neg = False
    if m:
        kind, name, body = m.groups()
    else:
        # Precise Cut's delegate: minus the other cards in hand; Helix Drill's
        # energy spent on the turn's other cards.
        m = re.search(r"new (Calculated\w*)Var\((?:\"(\w+)\")?[^)]*\)(?:\.FromOsty\(\))?\.WithMultiplier\(delegate\([^)]*\)", src)
        if not m:
            return {}
        kind, name = m.groups()
        body = braced(src, m.end())
        neg = "return -num;" in body
    body = body.strip().rstrip(",")
    plus = re.match(r"(\d+) \+ (.*)", body)
    if plus:
        body = plus.group(2)
    of = next((key for pattern, key in CALC_OF if re.search(pattern, body)), None)
    to = {"CalculatedDamage": "dmg", "CalculatedBlock": "block"}.get(kind)
    if kind == "Calculated" and name and re.search(rf"WithHitCount\([^;]*\"{name}\"", src):
        to = "hits"
    calc_of = rf"\(\(CalculatedVar\)base\.DynamicVars\[\"{name}\"\]\)\.Calculate"
    if kind == "Calculated" and name and re.search(rf"\.Draw\(\w+, {calc_of}", src):
        to = "draw"  # Compile Driver
    p = re.search(rf"PowerCmd\.Apply<(\w+)Power>\([^;]*{calc_of}", src) if name else None
    if kind == "Calculated" and p:
        to = "power:" + p.group(1)  # Synchronize: its Focus
    if kind == "Calculated" and name and re.search(rf"int \w+ = \(int\){calc_of}", src):
        to = "count"  # Voltaic: a loop's count (see orb_ops)
    f = re.search(rf"decimal (\w+) = {calc_of}", src) if name else None
    if kind == "Calculated" and f and re.search(rf"ForgeCmd\.Forge\({f.group(1)}\b", src):
        to = "forge"  # Beat Into Shape
    if not (of and to):
        return {}
    return {"calc": {"to": to, "of": of, **({"plus": int(plus.group(1))} if plus else {}), **({"neg": True} if neg else {})}}


def orb_count(expr: str, local: dict):
    """A loop bound in an orb card: a literal, a var, or a local's meaning."""
    expr = re.sub(r"^\((?:decimal|int)\)", "", expr.strip())
    if expr in local:
        return local[expr]
    a = amount(expr)
    return a if a is not None else "varies"


def orb_ops(play: str) -> list:
    """What a card does with orbs, in order: `channel` (an orb type, or
    Random), `evoke` (the next orb n times, then it goes), `passive` (each
    orb of a type n times, onTarget for Tesla Coil) and `slots` (+/-).
    Each op has `n` (a literal or a var), `upN` when upgrading changes it,
    `times`: what it repeats for ("enemies" for Chill, "orbs" held for
    Shatter, "X" for Tempest, "calc" for Voltaic's count, or a var), `upPlus`
    when upgrading adds one to an X, and `up` when only the upgraded card
    does it (Spinner's Glass). Ignition's orb is an ally's and is left out."""
    local = {}
    for m in re.finditer(r"int (\w+) = ResolveEnergyXValue\(\);", play):
        local[m.group(1)] = "X"
    for m in re.finditer(r"int (\w+) = base\.Owner\.PlayerCombatState\.OrbQueue\.Orbs\.Count;", play):
        local[m.group(1)] = "orbs"
    for m in re.finditer(r"int (\w+) = \(int\)\(\(CalculatedVar\)base\.DynamicVars\[\"\w+\"\]\)\.Calculate", play):
        local[m.group(1)] = "calc"
    for m in re.finditer(r"int (\w+) = \(\(!base\.IsUpgraded\) \? (\d+) : (\d+)\);", play):
        local[m.group(1)] = (int(m.group(2)), int(m.group(3)))  # Darkness
    for m in re.finditer(r"(\w+) = base\.CombatState\.HittableEnemies;", play):
        local[m.group(1)] = "enemies"
    for m in re.finditer(r"(\w+) = base\.Owner\.PlayerCombatState\.OrbQueue\.Orbs\.(?:Where\(\(OrbModel orb\) => orb is "
                         r"(\w+)Orb\)|OfType<(\w+)Orb>\(\))", play):
        local[m.group(1)] = ("each", m.group(2) or m.group(3))
    up_plus = {name for name in local if re.search(rf"if \(base\.IsUpgraded\)\s*\{{\s*{name}\+\+;", play)}
    ops, stack, pending = [], [], None
    for line in play.splitlines():
        s = line.strip()
        m = re.match(r"for \(int i = 0; \(?(?:decimal\)?)?i < (.+?); i\+\+\)", s)
        f = re.match(r"foreach \(\w+ \w+ in (\w+)\)", s)
        if m:
            pending = {"loop": orb_count(m.group(1), local), "var": m.group(1).strip()}
        elif f:
            pending = {"loop": local.get(f.group(1), "varies")}
        elif s.startswith("if (base.IsUpgraded)"):
            pending = {"up": True}
        elif s.startswith(("if (", "else")):
            pending = {}
        if s == "{":
            stack.append(pending or {})
            pending = None
            continue
        if s == "}":
            if stack:
                stack.pop()
            continue
        op = None
        ch = re.search(r"OrbCmd\.Channel(?:<(\w+)Orb>)?\(", s)
        if ch and "cardPlay.Target.Player" not in s:
            op = {"op": "channel", "orb": ch.group(1) or ("Random" if "GetRandomOrb" in s else "varies")}
        elif "OrbCmd.EvokeNext(" in s:
            op = {"op": "evoke"}
        elif (p := re.search(r"OrbCmd\.Passive\(\w+, (\w+), (null|cardPlay\.Target)\)", s)):
            each = next((fr["loop"][1] for fr in stack if isinstance(fr.get("loop"), tuple) and fr["loop"][0] == "each"), None)
            op = {"op": "passive", "orb": each or "varies"}
            if p.group(2) != "null":
                op["onTarget"] = True
        elif (sl := re.search(r"OrbCmd\.(Add|Remove)Slots\(base\.Owner, ([^)]+?)\);", s)):
            n = amount(sl.group(2))
            op = {"op": "slots", "n": n if sl.group(1) == "Add" else f"-{n}" if isinstance(n, str) else -n}
        if not op:
            continue
        op.setdefault("n", 1)
        times = []
        for fr in stack:
            if fr.get("up"):
                op["up"] = True
            loop = fr.get("loop")
            if loop is None or (isinstance(loop, tuple) and loop[0] == "each"):
                continue
            # Multi-Cast and Quadcast evoke the same orb each time round and let it go on the last.
            same = op["op"] == "evoke" and re.search(r"i == ", s)
            if isinstance(loop, tuple):  # Darkness: 1, or 2 upgraded
                op["n"], op["upN"] = loop
            elif same or isinstance(loop, int):
                op["n"] = loop if not isinstance(loop, int) else op["n"] * loop
            else:
                times.append(loop)
            if not isinstance(loop, (int, tuple)) and fr.get("var") in up_plus:
                op["upPlus"] = 1
        if times:
            op["times"] = times[0] if len(times) == 1 else times
        last = ops[-1] if ops else None
        # Dualcast and Shatter: back-to-back evokes of the next orb are one orb evoked twice.
        if last and op["op"] == last["op"] == "evoke" and {k: v for k, v in op.items() if k != "n"} == \
                {k: v for k, v in last.items() if k != "n"} and isinstance(op["n"], int) and isinstance(last["n"], int):
            last["n"] += op["n"]
            continue
        ops.append(op)
    return ops


# The hook a power or relic acts on orbs in -> when the sim runs it
ORB_HOOK_AT = (("AfterEnergyReset", "start"), ("AfterPlayerTurnStart", "start"), ("BeforeSideTurnStart", "start"),
               ("AfterSideTurnStart", "start"), ("BeforeSideTurnEnd", "end"), ("AfterSideTurnEnd", "end"),
               ("AfterCardPlayed", "play"), ("AfterCardGeneratedForCombat", "statusMade"),
               ("AfterOrbEvoked", "evoked"), ("AfterOrbChanneled", "channeled"))


def orb_hooks(src: str) -> list:
    """What a power or relic does with orbs, on an event (ORB_HOOK_AT):
    `channel` an orb type n times (Lightning Rod, Spinner, Storm on a Power
    played, Trash to Treasure on a Status made, Cracked Core on turn 1),
    `evokeLast` (Consuming Shadow), `passiveFirst` (Loop) or `passiveAll`
    (Emotion Chip, after losing HP last turn), `slots` (Runic Capacitor),
    `blockPerUnique` (Coolant), damage to all foes with `ifFrost` (Hailstorm)
    or after a number of channels (Metronome), or `damage` to what a
    Lightning evoke hit (Thunder). Amounts are "Amount" or a var."""
    out = []
    for meth, at in ORB_HOOK_AT:
        body = method_bodies(src, meth)
        if not body or not re.search(r"Orb|OrbQueue", body):
            continue
        h = {"at": at}
        loop = re.search(r"for \(int i = 0; \(?(?:decimal\)?)?i < ([^;]+);", body)
        n = (amount(loop.group(1)) if loop else 1) or 1
        ch = re.search(r"OrbCmd\.Channel(?:<(\w+)Orb>)?\(", body)
        if ch:
            h["channel"], h["n"] = ch.group(1) or "Random", n
        elif "OrbCmd.EvokeLast(" in body:
            h["evokeLast"] = n
        elif re.search(r"OrbCmd\.Passive\(\w+, \w+\.PlayerCombatState\.OrbQueue\.Orbs\[0\]", body):
            h["passiveFirst"] = n
        elif re.search(r"foreach \(OrbModel (\w+) in [^)]*OrbQueue\.Orbs\)\s*\{\s*await OrbCmd\.Passive\(\w+, \1", body):
            h["passiveAll"] = 1
            if "LostHpInPreviousTurn" in body:
                h["ifLostHp"] = True
        elif (sl := re.search(r"OrbCmd\.AddSlots\(base\.Owner, ([^)]+?)\);", body)):
            h["slots"] = amount(sl.group(1))
        elif "group orb by orb.Id" in body and "GainBlock" in body:
            h["blockPerUnique"] = "Amount"
        elif (fr := re.search(r"Count\(\(OrbModel o\) => o is FrostOrb\);\s*if \(\w+ >= base\.DynamicVars\[\"(\w+)\"\]", body)):
            h["aoe"], h["ifFrost"] = "Amount", fr.group(1)
        elif at == "channeled" and (c := re.search(r"== base\.DynamicVars\[\"(\w+)\"\]\.IntValue", body)):
            h["aoe"], h["every"] = "Damage", c.group(1)
            h["perCombat"] = 1
        elif at == "evoked" and "orb is LightningOrb" in body and "CreatureCmd.Damage" in body:
            h["damage"] = "Amount"
        else:
            continue
        if at == "play" and (t := re.search(r"Card\.Type != CardType\.(\w+)", src)):
            h["type"] = t.group(1)  # Storm: Powers
            if "amountsForPlayedCards.Add" in method_bodies(src, "BeforeCardPlayed"):
                h["snapshot"], h["n"] = True, "Amount"  # its stack as the card started
        if at == "statusMade" and "CardType.Status" in body:
            h["type"] = "Status"
        if "TurnNumber <= 1" in body:
            h["first"] = True  # Cracked Core: the first turn only
        if "PowerCmd.Decrement(this)" in body:
            h["decrements"] = True  # Lightning Rod: one a turn for its stack of turns
        out.append(h)
    return out


def orb_mods(src: str) -> dict:
    """Relic changes to orbs: Gold-Plated Cables' extra passive for the
    first orb, Infused Core's bonus to Lightning (a var)."""
    out = {}
    if "ModifyOrbPassiveTriggerCounts" in src and "OrbQueue.Orbs[0]" in src:
        out["firstPassiveExtra"] = 1
    m = re.search(r"orb is (\w+)Orb\)\)\s*\{\s*return value;\s*\}\s*return value \+ base\.DynamicVars\[\"(\w+)\"\]",
                  method_bodies(src, "ModifyOrbValue"))
    if m:
        out["orbBonus"] = {"orb": m.group(1), "by": m.group(2)}
    return out


# A condition in a card's code -> what the sim checks
CONDS = (
    (r"cardPlay\.Target\.HasPower<VulnerablePower>\(\)", "targetVulnerable"),  # Dismantle
    (r"cardPlay\.Target\.HasPower<PoisonPower>\(\)", "targetPoisoned"),        # Bubble Bubble
    (r"LostHpThisTurn\(", "lostHpThisTurn"),                                   # Spite
    (r"WasCardExhaustedThisTurn", "exhaustedThisTurn"),                        # Evil Eye
    (r"^CanDealDamage$", "exhaustPileAtLeast"),                               # Pact's End: Cards in it
    (r"Monster\.IntendsToAttack", "targetAttacks"),                            # Go for the Eyes
    (r"PileType\.Draw\.GetPile\(base\.Owner\)\.Cards\.Count == 0", "drawPileEmpty"),  # Grand Finale
    (r"PileType\.Hand\)\.All\(\(CardModel c\) => c\.Type == CardType\.Attack\)", "onlyAttacksInHand"),  # Clash
    (r"^WasDoomAppliedThisTurn$", "doomAppliedThisTurn"),                      # Death's Door
)


def cond_of(text: str) -> str | None:
    return next((key for pattern, key in CONDS if re.search(pattern, text.strip())), None)


def conditions(src: str, play: str) -> dict:
    """Effects that hang on a condition (CONDS): `twiceIf` {if, times: a var
    or literal, to: "hits" / "block", plus: added to times} when the
    condition multiplies them (Dismantle hits twice on a Vulnerable target,
    Spite Repeat times after you lost HP, Evil Eye blocks twice after an
    exhaust, Death's Door 1 + Repeat times after you applied Doom); `onlyIf` when the
    card's attack only happens then (Pact's End); `appliesIf` {power: cond}
    for a power it only applies then (Go for the Eyes' Weak); `playableIf`
    when the card can't be played otherwise (Clash, Grand Finale)."""
    out = {}
    m = re.search(r"int (\w+) = \(\(!(.+?)\) \? 1 : (\d+|base\.DynamicVars(?:\.(\w+)|\[\"(\w+)\"\])\.IntValue)\);", play)
    if m and cond_of(m.group(2)):
        times = int(m.group(3)) if m.group(3).isdigit() else m.group(4) or m.group(5)
        to = "hits" if re.search(rf"WithHitCount\({m.group(1)}\)", play) else "block" if "GainBlock" in play else None
        if to:
            out["twiceIf"] = {"if": cond_of(m.group(2)), "times": times, "to": to}
    m = re.search(r"int (\w+) = 1;\s*if \((\w+)\)\s*\{\s*\1 \+= base\.DynamicVars\.(\w+)\.IntValue;", play)
    if m and cond_of(m.group(2)) and "GainBlock" in play:
        out["twiceIf"] = {"if": cond_of(m.group(2)), "times": m.group(3), "plus": 1, "to": "block"}
    for m in re.finditer(r"if \((.+?)\)\s*\{", play):
        cond = cond_of(m.group(1))
        if not cond:
            continue
        block = braced(play, m.end() - 1)
        if "DamageCmd.Attack(" in block and play.count("DamageCmd.Attack(") == 1:
            out["onlyIf"] = cond
        for power in re.findall(r"PowerCmd\.Apply<(\w+)Power>", block):
            out.setdefault("appliesIf", {})[power] = cond
    m = re.search(r"override bool IsPlayable => (.+);", src)
    if m and cond_of(m.group(1)):
        out["playableIf"] = cond_of(m.group(1))
    return out


def generators(src: str, play: str) -> dict:
    """Cards a card puts into the fight, past Shivs and named cards: `copyTo`
    a pile for a copy of itself (Anger: the discard pile; `copyFree` when
    it costs 0, Adaptive Strike), `puts` named cards made into a pile, with
    how many (Fight Through: 2 Wounds into the discard pile; Crash Landing:
    Debris up to a full hand), `randomFree` a
    random card of that type from your pool, free this turn (Infernal
    Blade: an Attack), `discardToTop` a card of your pick from the discard
    pile back on top of the draw pile (Headbutt). Also `costDown`: a cost
    cut this turn per card of a type played (Stomp: Attacks)."""
    out = {}
    m = re.search(r"= CreateClone\(\);((?:[^;]*;)??)[^;]*AddGeneratedCardToCombat\(\w+, PileType\.(\w+)", play)
    if m:
        out["copyTo"] = m.group(2)
        if "EnergyCost.SetThisCombat(0)" in m.group(1):
            out["copyFree"] = True  # Adaptive Strike: the copy costs 0
    statuses = []
    for m in re.finditer(r"CreateCard<(\w+)>\(base\.Owner\)[^;]*;?[^;]*AddGeneratedCards?ToCombat\([^;]*PileType\.(\w+)", play):
        loop = re.findall(r"for \(int i = 0; i < (\w+); i\+\+\)", play[:m.start()])
        n = 1
        if loop:
            n = int(loop[-1]) if loop[-1].isdigit() else "fullHand" if "MaxCardsInHand" in play else "varies"
        statuses.append({"id": game_id(m.group(1)), "pile": m.group(2), "n": n})
    for m in re.finditer(r"AddGeneratedCardToCombat\(base\.CombatState\.CreateCard<(\w+)>\(base\.Owner\), PileType\.(\w+)", play):
        statuses.append({"id": game_id(m.group(1)), "pile": m.group(2), "n": 1})  # Collision Course
    if statuses:
        out["puts"] = statuses
    m = re.search(r"GetDistinctForCombat\([^;]*c\.Type == CardType\.(\w+)", play)
    if m and "SetToFreeThisTurn" in play and "PileType.Hand" in play:
        out["randomFree"] = m.group(1)
    if re.search(r"FromCombatPile\([^;]*PileType\.Discard[^;]*;[^}]*PileType\.Draw, CardPilePosition\.Top", play, re.S):
        out["discardToTop"] = True
    m = re.search(r"CardPlaysFinished\.Count\([^;]*CardType\.(\w+)[^;]*HappenedThisTurn", src)
    if m and "EnergyCost.AddThisTurn(-" in src:
        out["costDown"] = m.group(1)
    return out


def pile_moves(src: str, play: str) -> dict:
    """Cards a card moves between piles: `fromDiscard` {n, pick, free, to}
    out of the discard pile (Hologram picks 1 into your hand, Dredge picks
    Cards, All for One takes every 0-cost card; Cosmic Indifference puts
    its pick on top of the draw pile, read as `discardToTop`), `playsFrom`
    {pile, type, n} random cards of a type autoplayed out of a pile (Uproar:
    an Attack from the draw pile; Beat Down: Cards of them from the
    discard pile), `upgradesDiscard` random cards upgraded there (Drain
    Power: Cards of them), `doublesEnergy` (Double Energy) and `handToDraw`
    (Reboot shuffles your hand into the draw pile before it draws)."""
    out = {}
    pick = re.search(r"CardSelectCmd\.FromCombatPile\([^;]*PileType\.Discard\.GetPile\(base\.Owner\)", play)
    m = pick and re.search(r"CardSelectorPrefs\(base\.SelectionScreenPrompt, (?:\d+, )?(\w+)\)", play)
    if m:
        n = m.group(1)
        if not n.isdigit():
            v = re.search(rf"int {n} = Math\.Min\(base\.DynamicVars\.(\w+)\.IntValue", play)
            n = v.group(1) if v else "varies"
        rest = play[pick.end():]
        if re.search(r"PileType\.Draw, CardPilePosition\.Top", rest):
            out["discardToTop"] = True  # Cosmic Indifference
        elif "PileType.Hand)" in rest:
            out["fromDiscard"] = {"n": int(n) if n.isdigit() else n, "pick": True, "to": "Hand"}
    if re.search(r"PileType\.Discard\.GetPile\(base\.Owner\)\.Cards\.Where\(Filter\)", play) \
            and "EnergyCost.GetWithModifiers(CostModifiers.All) == 0" in src and "PileType.Hand)" in play:
        out["fromDiscard"] = {"n": "all", "free": True, "to": "Hand"}  # All for One
    pile = re.search(r"PileType\.(Discard|Draw)\.GetPile\(base\.Owner\)", play)
    m = pile and re.search(r"\.Cards\.Where\(\(CardModel c\) => c\.Type == CardType\.(\w+)[^;]*", play)
    if m and "CardCmd.AutoPlay(" in play:
        take = re.search(r"\.Take\(base\.DynamicVars\.(\w+)\.IntValue\)", m.group(0))
        out["playsFrom"] = {"pile": pile.group(1), "type": m.group(1), "n": take.group(1) if take else 1}
    m = re.search(r"PileType\.Discard\.GetPile\(base\.Owner\)\.Cards\.Where\(\(CardModel c\) => c\.IsUpgradable\)"
                  r"\.TakeRandom\(base\.DynamicVars\.(\w+)", play)
    if m:
        out["upgradesDiscard"] = m.group(1)
    if "GainEnergy(base.Owner.PlayerCombatState.Energy," in play:
        out["doublesEnergy"] = True
    if re.search(r"foreach \(CardModel item in PileType\.Hand\.GetPile\(base\.Owner\)\.Cards\.ToList\(\)\)\s*\{\s*"
                 r"await CardPileCmd\.Add\(item, PileType\.Draw\);", play):
        out["handToDraw"] = True
    return out


def colorless(src: str, play: str) -> dict:
    """Colorless card effects: `blockFromDamage` (Fisticuffs blocks what it
    dealt), `returnsNextTurn` (Bolas, Thrumming Hatchet: back in hand the
    turn after it's played), `fetches` {type, n, choose, rarity} cards out
    of the draw pile into your hand (Wish: any 1; Secret Technique: a
    Skill; Seeker Strike: 1 of Cards random ones; Anointed: every Rare, up
    to a full hand), `playsFrom` with no type (Catastrophe: Cards random
    playable ones from the draw pile), `makesRandom` {pool: Colorless /
    own / others, type, n, choose, up, free: turn / combat, zeroCost, pile}
    (Jack of All Trades: Cards colorless; Discovery: 1 of 3 of your own,
    free this turn; Splash: 1 of 3 Attacks of another character's;
    Jackpot: Cards 0-cost ones of yours; Metamorphosis: Cards Attacks into
    the draw pile, free all fight) and `replaysDrawCard` the var a random
    draw-pile card's replays go up by (Hidden Gem: Replay), `bombDamage`
    the var The Bomb's power goes off for."""
    out = {}
    if re.search(r"GainBlock\(base\.Owner\.Creature, \w+\.Results\.SelectMany", play):
        out["blockFromDamage"] = True
    back = method_bodies(src, "BeforeHandDraw")
    if "HappenedLastPlayerTurn" in back and "CardPileCmd.Add(this, PileType.Hand)" in back:
        out["returnsNextTurn"] = True
    m = re.search(r"CardSelectCmd\.FromCombatPile\([^;]*PileType\.Draw\.GetPile\(base\.Owner\)[^;]*;", play)
    if m and re.search(r"CardPileCmd\.Add\(\w+, PileType\.Hand\)", play[m.end():]):
        n = re.search(r"CardSelectorPrefs\(base\.SelectionScreenPrompt, (\d+)\)", m.group(0))
        t = re.search(r"c\.Type == CardType\.(\w+)", m.group(0))
        choose = re.search(r"StableShuffle\([^)]*\)\.Take\(base\.DynamicVars\.(\w+)\.IntValue\)", play)
        out["fetches"] = {"type": t and t.group(1), "n": int(n.group(1)) if n else 1,
                          **({"choose": choose.group(1)} if choose else {})}
    m = re.search(r"PileType\.Draw\.GetPile\(base\.Owner\)\.Cards\.Where\(\(CardModel c\) => c\.Rarity == CardRarity\.(\w+)\)"
                  r"\.TakeRandom\(\w+", play)
    if m and "MaxCardsInHand" in play and "PileType.Hand)" in play:
        out["fetches"] = {"type": None, "rarity": m.group(1), "n": "fullHand"}  # Anointed
    m = re.search(r"for \(int i = 0; i < base\.DynamicVars\.(\w+)\.IntValue; i\+\+\)\s*\{\s*CardModel \w+ = "
                  r"PileType\.Draw\.GetPile\(base\.Owner\)\.Cards\.Where\(\(CardModel c\) => "
                  r"!c\.Keywords\.Contains\(CardKeyword\.Unplayable\)\)", play)
    if m and "CardCmd.AutoPlay(" in play:
        out["playsFrom"] = {"pile": "Draw", "type": None, "n": m.group(1)}  # Catastrophe
    m = re.search(r"CardFactory\.(GetDistinctForCombat|GetForCombat)\(base\.Owner, ([\s\S]*?), "
                  r"(\d+|base\.DynamicVars\.(\w+)\.IntValue), base\.Owner\.RunState\.Rng", play)
    if m:
        args = m.group(2)
        pool = "Colorless" if "ColorlessCardPool" in args \
            else "others" if "Remove(base.Owner.Character.CardPool)" in play \
            else "own" if "Character.CardPool" in args else None
        n = int(m.group(3)) if m.group(3).isdigit() else m.group(4)
        choose = "FromChooseACardScreen" in play
        t = re.search(r"c\.Type == CardType\.(\w+)", play[:m.end()])
        to = re.search(r"AddGeneratedCardToCombat\(\w+, PileType\.(\w+)", play)
        if pool and to:
            out["makesRandom"] = {
                "pool": pool, "n": 1 if choose else n, **({"choose": n} if choose else {}),
                "up": "CardCmd.Upgrade(" in play, **({"type": t.group(1)} if t else {}),
                **({"free": "turn"} if "SetToFreeThisTurn" in play else {"free": "combat"} if "SetToFreeThisCombat" in play else {}),
                **({"zeroCost": True} if "Canonical == 0" in args else {}),
                **({"pile": to.group(1)} if to.group(1) != "Hand" else {})}
    m = re.search(r"BaseReplayCount \+= base\.DynamicVars\[\"(\w+)\"\]", play)
    if m and "PileType.Draw.GetPile" in play:
        out["replaysDrawCard"] = m.group(1)
    m = re.search(r"\.SetDamage\(base\.DynamicVars\[\"(\w+)\"\]", play)
    if m:
        out["bombDamage"] = m.group(1)  # The Bomb's blast, set on the power it applies
    return out


def card_loops(src: str, play: str) -> dict:
    """Effects a card repeats or scales past its vars: `applyRepeat` the var
    its powers are applied that many times over (Bouncing Flask: Repeat),
    `discardsHand` (Storm of Steel, Shadow Step), `makesPerDiscarded` a
    card made once per card it discarded (Storm of Steel: Shivs),
    `repeatOnKill` (Echoing Slash: again for each enemy it kills), and
    `playsExhausted` a tag it plays out of the exhaust pile (Knife Trap:
    every Shiv, upgraded first if it is)."""
    out = {}
    m = re.search(r"for \(int i = 0; i < base\.DynamicVars\.(\w+)\.IntValue; i\+\+\)", play)
    if m and "PowerCmd.Apply<" in braced(play, m.end()):
        out["applyRepeat"] = m.group(1)
    if "CardCmd.Discard(choiceContext, PileType.Hand.GetPile(base.Owner).Cards)" in play \
            or re.search(r"(\w+) = PileType\.Hand\.GetPile\(base\.Owner\)\.Cards\.ToList\(\);[\s\S]*"
                         r"CardCmd\.Discard\(choiceContext, \1\)", play):
        out["discardsHand"] = True
    m = re.search(r"int (\w+) = \w+\.Count\(\);[\s\S]*?(\w+)\.CreateInHand\(base\.Owner, \1", play)
    if m and out.get("discardsHand"):
        out["makesPerDiscarded"] = game_id(m.group(2))
    if "WasTargetKilled" in play and re.search(r"attackCount \+=", play):
        out["repeatOnKill"] = True
    m = re.search(r"PileType\.Exhaust\.GetPile\(base\.Owner\)\.Cards\.Where\(\(CardModel c\) => "
                  r"c\.Tags\.Contains\(CardTag\.(\w+)\)\)", play)
    if m and "CardCmd.AutoPlay" in play:
        out["playsExhausted"] = m.group(1)
    return out


def card_tags(src: str) -> list[str]:
    """The card's tags (Strike, Shiv...): what Perfected Strike and
    Hellraiser look for."""
    m = re.search(r"CanonicalTags => new HashSet<CardTag>\s*\{([^}]*)\}", src)
    return sorted(re.findall(r"CardTag\.(\w+)", m.group(1))) if m else []


def power_rules(src: str, parent: str) -> dict:
    """How a power changes the rules of play, past damage and economy:
    `temp` {stat, sign} for Temporary Strength / Dexterity / Focus (it
    gives or takes the stat until the owner's turn ends: Setup Strike +,
    Piercing Wail -); `vulnBonus` (Cruelty: Vulnerable hits deal Amount %
    more); `replays` {type, decrements, perTurn} when cards play an extra
    time (One-Two Punch: the next Attack; Echo Form: the first Amount cards
    each turn); `free` {type or keyword, decrements} when cards cost 0
    (Corruption: Skills, for good; Free Skill: the next one; Void Form:
    the first Amount cards each turn) and
    `exhaustsType` when that type exhausts once played (Corruption);
    `lasts: turn` when it's gone at the end of the owner's turn (Rage);
    `fromDiscard` a type it pulls into hand each turn, upgraded (Aggression);
    `playsDrawn` a tag it auto-plays when drawn (Hellraiser); `endPlays` a
    type it plays from hand at the end of the turn (Stampede); `copiesNth`
    the Attack each turn it copies into hand (Juggling: the 3rd);
    `weakBonus` (Tracking: Amount % more on Weak foes); `dmgMult` (Double
    Damage); `blockDoubles` block doubled per stack (Shadowmeld);
    `keepsBlock` (Blur, Barricade); `keepsHand` (Well-Laid Plans: no
    discard at turn end); `turnMakes` a card it puts in hand each turn, its
    stack of them (Infinite Blades: Shivs); `clonesNextTurn` (Nightmare:
    copies of the card picked, next turn); `firstTagBonus` damage on the
    first card of a tag each turn and `retainsTag` (Phantom Blades: Shivs);
    `hurtsOnPlay` on an enemy, which takes its stack each time you play a
    card (Strangle); `keywordOnPlay` {type, keyword} given to played cards
    (Master Planner: Skills gain Sly); `buffer` (Buffer: the next HP loss
    is 0, a stack spent each); `zeroCostBonus` (One for All: Amount more
    damage on 0-cost Attacks, not X); `returnsZeroCost` a type that goes back
    to the hand when played for 0, Amount a turn (Feral: Attacks);
    `turnMakesRandom` a random card of that type from the character's pool
    into the hand each turn, its stack of them (Creative AI: Powers; Call of
    the Void: "Any", `turnMakesEthereal`). Necrobinder: `doomsOnPlay`
    (Oblivion: its stack of Doom on that enemy per card played),
    `doomPerDamage` (Reaper Form: Doom of the damage dealt times its stack),
    `summonOnOstyHit` (Sic 'Em), `ostyLossHits` (Necro Mastery: every enemy
    takes Osty's HP lost times its stack), `ostyBonus` (Calcify: Osty's
    hits), `firstAttackBonus` (Lethality), `cardMult` (Hang: hits from that
    card times its stack) and `costUp` (Borrowed Time: cards cost its stack
    more). Regent: `strPerPlay` (Monologue: Strength per card played this
    turn), `drawAfterAttacks` (Pale Blue Dot: draw next turn after that
    many Attacks), `energyPer` (Orbit: its stack per that much energy
    spent), `bladeReplays` (Sword Sage: the Sovereign Blade plays its
    stack more times), `bladeMultFoe` (Conqueror: the blade deals double
    to this enemy), `hitStrDown` (Monarch's Gaze), `reflect` (Reflect),
    `handDrawOnce` (Foregone Conclusion) and Spectrum Shift's Colorless
    `turnMakesRandom`. Colorless: `tagBlock` (Fasten: more block on that
    tag), `noCardBlock` (No Block), `turnPlaysTop` (Mayhem), `topsFirst`
    (Nostalgia), `turnAoeGrows` its growth (Rolling Boulder), `bomb` (The
    Bomb: its damage is the card's `bombDamage`), `shuffleFetch`
    (Stratagem), `attackMakesRandom` (Calamity), `turnTransforms` (Entropy)
    and `gambit` (The Gambit). Read
    from other code (see main):
    `poisonTicks` (Accelerant: Poison triggers that many more times) and
    `aoeTag` (Fan of Knives: Shivs hit every enemy)."""
    out = {}
    m = re.match(r"Temporary(Strength|Dexterity|Focus)Power$", parent)
    if m:
        out["temp"] = {"stat": m.group(1), "sign": -1 if "IsPositive => false" in src else 1}
    vm = re.search(r"\bModifyVulnerableMultiplier\(", src)  # a plain method, not an override
    if vm and "base.Amount / 100m" in braced(src, vm.end()):
        out["vulnBonus"] = True
    body = method_bodies(src, "ModifyCardPlayCount")
    if "playCount + 1" in body:
        t = re.search(r"card\.Type != CardType\.(\w+)", body)
        out["replays"] = {"type": t.group(1) if t else None,
                          "decrements": "PowerCmd.Decrement(this)" in method_bodies(src, "AfterModifyingCardPlayCount"),
                          **({"perTurn": True} if "HappenedThisTurn" in body and "num >= base.Amount" in body else {})}
    body = method_bodies(src, "TryModifyEnergyCostInCombatLate")
    if re.search(r"modifiedCost = default\(decimal\);\s*return true;", body):
        t = re.search(r"card\.Type != CardType\.(\w+)", body)
        k = re.search(r"Keywords\.Contains\(CardKeyword\.(\w+)\)", body)
        out["free"] = {**({"type": t.group(1)} if t else {}), **({"keyword": k.group(1)} if k else {}),
                       "decrements": "PowerCmd.Decrement(this)" in src,
                       **({"perTurn": True} if "cardsPlayedThisTurn >= base.Amount" in src else {})}
    body = method_bodies(src, "ModifyCardPlayResultLocation")
    t = re.search(r"card\.Type != CardType\.(\w+)", body)
    if t and "PileType.Exhaust" in body:
        out["exhaustsType"] = t.group(1)
    if re.search(r"participants\.Contains\(base\.Owner\)\)\s*\{?\s*await PowerCmd\.Remove\(this\)",
                 method_bodies(src, "AfterSideTurnEnd")):
        out["lasts"] = "turn"
    body = method_bodies(src, "BeforeSideTurnStart")
    t = re.search(r"PileType\.Discard\.GetPile[^;]*;[^;]*c\.Type == CardType\.(\w+)", body)
    if t and "PileType.Hand" in body:
        out["fromDiscard"] = t.group(1)
    t = re.search(r"card\.Tags\.Contains\(CardTag\.(\w+)\)", method_bodies(src, "AfterCardDrawnEarly"))
    if t and "CardCmd.AutoPlay" in src:
        out["playsDrawn"] = t.group(1)
    t = re.search(r"c\.Type == CardType\.(\w+)", method_bodies(src, "AfterAutoPostPlayPhaseEntered"))
    if t and "PileType.Hand" in src and "CardCmd.AutoPlay" in src:
        out["endPlays"] = t.group(1)
    t = re.search(r"attacksPlayedThisTurn == (\d+)", src)
    if t and "CreateClone" in src:
        out["copiesNth"] = int(t.group(1))
    body = method_bodies(src, "ModifyDamageMultiplicative")
    if "HasPower<WeakPower>" in body and "base.Amount / 100m" in body:
        out["weakBonus"] = True
    t = re.search(r"return (\d+)m;\s*$", body)
    if t and int(t.group(1)) > 1 and "IsPoweredAttack" in body:
        out["dmgMult"] = int(t.group(1))
    if "Math.Pow(2.0, base.Amount)" in method_bodies(src, "ModifyBlockMultiplicative"):
        out["blockDoubles"] = True
    if re.search(r"if \(base\.Owner != creature\)\s*\{\s*return true;\s*\}\s*return false;",
                 method_bodies(src, "ShouldClearBlock")):
        out["keepsBlock"] = True
    if re.search(r"if \(player != base\.Owner\.Player\)\s*\{\s*return true;\s*\}\s*return false;",
                 method_bodies(src, "ShouldFlush")):
        out["keepsHand"] = True
    body = method_bodies(src, "BeforeHandDraw")
    t = re.search(r"(\w+)\.CreateInHand\(base\.Owner\.Player, base\.Amount", body) \
        or re.search(r"for \(int i = 0; i < base\.Amount; i\+\+\)\s*\{[^}]*CreateCard<(\w+)>\(base\.Owner\.Player\)"
                     r"[^}]*PileType\.Hand", body)
    if t:
        out["turnMakes"] = game_id(t.group(1))  # Infinite Blades; Sentry Mode's Sweeping Gaze
    if "CreateClone()" in body and "PileType.Hand" in body:
        out["clonesNextTurn"] = True
    body = method_bodies(src, "ModifyDamageAdditive")
    t = re.search(r"Tags\.Contains\(CardTag\.(\w+)\)", body)
    if t and re.search(r"if \(num > 0\)\s*\{\s*return 0m;", body):
        out["firstTagBonus"] = t.group(1)
    body = method_bodies(src, "AfterCardEnteredCombat")
    t = re.search(r"Tags\.Contains\(CardTag\.(\w+)\)", body)
    if t and "CardKeyword.Retain" in body:
        out["retainsTag"] = t.group(1)
    if "Applier" in method_bodies(src, "BeforeCardPlayed") \
            and re.search(r"CreatureCmd\.Damage\(\w+, base\.Owner,", method_bodies(src, "AfterCardPlayed")):
        out["hurtsOnPlay"] = True
    if re.search(r"return 0m;\s*$", method_bodies(src, "ModifyHpLostAfterOstyLate")) \
            and "PowerCmd.Decrement(this)" in method_bodies(src, "AfterModifyingHpLostAfterOsty"):
        out["buffer"] = True
    body = method_bodies(src, "ModifyDamageAdditive")
    if "EnergySpent != 0" in body and "CostsX" in body and "return base.Amount;" in body:
        out["zeroCostBonus"] = True
    body = method_bodies(src, "ModifyCardPlayResultLocation")
    t = re.search(r"card\.Type != CardType\.(\w+)", body)
    if t and "EnergyValue > 0" in body and "location.pileType = PileType.Hand;" in body:
        out["returnsZeroCost"] = t.group(1)
    body = method_bodies(src, "BeforeHandDraw")
    t = re.search(r"CardPool[^;]*c\.Type == CardType\.(\w+)", body)
    if t and "PileType.Hand" in body and "base.Amount" in body:
        out["turnMakesRandom"] = t.group(1)
    elif "CardPool" in body and "CardKeyword.Ethereal" in body and "base.Amount" in body:
        out["turnMakesRandom"] = "Any"  # Call of the Void: any card, made Ethereal
        out["turnMakesEthereal"] = True
    if re.search(r"PowerCmd\.Apply<DoomPower>\(\w+, base\.Owner,", method_bodies(src, "AfterCardPlayed")):
        out["doomsOnPlay"] = True  # Oblivion: Doom on its enemy for each card you play
    body = method_bodies(src, "AfterDamageGiven")
    if "dealer == base.Owner" in body and re.search(r"PowerCmd\.Apply<DoomPower>\([^;]*TotalDamage \* base\.Amount", body):
        out["doomPerDamage"] = True  # Reaper Form, Osty's hits too
    if "Monster is Osty" in body and "OstyCmd.Summon(" in body:
        out["summonOnOstyHit"] = True  # Sic 'Em
    body = method_bodies(src, "AfterCurrentHpChanged")
    if "Monster is Osty" in body and "HittableEnemies" in body and "CreatureCmd.Damage(" in body:
        out["ostyLossHits"] = True  # Necro Mastery
    if "Monster is Osty" in method_bodies(src, "ModifyDamageAdditive"):
        out["ostyBonus"] = True  # Calcify
    body = method_bodies(src, "ModifyDamageMultiplicative")
    if "CardPlaysStarted" in body and "CardType.Attack" in body and "base.Amount / 100m" in body:
        out["firstAttackBonus"] = True  # Lethality: Amount % more on the turn's first Attack
    t = re.search(r"!\(cardSource is (\w+)\)\)\s*\{\s*return 1m;\s*\}\s*return base\.Amount;", body)
    if t:
        out["cardMult"] = game_id(t.group(1))  # Hang: its stack times on Hang
    body = method_bodies(src, "TryModifyEnergyCostInCombat")
    if "originalCost + (decimal)base.Amount" in body and "Affliction" not in body:
        out["costUp"] = True  # Borrowed Time
    body = method_bodies(src, "AfterCardPlayed")
    t = re.search(r"cardPlay\.Card\.Type != CardType\.(\w+)", body)
    k = re.search(r"CardCmd\.ApplyKeyword\(cardPlay\.Card, CardKeyword\.(\w+)\)", body)
    if t and k:
        out["keywordOnPlay"] = {"type": t.group(1), "keyword": k.group(1)}
    if "amountsForPlayedCards.Remove" in body and "PowerCmd.Apply<StrengthPower>" in body \
            and "StrengthApplied" in method_bodies(src, "AfterSideTurnEnd"):
        out["strPerPlay"] = True  # Monologue: Strength per card played, gone at the turn's end
    if re.search(r"AttacksPlayedThisTurn >= (\d+)", body) and "DrawCardsNextTurnPower" in body:
        out["drawAfterAttacks"] = int(re.search(r"AttacksPlayedThisTurn >= (\d+)", body).group(1))  # Pale Blue Dot
    t = re.search(r"energySpent / (\d+)", method_bodies(src, "AfterEnergySpent"))
    if t and "GainEnergy(base.Amount" in src:
        out["energyPer"] = int(t.group(1))  # Orbit: its stack of energy per 4 spent
    if "sovereignBlade.BaseReplayCount" in src:
        out["bladeReplays"] = True  # Sword Sage
    body = method_bodies(src, "ModifyDamageMultiplicative")
    if "cardSource is SovereignBlade" in body and "target != base.Owner" in body and "return 2m;" in body:
        out["bladeMultFoe"] = 2  # Conqueror, on the enemy
    t = re.search(r"PowerCmd\.Apply<(\w+StrengthDown)Power>\(\w+, target, base\.Amount", method_bodies(src, "AfterDamageGiven"))
    if t:
        out["hitStrDown"] = True  # Monarch's Gaze: its stack of Strength off each enemy you hit, for a turn
    body = method_bodies(src, "AfterDamageReceived")
    if re.search(r"CreatureCmd\.Damage\(\w+, dealer, result\.BlockedDamage", body):
        out["reflect"] = True  # Reflect: what you block of a hit goes back at the attacker
    body = method_bodies(src, "BeforeHandDraw")
    if "ColorlessCardPool" in body and "base.Amount" in body and "PileType.Hand" in body:
        out["turnMakesRandom"] = "Colorless"  # Spectrum Shift
    if re.search(r"FromCombatPile\([^;]*PileType\.Draw[^;]*base\.Amount", body) and "PowerCmd.Remove(this)" in body:
        out["handDrawOnce"] = True  # Foregone Conclusion: its stack more, once
    body = method_bodies(src, "ModifyBlockAdditive")
    t = re.search(r"!cardSource\.Tags\.Contains\(CardTag\.(\w+)\)", body)
    if t and "return base.Amount;" in body:
        out["tagBlock"] = t.group(1)  # Fasten: its stack more block on Defends
    if re.search(r"cardSource == null\)\s*\{\s*return 1m;\s*\}\s*return 0m;",
                 method_bodies(src, "ModifyBlockMultiplicative")):
        out["noCardBlock"] = True  # No Block (Panic Button): cards give no block
    if re.search(r"AutoPlayFromDrawPile\([^;]*base\.Amount, CardPilePosition\.Top",
                 method_bodies(src, "AfterAutoPrePlayPhaseEntered")):
        out["turnPlaysTop"] = True  # Mayhem: its stack off the top of the draw pile, played each turn
    body = method_bodies(src, "ModifyCardPlayResultLocation")
    if "location.pileType = PileType.Draw" in body and "CardPilePosition.Top" in body and ">= base.Amount" in body:
        out["topsFirst"] = True  # Nostalgia: the turn's first Attacks/Skills go back on top of the draw pile
    body = method_bodies(src, "AfterPlayerTurnStart")
    t = re.search(r"new DamageVar\((\d+)m", src)
    if t and "SetAmount(base.Amount + base.DynamicVars.Damage" in body:
        out["turnAoeGrows"] = int(t.group(1))  # Rolling Boulder: its stack at every foe each turn, then that much more
    if "CardSelectCmd.FromHand" in body and "TransformToRandom" in body:
        out["turnTransforms"] = True  # Entropy: its stack of cards in hand, transformed each turn
    body = method_bodies(src, "BeforeSideTurnEnd")
    if "PowerCmd.Decrement(this)" in body and "base.DynamicVars.Damage" in body and "PowerCmd.Remove(this)" in body:
        out["bomb"] = True  # The Bomb: counts its stack down, then its damage at every foe
    if re.search(r"FromCombatPile\([^;]*PileType\.Draw[^;]*base\.Amount", method_bodies(src, "AfterShuffle")):
        out["shuffleFetch"] = True  # Stratagem: its stack picked out of the draw pile on each shuffle
    t = re.search(r"CardPool[^;]*c\.Type == CardType\.(\w+)[^;]*base\.Amount", method_bodies(src, "AfterCardPlayed"))
    if t and f"cardPlay.Card.Type != CardType.{t.group(1)}" in method_bodies(src, "BeforeCardPlayed"):
        out["attackMakesRandom"] = t.group(1)  # Calamity: a random Attack into hand per Attack played
    body = method_bodies(src, "AfterDamageReceived")
    if "UnblockedDamage > 0" in body and "CreatureCmd.Kill(base.Owner)" in body:
        out["gambit"] = True  # The Gambit: unblocked attack damage kills you
    return out


# The condition on a card's draw or energy -> what the sim checks
DRAW_IFS = (
    (r"!PileType\.Hand\.GetPile\(base\.Owner\)\.Cards\.Any\(\(CardModel c\) => c\.Type == CardType\.Attack\)",
     "noAttackInHand"),                     # Impatience
    (r"^IsOnlyCardInHand$", "onlyCardInHand"),  # Restlessness
    (r"^CanDrawCard$", "fewPlays"),           # FTL: under PlayMax cards played this turn
    (r"^!HasBeenPlayedThisTurn$", "firstPlay"),  # Fetch
)


def card_draw(src: str, play: str) -> dict:
    """How a card draws, past its Cards var: `drawN` when the count is
    something else (a literal, another var, "fullHand"), `drawWhile` a card
    type that keeps it drawing (Pillage: while it draws Attacks), `drawIf` /
    `energyIf` a condition (DRAW_IFS), and what happens to the cards drawn:
    `drawnRetain` (Expertise), `drawnDiscard: costly` (Scrape discards the
    ones that cost energy), `blockIfDrawn` a type (Escape Plan: block if it
    drew a Skill)."""
    out = {}
    i = play.find("CardPileCmd.Draw(")
    if i < 0:
        return out
    n = draw_count(play, i)
    if n != "Cards" and n is not None:
        out["drawN"] = n
    m = re.search(r"while \(\w+ != null && \w+\.Type == CardType\.(\w+)", play)
    if m:
        out["drawWhile"] = m.group(1)
    for m in re.finditer(r"if \((.+?)\)\s*\{", play):
        block = braced(play, m.end() - 1)
        for pattern, cond in DRAW_IFS:
            if re.search(pattern, m.group(1)):
                if "CardPileCmd.Draw(" in block:
                    out["drawIf"] = cond
                if "GainEnergy(" in block:
                    out["energyIf"] = cond
    if "ApplySingleTurnRetain" in play:
        out["drawnRetain"] = True
    if re.search(r"CardPileCmd\.Draw\([^;]*\)\)\.Where\([^;]*EnergyCost[^;]*!= 0", play):
        out["drawnDiscard"] = "costly"
    m = re.search(r"CardPileCmd\.Draw\([^;]*\)\)\.FirstOrDefault\(\);\s*if \(\w+ != null && \w+\.Type == CardType\.(\w+)\)", play)
    if m:
        out["blockIfDrawn"] = m.group(1)
    return out


def exhausts(src: str, play: str) -> str | None:
    """Which other cards a card exhausts: "statuses" (Flak Cannon, every
    Status you own), "nonAttacks" in hand (Second Wind), "randomAttack" in
    hand (Thrash), "drawPile" (Cleanse picks one), "hand" (Fiend Fire,
    Stoke), "upTo" its Cards var of your pick (Purity), "pick" one
    (Burning Pact), "random" one in hand (Cinder)."""
    if "CardCmd.Exhaust" not in play:
        return None
    for pattern, how in (
        (r"c\.Type == CardType\.Status", "statuses"),
        (r"c\.Type != CardType\.Attack", "nonAttacks"),
        (r"NextItem\([^;]*c\.Type == CardType\.Attack", "randomAttack"),
        (r"PileType\.Draw\.GetPile", "drawPile"),
        (r"PileType\.Hand\.GetPile\(base\.Owner\)\.Cards\.ToList\(\);\s*int \w+ = list\.Count", "hand"),
        (r"CardSelectorPrefs\([\w.]+, 0, base\.DynamicVars", "upTo"),
        (r"NextItem\(", "random"),
        (r"CardSelectCmd\.FromHand\(", "pick"),
    ):
        if re.search(pattern, src):
            return how
    return None


def add_economy(entry: dict, src: str, power: bool = False):
    """The draw-side fields powers and relics share: triggers, a card given
    up at turn start, and draws blocked outside the hand draw."""
    trig = triggers(src, power)
    if trig:
        entry["triggers"] = trig
    choice = turn_start_choice(src)
    if choice:
        entry["atStart"] = choice
        gate = turn_gate(method_bodies(src, "AfterPlayerTurnStart"))
        if gate:
            entry["atStartGate"] = gate  # Gambling Chip: turn 1 only
    if blocks_draws(src):
        entry["noOtherDraws"] = True


# ---------------------------------------------------------------------------
# Monsters

def resolve_values(src: str) -> dict[str, tuple]:
    """Identifier -> (base, raised) for the monster's int properties and
    constants: `X => AscensionHelper.GetValueIfAscension(Level, raised, base)`,
    `X => 5`, `const int _x = 2`. `raised` is None when no ascension changes it."""
    vals = {}
    for name, level, raised, base in re.findall(
            r"int (\w+) => AscensionHelper\.GetValueIfAscension\(AscensionLevel\.(\w+), (-?\d+), (-?\d+)\)", src):
        vals.setdefault(name, (int(base), int(raised), level))
    for name, v in re.findall(r"int (\w+) => (-?\d+);", src):
        vals.setdefault(name, (int(v), None, None))
    for name, v in re.findall(r"const int (\w+) = (-?\d+);", src):
        vals.setdefault(name, (int(v), None, None))
    return vals


def value(token: str, vals: dict) -> tuple:
    token = re.sub(r"^\(\)\s*=>\s*", "", token.strip())
    if re.fullmatch(r"-?\d+", token):
        return (int(token), None, None)
    # Attacks that ramp keep the running figure in CurrentX, seeded from BaseX.
    return vals.get(token) or vals.get(re.sub(r"^Current", "Base", token), (None, None, None))


INTENT = re.compile(r"new (\w+)Intent\(([^()]*(?:\([^()]*\)[^()]*)*)\)")


def scan_monster(src: str, parent: str = "") -> dict:
    """`parent` is the base class's code when the monster shares one (the
    three Decimillipede segments): HP and moves it doesn't define itself
    come from there."""
    vals = resolve_values(src + "\n" + parent)
    mon = {}
    for key, prop in (("hpMin", "MinInitialHp"), ("hpMax", "MaxInitialHp")):
        m = re.search(rf"{prop} => (.+?);", src) or re.search(rf"{prop} => (.+?);", parent)
        if m and m.group(1) == "MinInitialHp":
            mon[key] = mon.get("hpMin")
        elif m:
            asc = re.search(r"GetValueIfAscension\(AscensionLevel\.\w+, (\d+), (\d+)\)", m.group(1))
            mon[key] = [int(asc.group(2)), int(asc.group(1))] if asc else (
                [int(m.group(1))] * 2 if m.group(1).isdigit() else None)
    moves = []
    move_src = src if "new MoveState(" in src else parent
    for m in re.finditer(r"new MoveState\(\"(\w+)\",\s*\w+,(.*?)\);", move_src):
        intents = []
        for kind, args in INTENT.findall(m.group(2)):
            intent = {"type": kind}
            if kind in ("SingleAttack", "MultiAttack", "DeathBlow"):
                parts = [a.strip() for a in re.split(r",(?![^()]*\))", args) if a.strip()]
                dmg = value(parts[0], vals) if parts else (None, None, None)
                hits = value(parts[1], vals) if len(parts) > 1 else (1, None, None)
                intent["dmg"] = dmg[0]
                if dmg[1] is not None:
                    intent["dmgAsc"] = dmg[1]
                intent["hits"] = hits[0]
                if hits[1] is not None:
                    intent["hitsAsc"] = hits[1]
            intents.append(intent)
        moves.append({"id": m.group(1), "intents": intents})
    mon["moves"] = moves
    return mon


# ---------------------------------------------------------------------------

def main():
    if not MODELS.exists():
        raise SystemExit(f"decompiled game code not found at {MODELS}")
    card_data = json.loads((ROOT / "card_data.json").read_text(encoding="utf-8"))
    relic_data = json.loads((ROOT / "relic_data.json").read_text(encoding="utf-8"))

    powers = {}
    for f in sorted((MODELS / "Powers").glob("*Power.cs")):
        src = read(f)
        # A power that applies another produces it (Noxious Fumes -> Poison).
        made = {f"power:{p}" for p in applied_powers(src)} - {f"power:{f.stem[:-len('Power')]}"}
        entry = {"consumes": sorted(consumed_keys(src)), "produces": sorted(produced_keys(src) | made)}
        mods = damage_mods(src)
        if mods:
            entry["mods"] = mods
        turns = turn_effects(src, power=True)
        if turns:
            entry["turnEffects"] = turns
        # Plating loses a stack each turn after the first (Clarity: its turns).
        if "PowerCmd.Decrement(this)" in method_bodies(src, "AfterSideTurnStart"):
            entry["decays"] = True
        # Double Damage: a stack lost as its owner's turn ends.
        if re.search(r"participants\.Contains\(base\.Owner\)\)\s*\{?\s*await PowerCmd\.Decrement\(this\)",
                     method_bodies(src, "AfterSideTurnEnd")):
            entry["endDecays"] = True
        draw_mod = hand_draw(src)
        if draw_mod is not None:
            # Draw Cards Next Turn: gone once it has given its draw.
            if "PowerCmd.Remove(this)" in method_bodies(src, "AfterSideTurnStart"):
                draw_mod["once"] = True
            entry["handDraw"] = draw_mod
        if "override decimal ModifyMaxEnergy" in src:
            # Demesne: its stack more every turn; Waste Away: that much less.
            entry["maxEnergy"] = -1 if "amount - " in method_bodies(src, "ModifyMaxEnergy") else 1
        add_economy(entry, src, power=True)
        hooks = orb_hooks(src)
        if hooks:
            entry["orbHooks"] = hooks
            # Coolant's block and Hailstorm's hit hang on the orbs held, not
            # every turn as turn_effects reads them.
            if any("blockPerUnique" in h or "ifFrost" in h for h in hooks):
                entry.pop("turnEffects", None)
        parent = re.search(rf"class {f.stem} : (\w+)", src)
        entry.update(power_rules(src, parent.group(1) if parent else ""))
        powers[f.stem[:-len("Power")]] = entry
    # Accelerant: Poison triggers once more per stack the poisoner has.
    for p in set(re.findall(r"GetPowerAmount<(\w+)Power>", read(MODELS / "Powers" / "PoisonPower.cs"))) & set(powers):
        powers[p]["poisonTicks"] = True
    orbs ={f.stem[:-len("Orb")]: sorted(consumed_keys(read(f)))
            for f in (MODELS / "Orbs").glob("*Orb.cs")}

    def link(src: str, extra_consumes=(), own_powers=()) -> tuple[list, list]:
        cons, prod = consumed_keys(src) | set(extra_consumes), produced_keys(src)
        prod |= {f"power:{p}" for p in applied_powers(src)}
        # A power you give yourself brings what it reacts to: Barricade ->
        # BarricadePower, which keeps block ("block"); Accuracy -> "shiv".
        for p in own_powers:
            cons |= set(powers.get(p, {}).get("consumes", []))
            prod |= set(powers.get(p, {}).get("produces", []))
        return sorted(cons), sorted(prod)

    cards, missing = {}, []
    for f in sorted((MODELS / "Cards").glob("*.cs")):
        cid = f"CARD.{game_id(f.stem)}"
        if cid not in card_data:
            missing.append(cid)
            continue
        src = read(f)
        card = scan_card(src)
        own = [p for p, side in card.get("applies", {}).items() if side != "enemy"]
        extra = [k for o in card.get("orbs", []) for k in orbs.get(o, [])]
        card["consumes"], card["produces"] = link(src, extra, own)
        cards[cid] = card
        # Fan of Knives: a power that turns a tagged card (Shiv) on every enemy.
        p = re.search(r"HasPower<(\w+)Power>\(\)", src)
        if p and p.group(1) in powers and "TargetingAllOpponents" in src and card.get("tags"):
            powers[p.group(1)]["aoeTag"] = card["tags"][0]

    relics = {}
    for f in sorted((MODELS / "Relics").glob("*.cs")):
        rid = f"RELIC.{game_id(f.stem)}"
        if rid not in relic_data:
            missing.append(rid)
            continue
        src = read(f)
        own = [p for p, side in applied_powers(src).items() if side != "enemy"]
        cons, prod = link(src, own_powers=own)
        relic = {"consumes": cons, "produces": prod}
        mods = damage_mods(src)
        if mods:
            relic["mods"] = mods
        turns = turn_effects(src)
        if turns:
            relic["turnEffects"] = turns
        # Turn economy; the amounts are the relic's Energy / Cards vars, and
        # maxEnergy holds the turns it applies on (Pael's Flesh: from turn 3).
        if "override decimal ModifyMaxEnergy" in src:
            relic["maxEnergy"] = turn_gate(method_bodies(src, "ModifyMaxEnergy"))
        draw_mod = hand_draw(src)
        if draw_mod is not None:
            relic["handDraw"] = draw_mod
        add_economy(relic, src)
        hooks = orb_hooks(src)
        if hooks:
            relic["orbHooks"] = hooks
        relic.update(orb_mods(src))
        relic.update(regent_relic(src))
        if "tagMult" in relic:
            relic.pop("mods", None)  # Vitruvian Minion's x2 is for Minion cards only
        relics[rid] = relic

    monsters = {}
    for f in sorted((MODELS / "Monsters").glob("*.cs")):
        src = read(f)
        base = re.search(rf"class {f.stem} : (\w+)", src)
        parent_file = MODELS / "Monsters" / f"{base.group(1)}.cs" if base else None
        if re.search(rf"abstract class {f.stem}\b", src):
            continue
        parent = read(parent_file) if parent_file and parent_file.exists() else ""
        monsters[f"MONSTER.{game_id(f.stem)}"] = scan_monster(src, parent)
    encounters = {}
    for f in sorted((MODELS / "Encounters").glob("*.cs")):
        mons = sorted({f"MONSTER.{game_id(m)}" for m in re.findall(r"Monster<(\w+)>", read(f))})
        if mons:
            encounters[f"ENCOUNTER.{game_id(f.stem)}"] = {"monsters": mons}

    out = {"cards": cards, "relics": relics, "powers": powers, "orbs": orbs,
           "monsters": monsters, "encounters": encounters}
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{OUT.name}: {len(cards)} cards, {len(relics)} relics, {len(powers)} powers, "
          f"{len(monsters)} monsters, {len(encounters)} encounters")
    unmatched_cards = sorted(set(card_data) - set(cards))
    if unmatched_cards:
        print(f"  {len(unmatched_cards)} cards in card_data.json with no code file matched:",
              ", ".join(unmatched_cards[:12]))
    if missing:
        print(f"  {len(missing)} code files with no data entry (deprecated/test models?):",
              ", ".join(missing[:12]))


if __name__ == "__main__":
    main()
