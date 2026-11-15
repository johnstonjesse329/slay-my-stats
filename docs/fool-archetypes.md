# Fool card archetypes

Compiled from the local card_data.json export, reviewed November 15, 2026.
These are mechanic-based deck tags, not established strategy or strength rankings.
The site tags a deck when it contains at least three non-starter cards in a group;
multiple copies count, and groups can overlap. Ancient and generated cards count
if present in the final deck, following the existing tagging rules.

| Tag | What it captures |
|---|---|
| Shots | Shooting, Aim, and Arrow support. |
| Impale | Impale bonuses and Dislodge effects. |
| Melodies | Wah/Cho/Ki cards and Melody payoffs. |
| Sadness | Sadness creation, scaling, and transformation into Joy. |
| Stretch | Stretch generation and preservation. |

Melodies includes cards named Wah, Cho, or Ki even when their printed text does
not mention a Melody. Generic utility such as Encore, Simpleton, and Timber does
not receive a tag. These groups describe deck ingredients; three support cards
alone do not establish that a strategy is effective. No separate payoff is required.

Implementation: tools/power_curve/archetypes.py; compiled by
build_site.py::build_archetypes. Text matching supports Fool before the power
export includes its mechanics; this does not add Fool mechanics to the simulator.

## Card lists

### Shots (30)

Archery, Arrow Stab, Blossom Shot, Blot out the Sky, Brace, Cho Firm, Cho Ready, Covering Fire, Dislike You, Divine Shot, Epic Retrieval, Florescence, Heavy Shot, Hobbling Shot, Honing, Locked In, Melodic Shot, Nock, Quick Shot, Quietus, Quiver, Rain Shot, Rapid Shot, Repeat Shot, Show Off, Sky Shot, The Shot, Trick Shot, Whistling Arrows, Yah!.

### Impale (11)

Bow Smack, Epic Retrieval, Explosive Arrows, Ki Hop, Nail, Recall, Serrated Arrows, Uproot, Wah Hammer, Wrest, Yah!.

### Melodies (30)

Cho Barbs, Cho Chorus, Cho Firm, Cho Ki, Cho Limbs, Cho Ready, Coda, Harmonic Shield, Ki Chant, Ki Hop, Ki Rest, Ki Verse, Ki Whip, Lost Lute, Lullaby, Melodic Shot, Motif, Rhythm Strike, Song Path, Steady Cadence, Tune, Violent Chord, Wah Blast, Wah Cho, Wah Cho Ki, Wah Hammer, Wah Ki, Wah Sweep, Wah Symphony, Wah Touch.

### Sadness (13)

All Is Well, Anguish, Brighten Up, Ecstasy, Ennui, Growth, Jest, Mourning Blow, Punch of Joy, Rummage, Self Deprecate, Sorrowful Strike, Vitriol.

### Stretch (8)

Blossom Shot, Bounce, Cho Ki, Deep Stretch, Enrapture, Growth, Hidden Roots, Yoga.

