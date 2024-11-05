from spotipy.oauth2 import SpotifyOAuth
from flask import session, url_for
from functools import wraps
import logging
import os
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class SpotifyAuthError(Exception):
    pass

class SpotifyService:
    def __init__(self):
        self.scope = (
            "playlist-modify-public playlist-modify-private "
            "user-library-read user-read-recently-played "
            "user-read-playback-state playlist-read-private "
            "user-top-read"
        )
        
        self._auth = None  # Initialize as None
        
    @property
    def auth_manager(self):
        if self._auth is None:
            self._auth = SpotifyOAuth(
                client_id=os.getenv('SPOTIFY_CLIENT_ID'),
                client_secret=os.getenv('SPOTIFY_CLIENT_SECRET'),
                redirect_uri=os.getenv('SPOTIFY_REDIRECT_URI'),
                scope=self.scope,
                open_browser=False,
                cache_handler=None  # Disable caching to prevent recursion
            )
        return self._auth

    def get_auth_url(self) -> str:
        """Generate authorization URL."""
        try:
            auth_url = self.auth_manager.get_authorize_url()
            logger.info(f"Generated auth URL with state: {session.get('oauth_state')}")
            return auth_url
        except Exception as e:
            logger.error(f"Error generating auth URL: {e}")
            raise

    def get_token(self, code: str) -> Dict[str, Any]:
        """Get token info from authorization code."""
        try:
            token_info = self.auth_manager.get_access_token(code, as_dict=True)
            logger.info("Successfully obtained token information")
            return token_info
        except Exception as e:
            logger.error(f"Error getting token: {e}")
            raise SpotifyAuthError(f"Failed to get access token: {str(e)}")

    def refresh_token(self, token_info: dict) -> Dict[str, Any]:
        """Refresh access token."""
        try:
            if self.is_token_expired(token_info):
                token_info = self.auth_manager.refresh_access_token(token_info['refresh_token'])
            return token_info
        except Exception as e:
            logger.error(f"Error refreshing token: {e}")
            raise SpotifyAuthError(f"Failed to refresh token: {str(e)}")

    def get_spotify_client(self):
        """Get an authenticated Spotify client."""
        try:
            from spotipy import Spotify
            token_info = session.get('token_info', None)
            
            if not token_info:
                raise SpotifyAuthError("No token info in session")
                
            if self.is_token_expired(token_info):
                token_info = self.refresh_token(token_info)
                session['token_info'] = token_info
                
            return Spotify(auth=token_info['access_token'])
        except Exception as e:
            logger.error(f"Error getting Spotify client: {e}")
            raise SpotifyAuthError(f"Failed to get Spotify client: {str(e)}")

    def is_token_expired(self, token_info: Optional[Dict]) -> bool:
        """Check if the token is expired."""
        if not token_info:
            return True
        now = int(time.time())
        return token_info['expires_at'] - now < 60

    def clear_auth(self):
        """Clear authentication data."""
        self._auth = None
        if 'token_info' in session:
            del session['token_info']

    def require_auth(self, f):
        """Decorator to require authentication."""
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'token_info' not in session:
                return url_for('login')
                
            token_info = session['token_info']
            
            try:
                if self.is_token_expired(token_info):
                    token_info = self.refresh_token(token_info)
                    session['token_info'] = token_info
            except:
                return url_for('login')
                
            return f(*args, **kwargs)
        return decorated

    def get_user_playlists(self):
        """Get user's playlists."""
        try:
            sp = self.get_spotify_client()
            playlists = []
            results = sp.current_user_playlists()
            
            while results:
                playlists.extend(results['items'])
                if results['next']:
                    results = sp.next(results)
                else:
                    break
                    
            return playlists
        except Exception as e:
            logger.error(f"Error getting user playlists: {e}")
            raise SpotifyAuthError(f"Failed to get playlists: {str(e)}")
