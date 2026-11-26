"""Semantic checks over the heuristic power export, using current rules text.

These are mechanism distinctions, not a strength score. Keep Poison, Doom,
Souls, etc. together when the same resource genuinely connects both sides.
"""
import re

NUMBER = r"(?:\d+|X|\{\{[\w:]+\}\})"

# These reward playing Attacks. Rewards for not playing them (Art of War, Ripple Basin) stay out.
ATTACK_PAYOFFS = {
    "CARD.FINISHER", "CARD.STOMP", "CARD.JUGGLING", "CARD.RAGE", "CARD.CALAMITY",
    "RELIC.KUNAI", "RELIC.SHURIKEN", "RELIC.ORNAMENTAL_FAN", "RELIC.KUSARIGAMA", "RELIC.NUNCHAKU",
    "RELIC.PEN_NIB", "RELIC.DAUGHTER_OF_THE_WIND",
}


def refine(item_id, item, export, made, need):
    desc = item.get("desc", "")
    relic = item_id.startswith("RELIC.")
    # Pickup effects happen outside combat; later sentences may still be active.
    combat = re.sub(r"Upon pickup,[^.]*\.?", "", desc, flags=re.I) if relic else desc
    has = lambda pattern: bool(re.search(pattern.replace("NUMBER", NUMBER), combat, re.I))

    def role(key, source=None, payoff=None):
        if source is not None:
            (made.add if source else made.discard)(key)
        if payoff is not None:
            (need.add if payoff else need.discard)(key)

    # Power extraction also calls enemy debuffs and negative amounts "produces".
    self_strength = re.sub(r"(?:ALL )?enem(?:y|ies)[^.\n]*Strength[^.\n]*", "", combat, flags=re.I)
    strength_source = bool(re.search((r"\b(?:gain|with|have) NUMBER (?:additional )?Strength|gain Strength at Rest Sites").replace("NUMBER", NUMBER), self_strength, re.I))
    role("power:Strength", source=strength_source,
         payoff=has(r"for each Strength|you gain Strength each|gain Strength[^.]*double the amount|damage(?: to [^.\n]+)? (?:NUMBER times|twice)|hits (?:twice|NUMBER times|an additional time)"))
    # A multiline sentence can say "gain Strength ... double" in either order.
    if has(r"gain Strength[^.]*double the amount gained"):
        need.add("power:Strength")
    role("HP loss", source=has(r"\blose NUMBER HP"))
    doom_application = "power:Doom" in made
    doom_trigger = has(r"you applied Doom this turn|Whenever you apply Doom")
    role("Doom application", source=doom_application, payoff=doom_trigger)
    if doom_trigger:
        need.discard("power:Doom")
    if has(r"Doom to yourself"):
        made.discard("power:Doom")

    # Retaining a hand explicitly prevents the discard event.
    role("discard", source=has(r"(?<!no longer )\bdiscard (?:NUMBER|your Hand|any number|all cards)"))

    # A fresh card is different from a retrieved card or an added keyword.
    creation = has(r"\badds?\b(?! (?:Sly|Ethereal|Retain|Replay)\b)(?![^.\n]*\bfrom (?:your|the) (?:Draw|Discard) Pile)[^.\n]*(?:Hand|Hands|Draw Pile|Discard Pile)\b|fill your Hand with|\bTransform\b[^.]*\binto\b|(?:^|\n)Create (?:an? |NUMBER )")
    if has(r"choose[^.]*card in (?:your|their) (?:Draw|Discard) Pile to add"):
        creation = False
    role("creation", source=creation)
    # Count only specifically identified Attack output. A mixed or unspecified
    # card pool, and generators of Skills, Powers, or Statuses, are not evidence.
    attack_output = has(r"\b(?:add|create|fill|choose)\b[^.\n]*\b(?:random Attacks?|"
                        r"(?:Inky )?Shivs?|Sweeping Gaze|copy of the (?:first|third) Attack)\b")
    attack_copy = item.get("type") == "Attack" and has(r"\bcopy of this card\b")
    makes_attacks = (creation and (attack_output or attack_copy)) or has(r"\bcreate The Shot\b")
    if makes_attacks:
        need.add("power:Strength")
    role("attacks", source=not relic and (makes_attacks or item.get("type") == "Attack"),
         payoff=item_id in ATTACK_PAYOFFS)
    if relic and makes_attacks:
        made.add("attacks")
    if has(r"another player|their Hand"):
        # The creator may earn creation rewards (Largesse), but the Colorless
        # card is not available to that creator's Heirloom Hammer.
        made.discard("colorless")
    if item_id == "RELIC.OCARINA":
        need.difference_update({"wah cards", "cho cards", "ki cards"})
        made.add("melodies")
    if item_id == "CARD.SENTRY_MODE":
        made.add("ethereal")  # Sweeping Gaze is always Ethereal.

    # Generic block counts all actual self Block. Card-only multipliers do not
    # accept relic triggers, Plating powers, or Strength-doubling relics.
    ally_block = has(r"(?:give another player|another player[^.]*gains|allies gain)[^.]*Block") and not has(r"\byou gain NUMBER Block|^Gain NUMBER Block")
    block_source = "block scaling" in made and has(r"\bBlock\b|\bPlating\b") and not ally_block
    block_payoff = has(r"equal to your Block|Double your Block|Block is not removed|Whenever you gain Block|Double your Block gain")
    card_multiplier = has(r"gain Block from a card[^.]*double the amount")
    role("block scaling", source=block_source, payoff=block_payoff and not card_multiplier)
    direct_block = (not relic and item.get("type") != "Power" and not ally_block
                    and ("block" in export.get("does", []) or has(r"(?:^|\n)Gain NUMBER Block|Gain Block equal")))
    # A conditional future Blade power is not a printed Block card by itself.
    if not has(r"\bBlock\b"):
        direct_block = False
    role("card Block", source=direct_block, payoff=card_multiplier)
    role("stretch", payoff=direct_block or has(r"Regain any spent Stretch"))

    # Self-exhaust also feeds global Exhaust rewards. Individual targets need
    # an effect that can actually exhaust their card type.
    exhaust_other = "exhaust" in made
    exhaust_self = "Exhaust" in item.get("keywords", []) or has(r"(?:^|\n)Exhaust\.")
    # An Ethereal card Exhausts itself if it is still in hand at the end of the turn.
    ethereal = "ethereal" in made
    role("exhaust", source=exhaust_other or exhaust_self or ethereal)
    if has(r"this card is Exhausted|this is in your Exhaust Pile|ALL Ethereal cards in your Exhaust Pile"):
        need.discard("exhaust")
    selection = export.get("exhausts")
    any_type = selection in {"pick", "random", "hand", "upTo", "drawPile"} or has(r"Exhaust (?:your Hand|NUMBER card)|top card[^.]*Exhaust it")
    skill_target = any_type or selection == "nonAttacks" or has(r"play a Skill, Exhaust it")
    attack_target = any_type or selection == "randomAttack" or has(r"Exhaust a random Attack")
    skill_event = has(r"Exhaust a Skill")
    role("exhaust skills", source=skill_target, payoff=item.get("type") == "Skill" and has(r"this card is Exhausted"))
    role("Skill Exhaust", source=skill_target or ((exhaust_self or ethereal) and item.get("type") == "Skill"),
         payoff=skill_event)
    if skill_event:
        need.discard("exhaust")
    role("exhaust attacks", source=attack_target, payoff=item.get("type") == "Attack" and not exhaust_self and has(r"this is in your Exhaust Pile"))

    # Summon raises Osty's HP, not the damage of every ordinary Osty Attack.
    # Damage bonuses and attack-trigger rewards are separate directions.
    made.discard("osty")
    need.discard("osty")
    osty_attack = "OstyAttack" in export.get("tags", []) or has(r"Osty deals NUMBER damage") or item_id == "CARD.SENTRY_MODE"
    role("Osty health", source=has(r"\bSummon\b|Osty heals"), payoff=has(r"Osty's (?:current|Max) HP|If Osty is alive"))
    role("Osty attacks", source=osty_attack,
         payoff=has(r"Whenever Osty (?:attacks|hits)|Osty has attacked|each other time he has attacked|other Osty Attacks"))
    role("Osty damage", source=has(r"Osty's attacks deal NUMBER additional damage"), payoff=osty_attack)
    if item_id == "CARD.SOULBOUND":
        made.discard("souls")  # Its generated Souls go to the ally, not its owner.

    # Generation pays costs; paid cards trigger spending rewards. A spend
    # reward does not magically spend stars just because it names them.
    makes_stars = "stars" in made and not has(r"Whenever you spend or gain")
    star_cost = (item.get("stars", -1) > 0 or item.get("starsX", False)) and not relic
    spend_reward = has(r"Whenever you spend|for each [^.]*spent|For every [^.]*spent|first time you spend")
    gain_reward = has(r"Whenever you spend or gain|✦ gained")
    role("stars", source=makes_stars, payoff=star_cost)
    role("star spending", source=star_cost, payoff=spend_reward or has(r"Whenever you spend or gain"))
    role("star gain", source=makes_stars, payoff=gain_reward)

    # Forge's damage helps damage upgrades, not Parry's independent Block or
    # Beat into Shape's reward for earlier hits. Blade upgrades still have a
    # direct relationship with the actual Blade when it is present.
    role("forge", payoff=item_id in {"CARD.SOVEREIGN_BLADE", "CARD.CONQUEROR", "CARD.SEEKING_EDGE", "CARD.SWORD_SAGE", "CARD.HAMMER_TIME"})
    role("blade upgrades", source=item_id in {"CARD.PARRY", "CARD.CONQUEROR", "CARD.SEEKING_EDGE", "CARD.SWORD_SAGE"}, payoff=item_id == "CARD.SOVEREIGN_BLADE")
    # Internal powers describe these same mechanics; don't surface duplicates.
    for key in ("power:Parry", "power:SeekingEdge", "power:FanOfKnives", "power:Hibernate", "power:Confused"):
        made.discard(key)
        need.discard(key)
    if item_id == "CARD.FAN_OF_KNIVES":
        need.add("shiv")

    if relic and not combat.strip():
        made.clear()
        need.clear()
