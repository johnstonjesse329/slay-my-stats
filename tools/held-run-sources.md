# Held run content sources

Use this reference when an upload digest reports IDs missing from the site's game data. These observations do not make an ID core game content: modded runs stay held, and only IDs confirmed removed from the game belong in `retired_ids.json`.

| ID pattern or IDs | Source | Evidence and confidence |
| --- | --- | --- |
| `CARD.ALCHEMIST-` (including `DEFEND_ALCHEMIST`, `DISTILL`, `DOSE`, `JAB`, `QUENCH`, `STRIKE_ALCHEMIST`) | [The Alchemist character mod](https://alchemist.fyi/) | The mod's published card list matches the names. |
| `CARD.CHIIKAWAMOD-` (including `CHIIKAWA_DEFEND`, `CHIIKAWA_STRIKE`, `EI`, `SASUMATA`, `TOGETHER_WE_GO`, `USER_CARD049`) | Chiikawa character mod | The IDs use the mod's prefix; [community statistics](https://spire-codex.com/pol/cards/lift) list its character. |
| `CARD.WATCHER_CRESCENDO`, `CARD.WATCHER_DEFEND_P`, `CARD.WATCHER_ERUPTION_P` | Suspected Watcher mod | Exact source unverified; check the raw run or mod source before classifying. |

These IDs appeared in the 2026-11-14 digest. The digest shows at most 15 IDs, not necessarily the full set. The production raw uploads, counts and builds were not checked because the AWS login had expired. Co-op runs are checked for every player's content, including teammates'.

For the full list and counts, run `python tools/find_unknown_ids.py --bucket slay-my-stats-data` after authenticating. See the [held runs documentation](../README.md#held-runs) for the processing and rebuild policy.
