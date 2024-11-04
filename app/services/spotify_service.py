import os
from spotipy import Spotify, SpotifyException
from spotipy.oauth2 import SpotifyOAuth
from flask import session, redirect, url_for
from functools import wraps
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class SpotifyAuthError(Exception):
    """Custom exception for Spotify authentication errors."""
    pass

class SpotifyService:
    def __init__(self):
        """Initialize the Spotify service with OAuth configuration."""
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
            session['created_at'] = datetime.now().isoformat()
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
            session['created_at'] = datetime.now().isoformat()
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

            if self.is_token_expired(token_info):
                token_info = self.refresh_token(token_info)

            return Spotify(auth=token_info['access_token'])
        except Exception as e:
            logger.error(f"Error getting Spotify client: {str(e)}")
            return None

    def is_token_expired(self, token_info):
        """Check if the token is expired."""
        try:
            oauth = self.create_oauth()
            return oauth.is_token_expired(token_info)
        except Exception as e:
            logger.error(f"Error checking token expiration: {str(e)}")
            return True

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

    @staticmethod
    def require_auth(f):
        """Decorator to require Spotify authentication."""
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('token_info'):
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function

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
