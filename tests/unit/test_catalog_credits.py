import unittest
from linkmusicbot.models import Song
from linkmusicbot.services.base import same_recording


class CatalogCreditTests(unittest.TestCase):
    pairs = [
        ('See You Again (feat. Charlie Puth)', 'Wiz Khalifa', 'See You Again (из фильма «Форсаж 7»)', 'Wiz Khalifa & Charlie Puth'),
        ('Sunflower - Spider-Man: Into the Spider-Verse', 'Post Malone & Swae Lee', 'Sunflower (из мультфильма «Человек-паук: Через вселенные»)', 'Post Malone & Swae Lee'),
        ('Left and Right (Feat. Jung Kook of BTS)', 'Charlie Puth & Jung Kook & BTS', 'Left and Right', 'Charlie Puth & Jung Kook'),
        ('Left and Right (Feat. Jung Kook of BTS)', 'Charlie Puth & Jung Kook & BTS', 'Left And Right (feat. Jung Kook of BTS)', 'Charlie Puth'),
        ('What Could Have Been - from the series Arcane League of Legends', 'Sting & Ray Chen', 'What Could Have Been (from the series Arcane League of Legends)', 'Sting & 陳銳'),
    ]

    def test_verified_catalog_equivalents_work_both_directions(self):
        for title, artist, other_title, other_artist in self.pairs:
            with self.subTest(title=title, artist=other_artist):
                self.assertTrue(same_recording(Song(title, artist, ''), other_title, other_artist))
                self.assertTrue(same_recording(Song(other_title, other_artist, ''), title, artist))

    def test_versions_and_different_performers_are_not_equivalent(self):
        for title, artist, other_title, other_artist in self.pairs:
            for version in ['Remix', 'Live', 'Instrumental', 'Acoustic', 'Opening Title Version', 'Sped Up']:
                with self.subTest(title=title, version=version):
                    self.assertFalse(same_recording(Song(title, artist, ''), other_title+' ('+version+')', other_artist))
            self.assertFalse(same_recording(Song(title, artist, ''), other_title, 'Unrelated Cover Artist'))

    def test_affiliation_exception_does_not_remove_other_guest(self):
        self.assertFalse(same_recording(Song('Left and Right', 'Charlie Puth & Jung Kook', ''),
                                        'Left and Right', 'Charlie Puth & Jung Kook & Other Singer'))
        self.assertFalse(same_recording(Song('Other Song', 'Charlie Puth & Jung Kook & BTS', ''),
                                        'Other Song', 'Charlie Puth & Jung Kook'))
