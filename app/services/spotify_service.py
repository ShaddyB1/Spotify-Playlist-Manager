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
        self._oauth = None  # Cache the OAuth instance

    def create_oauth(self):
        """Create SpotifyOAuth instance with caching."""
        if self._oauth is not None:
            return self._oauth
            
        if not all([self.client_id, self.client_secret, self.redirect_uri]):
            raise SpotifyAuthError("Missing Spotify credentials")
            
        try:
            self._oauth = SpotifyOAuth(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                scope=self.scope,
                cache_handler=None,
                open_browser=False,
                show_dialog=True
            )
            return self._oauth
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
            token_info = oauth.get_access_token(code, check_cache=False, as_dict=True)
            if not token_info:
                raise SpotifyAuthError("Failed to get token information")
            
            # Store minimal token info in session
            session['token_info'] = {
                'access_token': token_info['access_token'],
                'refresh_token': token_info['refresh_token'],
                'expires_at': token_info['expires_at'],
                'scope': token_info['scope']
            }
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
            if not token_info.get('refresh_token'):
                raise SpotifyAuthError("No refresh token available")
    
            logger.info("Attempting to refresh token.")
            new_token = oauth.refresh_access_token(token_info['refresh_token'])
            
            # Update session with new token info
            session['token_info'] = {
                'access_token': new_token['access_token'],
                'refresh_token': new_token.get('refresh_token', token_info['refresh_token']),
                'expires_at': new_token['expires_at'],
                'scope': new_token.get('scope', token_info.get('scope', ''))
            }
            session['created_at'] = datetime.now().isoformat()
            logger.info("Token refreshed successfully.")
            return session['token_info']
        except SpotifyAuthError as e:
            logger.error(f"Authentication error refreshing token: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error refreshing token: {str(e)}")
            return None



    def get_spotify_client(self):
        """Get an authenticated Spotify client."""
        try:
            token_info = session.get('token_info')
            if not token_info:
                logger.warning("No token info found in session")
                return None
    
            # Check if token is expired and refresh if needed
            if self.is_token_expired(token_info):
                # Use a counter to limit the number of refresh attempts
                session['refresh_attempts'] = session.get('refresh_attempts', 0) + 1
                if session['refresh_attempts'] > 1:  # Only allow 1 refresh attempt
                    logger.error("Max refresh attempts reached. Redirecting to login.")
                    session.pop('refresh_attempts', None)
                    self.clear_auth()
                    return redirect(url_for('login'))
                
                # Try refreshing the token
                token_info = self.refresh_token(token_info)
                if not token_info:
                    logger.error("Token refresh failed, redirecting to login.")
                    self.clear_auth()
                    return redirect(url_for('login'))
    
            # Reset refresh attempts counter on successful access
            session.pop('refresh_attempts', None)
            return Spotify(auth=token_info['access_token'])
        except Exception as e:
            logger.error(f"Error getting Spotify client: {str(e)}")
            return None



    def is_token_expired(self, token_info):
        """Check if the token is expired."""
        try:
            now = int(datetime.now().timestamp())
            return token_info['expires_at'] - now < 60
        except Exception as e:
            logger.error(f"Error checking token expiration: {str(e)}")
            return True

    def clear_auth(self):
        """Clear all authentication data."""
        try:
            session.clear()
            self._oauth = None
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
