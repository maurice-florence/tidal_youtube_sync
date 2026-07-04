import unittest
from unittest.mock import patch, MagicMock
from sync import get_youtube_tracks, sync_to_tidal
import tidalapi

class TestSync(unittest.TestCase):
    @patch('sync.YTMusic')
    def test_get_youtube_tracks_success(self, mock_ytmusic):
        mock_instance = MagicMock()
        mock_ytmusic.return_value = mock_instance
        
        mock_instance.get_playlist.return_value = {
            'tracks': [
                {
                    'title': 'Test Song',
                    'artists': [{'name': 'Test Artist'}]
                },
                {
                    'title': 'No Artist Song',
                    'artists': []
                }
            ]
        }
        
        tracks = get_youtube_tracks('fake_playlist_id')
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]['title'], 'Test Song')
        self.assertEqual(tracks[0]['artist'], 'Test Artist')
        
    @patch('sync.os.getenv')
    @patch('sync.tidalapi.Session')
    def test_sync_to_tidal_adds_new_tracks(self, mock_session_class, mock_getenv):
        # Mock environment variables
        mock_getenv.side_effect = lambda k: "fake" if k.endswith("TIDAL_SESSION_ID") or k.endswith("TOKEN") else ("fake_tidal_playlist_id" if k.endswith("TIDAL_PLAYLIST_ID") else None)
        
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.check_login.return_value = True
        
        mock_playlist = MagicMock()
        mock_playlist.id = "fake_tidal_playlist_id"
        mock_session.user.playlists.return_value = [mock_playlist]
        
        # Existing tracks in Tidal
        mock_existing_track = MagicMock()
        mock_existing_track.name = "Existing Song"
        mock_existing_track.artist.name = "Existing Artist"
        mock_existing_track.id = "existing_id"
        mock_playlist.tracks.return_value = [mock_existing_track]
        
        # Mock search result for a new song
        mock_search_result = MagicMock()
        mock_found_track = MagicMock()
        mock_found_track.id = "new_id"
        # Oude versies van tidalapi konden een dict retourneren, nieuwere een object
        mock_search_result.tracks = [mock_found_track] 
        mock_session.search.return_value = mock_search_result
        
        yt_tracks = [
            {'title': 'Existing Song', 'artist': 'Existing Artist'},
            {'title': 'New Song', 'artist': 'New Artist'}
        ]
        
        sync_to_tidal(yt_tracks, "TEST_VRIEND")
        
        # Verify add was called for New Song only
        # De eerste yt_track wordt overgeslagen vanwege de 'existing' check.
        mock_session.search.assert_called_once_with('New Song New Artist', models=[tidalapi.Track])
        mock_playlist.add.assert_called_once_with(['new_id'])

if __name__ == '__main__':
    unittest.main()
