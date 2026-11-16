# Synergy coverage audit

Reviewed November 15, 2026 against the local card/relic exports and existing
power export. Fool mechanics were also checked in the local decompiled game:
AimPower, StretchPower, MelodyCmd, ArrowCmd, ChoKi, EpicRetrieval, and Florescence.

Archetype tags and synergy links are separate. A tag counts deck ingredients;
a link requires a producer and a different payoff in the actual deck/relic set.
The UI still excludes links consisting entirely of starter cards.

| Character | Archetypes checked | Representative links |
|---|---|---|
| Ironclad | Strength, Exhaust, Block, Self-damage, Vulnerable | Inflame → Conflagration; Fiend Fire → Ashen Strike; Impervious → Body Slam/Barricade; Bloodletting → Rupture; Bash → Bully |
| Silent | Shiv, Poison, Discard | Blade Dance → Accuracy; Concoct → Accelerant; Acrobatics → Abrasive |
| Defect | Lightning, Frost, Dark, Zero-cost, Status | Ball Lightning → Thunder; Glacier → Hailstorm/Capacitor; Shadow Shield → Darkness; Claw → All for One/Feral; Turbo → Iteration |
| Necrobinder | Doom, Osty, Souls, Ethereal | Oblivion → Time's Up; Bodyguard → Unleash; Capture Spirit → Soul Storm; Ethereal cards → Veilpiercer |
| Regent | Stars, Forge, Creation | Glow → Radiate; star-cost cards → Crescent Spear; Furnace → Sovereign Blade; Crash Landing → Pillar of Creation |
| Fool | Shots, Impale, Melodies, Sadness, Stretch | Song Bow → Heavy Shot; Shots → Nail/Epic Retrieval; Wrest → Twine; Quiver → Shots; Wah/Cho/Ki → Melody rewards; Jest → Anguish; Bizarre Lamp → Ecstasy; Stretch → Block cards |

Fool links distinguish Aim from shooting triggers, Impale from Dislodge, and
extra/returned Arrows from shooting. Melody acquisition is separate from effects
that target named song cards: Cho Chorus takes Wah/Ki cards, not plain Cho cards.
Sadness transformation payoffs do not count as Sadness producers. Whistling
Arrows reacts to shooting but does not itself Shoot. Joy is a generic energy/draw
reward; no unsupported Joy-specific payoff is invented.

Block production links only to explicit Block scaling, retention, or triggered
payoffs. Generic Block-to-Block links remain excluded. Creation links require an
explicit creation payoff. Zero-cost attacks have their own key so Feral and One
for All do not take non-Attack cards as inputs.

Base and upgraded text/costs contribute to catalog relationships. The union is
kept in `synergy.cards`; `synergy.cardVariants` supplies the actual base/upgraded
rows used by each copy in a run. A base Zap, for example, no longer acquires an
All for One link just because upgraded Zap costs zero. These are potential
mechanic relationships, not per-play predictions.
Multiplayer support can be listed, but this does not model turn order, targets,
or whether allies actually used the benefit. No Fool combat simulation was added.

Validation: `python -m unittest discover -s tools -p test_synergy.py` checks
representative producer/payoff pairs across every listed archetype, plus false
producer exclusions. The built preview was loaded with Playwright without JS
errors; all 27 locally synced Fool runs produced valid displayed synergy groups
through the actual deck-link function. The report is in the ignored
`local_data/fool-synergy-check.json`.

## Precision pass: Ironclad, Silent, Necrobinder, Regent

Each character's core producer and payoff memberships was reviewed against the
current exported rules text, including shared relics. Ambiguous mechanics were
checked in the local decompiled code: CardCmd's combat transformation hook,
ArsenalPower, Largesse, OstyCmd, BoneShards, Squeeze, ShroudPower, DeathsDoor, and
NeurosurgePower. This is a precision audit, not a new set of speculative builds.

| Character | Kept together | Changes supported by the rules |
|---|---|---|
| Ironclad | Strength, Vulnerable, self-damage, general Exhaust rewards, general Block scaling | Enemy Strength loss and ally-only Strength no longer feed your attacks. Expect a Fight is not a Strength payoff. Card-only Block bonuses accept Block cards, not relic triggers or Plating powers. General Exhaust rewards accept self-Exhaust too; specific Skill/Attack targets require an effect that can exhaust that type. |
| Silent | Shiv, Poison, Discard | Well-Laid Plans and Runic Pyramid prevent discard and are not discard sources. Fan of Knives is a Shiv payoff as well as a generator. Keyword additions are not card creation. The actual Poison/discard/Shiv relationships do not warrant subdivisions. |
| Necrobinder | Souls, Ethereal, enemy Doom scaling | Osty health scaling, attack rewards, and Calcify's attack damage are distinct. Summon does not increase ordinary Osty Attack damage. Doom application triggers are separate from enemy Doom: Neurosurge can feed Shroud/Death's Door, but not Time's Up. Soulbound sends its generated Souls to an ally; it is not a supply of your own Souls. Sentry Mode supplies Ethereal Osty attacks through Sweeping Gaze. |
| Regent | Combat card creation, Colorless and Minion support | Star generation funds costs; paid cards trigger spending rewards; generation triggers Radiate/Black Hole. Black Hole itself generates no stars. Forge damage supports Blade damage upgrades; Parry's independent Block and Beat into Shape's earlier-hit reward are not Forge payoffs. Blade upgrades still link to the Blade when present. Retrievals, keyword changes, and pickup-only transformations do not count as combat creation. |

Shared corrections remove pickup-only HP-loss links, Ruined Helmet's false Block
link, Philosopher's Stone's false friendly Strength, and duplicate internal-power
labels. Largesse still counts as creating a card for its creator (confirmed in
code), but does not supply a Colorless card to that creator's Heirloom Hammer.
Random rolls, targets, timing, and combat-only state are not simulated.

Validation commands:

```
python -m unittest discover -s tools -p test_synergy.py
infra/.venv/Scripts/python tools/test_synergy_explorer.py
infra/.venv/Scripts/python tools/test_synergy_precision_browser.py
```

The first command covers positive pairs, known false pairs, independent upgrade
rows, and existing Fool/Defect behavior. The browser checks use the actual
rendered catalog and real runs for all four reviewed characters, including
negative pair checks and upgrade-only links. They cover 1920×1080 desktop and
the named iPhone 16 portrait/landscape presets in WebKit. Screenshots are saved
under `local_data/precision-<character>-<orientation>.png`.

The explorer uses one ordered vertical list on solid backgrounds. Desktop cards
use the same face assets and sizing as the final deck; Sources/Payoffs align to
consistent columns, with at most three payoffs per row and wrapping sources.
Mobile stacks Sources above Payoffs and uses the deck's three-column card grid.
Touch opens previews on tap; hover-capable devices also have hover/focus tips.
There is no horizontal card-strip scrolling or column reordering when a group
is opened or closed.
