"""Regression checks against the locally exported game catalog.

Run: python -m unittest discover -s tools -p test_synergy.py
"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_site


@unittest.skipUnless((ROOT / 'power_data.json').exists(), 'requires local game exports')
class SynergyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.links = build_site.build_synergy()

    def pair(self, maker, user, key):
        section = lambda cid: 'relics' if cid.startswith('RELIC.') else 'cards'
        self.assertIn(key, self.links[section(maker)][maker][0], maker)
        self.assertIn(key, self.links[section(user)][user][1], user)

    def test_fool_mechanics(self):
        for maker, user, key in [
            ('RELIC.SONG_BOW', 'CARD.HEAVY_SHOT', 'aim'),
            ('CARD.RAPID_SHOT', 'CARD.WHISTLING_ARROWS', 'shots'),
            ('CARD.QUICK_SHOT', 'CARD.NAIL', 'impale'),
            ('CARD.QUICK_SHOT', 'CARD.EPIC_RETRIEVAL', 'impale'),
            ('CARD.WREST', 'RELIC.TWINE', 'dislodge'),
            ('CARD.RECALL', 'CARD.YAH', 'dislodge'),
            ('CARD.QUIVER', 'CARD.QUICK_SHOT', 'arrows'),
            ('CARD.WAH_CHO_KI', 'CARD.MOTIF', 'melodies'),
            ('CARD.CHO_KI', 'CARD.SONG_PATH', 'cho melody'),
            ('CARD.CHO_KI', 'CARD.TUNE', 'ki melody'),
            ('CARD.WAH_TOUCH', 'CARD.VIOLENT_CHORD', 'wah melody'),
            ('CARD.WAH_TOUCH', 'CARD.CHO_CHORUS', 'wah cards'),
            ('CARD.KI_HOP', 'CARD.CHO_CHORUS', 'ki cards'),
            ('CARD.JEST', 'CARD.ANGUISH', 'sadness'),
            ('RELIC.BIZARRE_LAMP', 'CARD.ECSTASY', 'sadness'),
            ('CARD.RUMMAGE', 'RELIC.FERTILIZER', 'sadness'),
            ('RELIC.EXERCISE_MAT', 'CARD.CHO_KI', 'stretch'),
            ('CARD.BLOSSOM_SHOT', 'CARD.CHO_LIMBS', 'stretch'),
            ('CARD.ENRAPTURE', 'CARD.CHO_FIRM', 'stretch'),
        ]:
            with self.subTest(key=key, maker=maker):
                self.pair(maker, user, key)

    def test_other_character_archetypes(self):
        for maker, user, key in [
            ('CARD.INFLAME', 'CARD.SWORD_BOOMERANG', 'power:Strength'),
            ('CARD.INFLAME', 'CARD.CONFLAGRATION', 'power:Strength'),
            ('CARD.FIEND_FIRE', 'CARD.ASHEN_STRIKE', 'exhaust'),
            ('CARD.IMPERVIOUS', 'CARD.BODY_SLAM', 'block scaling'),
            ('CARD.IMPERVIOUS', 'CARD.BARRICADE', 'block scaling'),
            ('CARD.BLOODLETTING', 'CARD.RUPTURE', 'HP loss'),
            ('CARD.BASH', 'CARD.BULLY', 'power:Vulnerable'),
            ('CARD.BLADE_DANCE', 'CARD.ACCURACY', 'shiv'),
            ('CARD.CONCOCT', 'CARD.ACCELERANT', 'power:Poison'),
            ('CARD.ACROBATICS', 'CARD.ABRASIVE', 'discard'),
            ('CARD.BALL_LIGHTNING', 'CARD.THUNDER', 'lightning'),
            ('CARD.GLACIER', 'CARD.HAILSTORM', 'frost'),
            ('CARD.SHADOW_SHIELD', 'CARD.DARKNESS', 'dark'),
            ('CARD.CAPACITOR', 'CARD.GLACIER', 'frost slots'),
            ('RELIC.DATA_DISK', 'CARD.ZAP', 'lightning focus'),
            ('CARD.ZAP', 'CARD.DUALCAST', 'lightning evoke'),
            ('CARD.SHADOW_SHIELD', 'CARD.MULTI_CAST', 'dark evoke'),
            ('CARD.CLAW', 'CARD.ALL_FOR_ONE', 'zero-cost'),
            ('CARD.CLAW', 'CARD.FERAL', 'zero-cost attacks'),
            ('CARD.ADAPTIVE_STRIKE', 'CARD.ONE_FOR_ALL', 'zero-cost attacks'),
            ('CARD.TURBO', 'CARD.ITERATION', 'status'),
            ('CARD.OBLIVION', 'CARD.TIMES_UP', 'power:Doom'),
            ('CARD.BODYGUARD', 'CARD.UNLEASH', 'Osty health'),
            ('CARD.CAPTURE_SPIRIT', 'CARD.SOUL_STORM', 'souls'),
            ('CARD.DYING_STAR', 'CARD.VEILPIERCER', 'ethereal'),
            ('CARD.GLOW', 'CARD.RADIATE', 'star gain'),
            ('CARD.COMET', 'CARD.CRESCENT_SPEAR', 'star-cost cards'),
            ('CARD.FURNACE', 'CARD.SOVEREIGN_BLADE', 'forge'),
            ('CARD.CRASH_LANDING', 'CARD.PILLAR_OF_CREATION', 'creation'),
        ]:
            with self.subTest(key=key, maker=maker):
                self.pair(maker, user, key)

    def test_attacks_and_ethereal_exhaust(self):
        for maker, user, key in [
            ('CARD.BLADE_DANCE', 'CARD.FINISHER', 'attacks'),
            ('CARD.DAGGER_SPRAY', 'RELIC.KUNAI', 'attacks'),
            ('CARD.DEFILE', 'CARD.ASHEN_STRIKE', 'exhaust'),
        ]:
            with self.subTest(key=key, maker=maker):
                self.pair(maker, user, key)
        self.pair('RELIC.MUSIC_BOX', 'CARD.ASHEN_STRIKE', 'exhaust')
        self.assertIn('power:Strength', self.links['relics']['RELIC.MUSIC_BOX'][1])
        for relic in ('RELIC.ART_OF_WAR', 'RELIC.RIPPLE_BASIN'):
            self.assertNotIn('attacks', self.links['relics'].get(relic, [[], []])[1])

    def test_mentions_do_not_invent_production(self):
        for cid, key in [('CARD.ANGUISH', 'sadness'),
                         ('CARD.PUNCH_OF_JOY', 'sadness'),
                         ('CARD.ECSTASY', 'sadness'),
                         ('CARD.WHISTLING_ARROWS', 'shots'),
                         ('CARD.WHISTLING_ARROWS', 'impale'),
                         ('RELIC.TWINE', 'dislodge'),
                         ('CARD.YAH', 'dislodge')]:
            section = 'relics' if cid.startswith('RELIC.') else 'cards'
            with self.subTest(cid=cid):
                self.assertNotIn(key, self.links[section].get(cid, [[], []])[0])

    def test_statuses_and_curses_are_not_sources(self):
        cards = json.loads((ROOT / 'card_data.json').read_text(encoding='utf-8'))
        for cid, card in cards.items():
            if card.get('type') in ('Curse', 'Status'):
                self.assertNotIn(cid, self.links['cards'])

    def test_song_targets_are_distinct_from_melody_requirements(self):
        needs = self.links['cards']['CARD.CHO_CHORUS'][1]
        self.assertNotIn('cho cards', needs)
        self.assertNotIn('melodies', needs)

    def test_orb_links_are_specific(self):
        for section in ('cards', 'relics'):
            for made, need in self.links[section].values():
                self.assertNotIn('orbs', made + need)
                self.assertNotIn('plasma focus', made + need)
        ignition = self.links['cards'].get('CARD.IGNITION', [[], []])
        self.assertFalse(any(' evoke' in k or ' focus' in k or ' slots' in k for row in ignition for k in row))
        self.assertNotIn('lightning evoke', self.links['cards']['CARD.DARKNESS'][1])
        self.assertNotIn('dark focus', self.links['cards'].get('CARD.HYPERBEAM', [[], []])[0])

    def test_precision_pairs(self):
        pairs = [
            ('CARD.POKE', 'CARD.RATTLE', 'Osty attacks'),
            ('CARD.BONE_SHARDS', 'RELIC.BONE_FLUTE', 'Osty attacks'),
            ('CARD.CALCIFY', 'CARD.BONE_SHARDS', 'Osty damage'),
            ('CARD.BODYGUARD', 'CARD.PROTECTOR', 'Osty health'),
            ('CARD.BODYGUARD', 'CARD.SACRIFICE', 'Osty health'),
            ('CARD.SENTRY_MODE', 'CARD.SPIRIT_OF_ASH', 'ethereal'),
            ('CARD.NEUROSURGE', 'CARD.SHROUD', 'Doom application'),
            ('CARD.NEUROSURGE', 'CARD.DEATHS_DOOR', 'Doom application'),
            ('CARD.GLOW', 'CARD.BLACK_HOLE', 'star gain'),
            ('CARD.COMET', 'CARD.BLACK_HOLE', 'star spending'),
            ('CARD.COMET', 'CARD.CHILD_OF_THE_STARS', 'star spending'),
            ('CARD.COMET', 'RELIC.MINI_REGENT', 'star spending'),
            ('RELIC.DIVINE_RIGHT', 'CARD.COMET', 'stars'),
            ('CARD.LARGESSE', 'CARD.ARSENAL', 'creation'),
            ('CARD.BEGONE', 'CARD.ARSENAL', 'creation'),
            ('CARD.PARRY', 'CARD.SOVEREIGN_BLADE', 'blade upgrades'),
            ('CARD.FURNACE', 'CARD.SWORD_SAGE', 'forge'),
            ('CARD.IMPERVIOUS', 'CARD.UNMOVABLE', 'card Block'),
            ('CARD.IMPERVIOUS', 'CARD.DARK_EMBRACE', 'exhaust'),
            ('CARD.CORRUPTION', 'CARD.DRUM_OF_BATTLE', 'exhaust skills'),
            ('CARD.SECOND_WIND', 'RELIC.BURNING_STICKS', 'Skill Exhaust'),
            ('CARD.IMPERVIOUS', 'RELIC.BURNING_STICKS', 'Skill Exhaust'),
            ('CARD.TRUE_GRIT', 'CARD.HOWL_FROM_BEYOND', 'exhaust attacks'),
            ('CARD.BLADE_DANCE', 'CARD.FAN_OF_KNIVES', 'shiv'),
        ]
        for maker, user, key in pairs:
            with self.subTest(maker=maker, user=user, key=key):
                self.pair(maker, user, key)

    def test_false_pairs_removed(self):
        exclusions = {
            ('CARD.MALAISE', 0): ['power:Strength'],
            ('CARD.FRIENDSHIP', 0): ['power:Strength'],
            ('CARD.SHARED_FATE', 0): ['power:Strength'],
            ('CARD.BLAZE', 0): ['power:Strength'],
            ('RELIC.PHILOSOPHERS_STONE', 0): ['power:Strength'],
            ('RELIC.RUINED_HELMET', 0): ['power:Strength'],
            ('CARD.EXPECT_A_FIGHT', 1): ['power:Strength'],
            ('CARD.WELL_LAID_PLANS', 0): ['discard'],
            ('RELIC.RUNIC_PYRAMID', 0): ['discard'],
            ('CARD.NEUROSURGE', 0): ['power:Doom'],
            ('CARD.SOULBOUND', 0): ['souls'],
            ('CARD.HAND_TRICK', 0): ['creation'],
            ('CARD.SCULPTING_STRIKE', 0): ['creation'],
            ('CARD.TRANSFIGURE', 0): ['creation'],
            ('CARD.SNAP', 0): ['creation'],
            ('CARD.TUTOR', 0): ['creation'],
            ('RELIC.POWER_CELL', 0): ['creation'],
            ('RELIC.ARCHAIC_TOOTH', 0): ['creation'],
            ('RELIC.FRAGRANT_MUSHROOM', 0): ['HP loss'],
            ('CARD.LARGESSE', 0): ['colorless'],
            ('CARD.BLACK_HOLE', 0): ['stars', 'star gain', 'star spending'],
            ('CARD.PARRY', 1): ['forge'],
            ('CARD.BEAT_INTO_SHAPE', 1): ['forge'],
            ('CARD.SUMMON_FORTH', 1): ['forge'],
            ('CARD.SECOND_WIND', 0): ['exhaust attacks'],
            ('CARD.THRASH', 0): ['exhaust skills'],
            ('CARD.IMPERVIOUS', 0): ['exhaust skills'],
            ('CARD.EIDOLON', 1): ['exhaust'],
            ('RELIC.BURNING_STICKS', 1): ['exhaust'],
            ('RELIC.ANCHOR', 0): ['card Block'],
            ('RELIC.RUINED_HELMET', 1): ['block scaling', 'card Block'],
            ('CARD.RAGE', 0): ['card Block', 'stretch'],
        }
        for (cid, side), keys in exclusions.items():
            section = 'relics' if cid.startswith('RELIC.') else 'cards'
            for key in keys:
                with self.subTest(cid=cid, side=side, key=key):
                    self.assertNotIn(key, self.links[section].get(cid, [[], []])[side])

    def test_upgrade_only_links_are_not_on_base_cards(self):
        for cid in ('CARD.BODY_SLAM', 'CARD.ZAP', 'CARD.DUALCAST'):
            base, upgraded = self.links['cardVariants'][cid]
            self.assertNotIn('zero-cost', base[0], cid)
            self.assertIn('zero-cost', upgraded[0], cid)
        # Self-Exhaust disappears when these cards are upgraded.
        base, upgraded = self.links['cardVariants']['CARD.IGNITION']
        self.assertIn('exhaust', base[0])
        self.assertNotIn('exhaust', upgraded[0])


if __name__ == '__main__':
    unittest.main()
