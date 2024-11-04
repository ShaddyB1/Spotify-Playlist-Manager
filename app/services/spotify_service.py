from spotipy import Spotify, SpotifyException
from spotipy.oauth2 import SpotifyOAuth
from flask import session, redirect, url_for
import logging
import os
from functools import wraps

logger = logging.getLogger(__name__)

class SpotifyAuthError(Exception):
    """Custom exception for Spotify authentication errors."""
    pass

class SpotifyService:
    def __init__(self):
        self.client_id = os.getenv('SPOTIFY_CLIENT_ID')
        self.client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
        self.redirect_uri = os.getenv('SPOTIFY_REDIRECT_URI')
        self.scope = (
            "playlist-modify-public playlist-modify-private "
            "user-library-read user-read-recently-played "
            "user-read-playback-state playlist-read-private "
            "playlist-read-collaborative user-top-read"
        )

    def create_oauth(self):
        """Create SpotifyOAuth instance."""
        if not all([self.client_id, self.client_secret, self.redirect_uri]):
            raise SpotifyAuthError("Missing Spotify credentials")
            
        try:
            return SpotifyOAuth(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                scope=self.scope,
                cache_handler=None  # Disable caching
            )
        except Exception as e:
            logger.error(f"Error creating OAuth: {str(e)}")
            raise SpotifyAuthError("Failed to initialize Spotify OAuth")

    def get_auth_url(self):
        """Get the Spotify authorization URL."""
        try:
            oauth = self.create_oauth()
            auth_url = oauth.get_authorize_url()
            session['oauth_state'] = oauth.state
            logger.info(f"Generated auth URL with state: {oauth.state}")
            return auth_url
        except Exception as e:
            logger.error(f"Error getting auth URL: {str(e)}")
            raise SpotifyAuthError("Failed to generate authorization URL")

    def get_token(self, code):
        """Get access token using authorization code."""
        try:
            oauth = self.create_oauth()
            token_info = oauth.get_access_token(code, check_cache=False)
            if not token_info:
                raise SpotifyAuthError("Failed to get token information")
            
            session['token_info'] = token_info
            logger.info("Successfully obtained token information")
            return token_info
        except Exception as e:
            logger.error(f"Error getting token: {str(e)}")
            raise SpotifyAuthError(f"Failed to get access token: {str(e)}")

    def refresh_token(self, token_info):
        """Refresh the access token."""
        try:
            oauth = self.create_oauth()
            new_token = oauth.refresh_access_token(token_info['refresh_token'])
            session['token_info'] = new_token
            return new_token
        except Exception as e:
            logger.error(f"Error refreshing token: {str(e)}")
            raise SpotifyAuthError("Failed to refresh token")

    def get_spotify_client(self):
        """Get an authenticated Spotify client."""
        try:
            token_info = session.get('token_info')
            if not token_info:
                return None

            oauth = self.create_oauth()
            if oauth.is_token_expired(token_info):
                token_info = self.refresh_token(token_info)

            return Spotify(auth=token_info['access_token'])
        except Exception as e:
            logger.error(f"Error getting Spotify client: {str(e)}")
            return None

    def get_current_user(self):
        """Get current user's profile information."""
        try:
            sp = self.get_spotify_client()
            if not sp:
                raise SpotifyAuthError("No valid Spotify client")
            return sp.current_user()
        except Exception as e:
            logger.error(f"Error getting current user: {str(e)}")
            raise

    def get_user_playlists(self, limit=50):
        """Get user's playlists with pagination."""
        try:
            sp = self.get_spotify_client()
            if not sp:
                raise SpotifyAuthError("No valid Spotify client")

            playlists = []
            results = sp.current_user_playlists(limit=limit)
            
            while results:
                playlists.extend(results['items'])
                if results['next']:
                    results = sp.next(results)
                else:
                    break

            return playlists
        except Exception as e:
            logger.error(f"Error getting user playlists: {str(e)}")
            raise

    def get_playlist_tracks(self, playlist_id):
        """Get all tracks from a playlist."""
        try:
            sp = self.get_spotify_client()
            if not sp:
                raise SpotifyAuthError("No valid Spotify client")

            tracks = []
            results = sp.playlist_tracks(playlist_id)
            
            while results:
                tracks.extend([
                    {
                        'track': item['track'],
                        'added_at': item['added_at']
                    }
                    for item in results['items'] if item['track']
                ])
                
                if results['next']:
                    results = sp.next(results)
                else:
                    break

            return tracks
        except Exception as e:
            logger.error(f"Error getting playlist tracks: {str(e)}")
            raise

    def get_audio_features(self, track_ids):
        """Get audio features for multiple tracks."""
        try:
            sp = self.get_spotify_client()
            if not sp:
                raise SpotifyAuthError("No valid Spotify client")

            # Split track_ids into chunks of 100 (Spotify API limit)
            features = []
            for i in range(0, len(track_ids), 100):
                chunk = track_ids[i:i + 100]
                chunk_features = sp.audio_features(chunk)
                features.extend([f for f in chunk_features if f])

            return features
        except Exception as e:
            logger.error(f"Error getting audio features: {str(e)}")
            raise

    @staticmethod
    def require_auth(f):
        """Decorator to require Spotify authentication."""
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('token_info'):
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function

    def clear_auth(self):
    """Clear all authentication data."""
    try:
        # Clear session data
        session.clear()
        
        # Clear OAuth cache if exists
        oauth = self.create_oauth()
        if oauth.cache_handler:
            oauth.cache_handler.save_token_to_cache(None)
            
        logger.info("Successfully cleared authentication data")
    except Exception as e:
        logger.error(f"Error clearing auth: {str(e)}")
        raise

    def update_playlist(self, playlist_id, tracks_to_remove=None, tracks_to_add=None):
        """Update a playlist by removing and/or adding tracks."""
        try:
            sp = self.get_spotify_client()
            if not sp:
                raise SpotifyAuthError("No valid Spotify client")

            if tracks_to_remove:
                # Remove tracks in batches of 100
                for i in range(0, len(tracks_to_remove), 100):
                    batch = tracks_to_remove[i:i + 100]
                    sp.playlist_remove_all_occurrences_of_items(playlist_id, batch)

            if tracks_to_add:
                # Add tracks in batches of 100
                for i in range(0, len(tracks_to_add), 100):
                    batch = tracks_to_add[i:i + 100]
                    sp.playlist_add_items(playlist_id, batch)

            return True
        except Exception as e:
            logger.error(f"Error updating playlist: {str(e)}")
            raise
