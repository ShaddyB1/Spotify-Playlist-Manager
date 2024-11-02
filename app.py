from flask import Flask, render_template, redirect, url_for, session, request, jsonify
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os
import time
import logging
from functools import wraps

# Enhanced logging setup
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24))

# Constants
SPOTIFY_SCOPE = (
    "playlist-modify-public playlist-modify-private "
    "user-library-read user-read-recently-played "
    "user-read-playback-state playlist-read-private"
)
TOKEN_INFO_KEY = 'token_info'
USER_INFO_KEY = 'user_info'

# Spotify Authentication Functions
def create_spotify_oauth():
    """Create and return a SpotifyOAuth instance"""
    try:
        client_id = os.getenv('SPOTIFY_CLIENT_ID')
        client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
        redirect_uri = os.getenv('SPOTIFY_REDIRECT_URI')
        
        if not all([client_id, client_secret, redirect_uri]):
            raise ValueError("Missing required Spotify credentials in environment variables")
        
        return SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=SPOTIFY_SCOPE,
            cache_path=None
        )
    except Exception as e:
        logger.error(f"Error creating SpotifyOAuth: {str(e)}", exc_info=True)
        raise

def get_spotify_client():
    """Helper function to create an authenticated Spotify client"""
    token_info = session.get(TOKEN_INFO_KEY)
    if not token_info:
        raise ValueError("No token info found in session")
    
    now = int(time.time())
    if token_info['expires_at'] - now < 60:
        sp_oauth = create_spotify_oauth()
        token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
        session[TOKEN_INFO_KEY] = token_info
    
    return spotipy.Spotify(auth=token_info['access_token'])

# Decorators
def login_required(f):
    """Decorator to check if user is logged in and refresh token if needed"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if TOKEN_INFO_KEY not in session:
            logger.debug("No token in session, redirecting to login")
            return redirect(url_for('login'))
        
        token_info = session[TOKEN_INFO_KEY]
        now = int(time.time())
        if token_info['expires_at'] - now < 60:
            try:
                sp_oauth = create_spotify_oauth()
                token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
                session[TOKEN_INFO_KEY] = token_info
            except Exception as e:
                logger.error(f"Error refreshing token: {str(e)}", exc_info=True)
                session.clear()
                return redirect(url_for('login'))
        
        return f(*args, **kwargs)
    return decorated_function

# Routes - Authentication
@app.route('/')
def index():
    """Landing page route"""
    try:
        if TOKEN_INFO_KEY in session:
            logger.debug("User already logged in, redirecting to dashboard")
            return redirect(url_for('dashboard'))
        return render_template('login.html')
    except Exception as e:
        logger.error(f"Error in index route: {str(e)}", exc_info=True)
        return render_template('login.html')

@app.route('/login')
def login():
    """Initialize Spotify login process"""
    try:
        sp_oauth = create_spotify_oauth()
        auth_url = sp_oauth.get_authorize_url()
        logger.debug(f"Generated Spotify auth URL: {auth_url}")
        return redirect(auth_url)
    except Exception as e:
        logger.error(f"Error in login route: {str(e)}", exc_info=True)
        return redirect(url_for('index'))

@app.route('/callback')
def callback():
    """Handle Spotify OAuth callback"""
    try:
        if 'error' in request.args:
            logger.error(f"Spotify auth error: {request.args.get('error')}")
            return redirect(url_for('index'))
        
        if 'code' not in request.args:
            logger.error("No code in callback args")
            return redirect(url_for('index'))
        
        sp_oauth = create_spotify_oauth()
        token_info = sp_oauth.get_access_token(request.args['code'])
        
        if not token_info:
            logger.error("Failed to get token info")
            return redirect(url_for('index'))
        
        session[TOKEN_INFO_KEY] = token_info
        
        # Get user info
        sp = spotipy.Spotify(auth=token_info['access_token'])
        user_info = sp.me()
        
        session[USER_INFO_KEY] = {
            'id': user_info['id'],
            'name': user_info.get('display_name', 'User'),
            'email': user_info.get('email'),
            'image': user_info.get('images', [{}])[0].get('url') if user_info.get('images') else None
        }
        
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        logger.error(f"Error in callback: {str(e)}", exc_info=True)
        return redirect(url_for('index'))

@app.route('/logout')
def logout():
    """Log out user by clearing session"""
    session.clear()
    return redirect(url_for('index'))

# Routes - Main Application
@app.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard showing user's playlists"""
    try:
        sp = get_spotify_client()
        processed_playlists = []
        playlists = sp.current_user_playlists()
        
        while playlists:
            for playlist in playlists['items']:
                if playlist:
                    processed_playlists.append({
                        'id': playlist['id'],
                        'name': playlist['name'],
                        'images': playlist.get('images', []),
                        'tracks': {
                            'total': playlist['tracks']['total']
                        },
                        'owner': {
                            'id': playlist['owner']['id'],
                            'name': playlist['owner'].get('display_name', 'Unknown')
                        }
                    })
            
            if playlists['next']:
                playlists = sp.next(playlists)
            else:
                break
        
        return render_template('dashboard.html',
                             playlists=processed_playlists,
                             user=session.get(USER_INFO_KEY))
        
    except Exception as e:
        logger.error(f"Error in dashboard: {str(e)}", exc_info=True)
        session.clear()
        return redirect(url_for('login'))

@app.route('/analyze_playlist/<playlist_id>')
@login_required
def analyze_playlist(playlist_id):
    """Analyze a specific playlist"""
    try:
        sp = get_spotify_client()
        
        # Get playlist info
        playlist = sp.playlist(playlist_id)
        
        # Get all tracks with pagination
        tracks = []
        results = sp.playlist_tracks(playlist_id)
        while results:
            tracks.extend(results['items'])
            if results['next']:
                results = sp.next(results)
            else:
                break

        # Get recent tracks for play history
        recent_plays = sp.current_user_recently_played(limit=50)
        recent_track_ids = {item['track']['id'] for item in recent_plays['items']}

        # Process tracks
        analysis = {
            'playlist_name': playlist['name'],
            'total_tracks': len(tracks),
            'tracks': [],
            'average_popularity': 0,
            'total_duration_ms': 0,
            'genres': {},
            'artists': {},
            'decades': {},
            'top_artists': []
        }

        total_popularity = 0
        for item in tracks:
            if not item['track']:
                continue
                
            track = item['track']
            artists = track['artists']
            
            # Update artist statistics
            for artist in artists:
                if artist['id'] in analysis['artists']:
                    analysis['artists'][artist['id']]['count'] += 1
                else:
                    analysis['artists'][artist['id']] = {
                        'name': artist['name'],
                        'count': 1
                    }

            track_info = {
                'name': track['name'],
                'artist': artists[0]['name'],  # Primary artist
                'popularity': track['popularity'],
                'duration': track['duration_ms'] // 1000,  # Convert to seconds
                'added_at': item['added_at'],
                'recently_played': track['id'] in recent_track_ids
            }
            
            analysis['tracks'].append(track_info)
            total_popularity += track['popularity']
            analysis['total_duration_ms'] += track['duration_ms']

        if analysis['total_tracks'] > 0:
            analysis['average_popularity'] = total_popularity / analysis['total_tracks']

        # Sort artists by track count and get top 10
        sorted_artists = sorted(
            analysis['artists'].values(), 
            key=lambda x: x['count'], 
            reverse=True
        )[:10]
        analysis['top_artists'] = [
            {'name': artist['name'], 'count': artist['count']} 
            for artist in sorted_artists
        ]

        # Additional statistics
        analysis['stats'] = {
            'duration_hours': round(analysis['total_duration_ms'] / (1000 * 60 * 60), 1),
            'recently_played_tracks': sum(1 for track in analysis['tracks'] if track['recently_played']),
            'average_popularity_rounded': round(analysis['average_popularity']),
            'playlist_age': item['added_at'] if tracks else None  # Most recent addition
        }

        return render_template(
            'analysis.html',
            analysis=analysis,
            playlist=playlist
        )
        
    except Exception as e:
        logger.error(f"Error analyzing playlist {playlist_id}: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": "An error occurred while analyzing the playlist"
        }), 500
# API Routes
@app.route('/api/optimize/<playlist_id>', methods=['POST'])
@login_required
def optimize_playlist_route(playlist_id):
    try:
        sp = get_spotify_client()
        settings = request.json
        
        # Get current playlist tracks
        tracks = []
        results = sp.playlist_tracks(playlist_id)
        while results:
            tracks.extend(results['items'])
            if results['next']:
                results = sp.next(results)
            else:
                break

        # Track selection criteria
        tracks_to_remove = []
        tracks_to_keep = []
        
        for item in tracks:
            if not item['track']:
                continue
                
            track = item['track']
            should_remove = False
            
            # Apply criteria from settings
            if track['popularity'] < int(settings.get('minPopularity', 30)):
                should_remove = True
                
            if should_remove:
                tracks_to_remove.append(track['id'])
            else:
                tracks_to_keep.append(track['id'])

        # Update playlist
        if tracks_to_remove:
            # Remove tracks
            sp.playlist_remove_all_occurrences_of_items(
                playlist_id,
                tracks_to_remove
            )
            
            # Get recommendations for replacement
            if tracks_to_keep:
                seed_tracks = tracks_to_keep[:5]  # Spotify limits to 5 seed tracks
                recommendations = sp.recommendations(
                    seed_tracks=seed_tracks,
                    limit=min(len(tracks_to_remove), 20)
                )
                
                # Add recommended tracks
                new_tracks = [track['id'] for track in recommendations['tracks']]
                if new_tracks:
                    sp.playlist_add_items(playlist_id, new_tracks)
            
            return jsonify({
                "status": "success",
                "message": f"Removed {len(tracks_to_remove)} tracks and added {len(new_tracks)} recommendations",
                "data": {
                    "removed_tracks": len(tracks_to_remove),
                    "added_tracks": len(new_tracks)
                }
            })
        
        return jsonify({
            "status": "success",
            "message": "No tracks needed optimization",
            "data": {
                "removed_tracks": 0,
                "added_tracks": 0
            }
        })
        
    except Exception as e:
        logger.error(f"Error optimizing playlist {playlist_id}: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
    

@app.route('/api/analyze-changes', methods=['POST'])
@login_required
def analyze_changes():
    """API endpoint to analyze playlist changes"""
    try:
        data = request.get_json()
        
        if not data or 'playlist_id' not in data:
            return jsonify({"error": "Missing playlist_id"}), 400
            
        playlist_id = data['playlist_id']
        sp = get_spotify_client()
        
        # Fetch playlist
        playlist = sp.playlist(playlist_id)
        
        # Get tracks
        tracks = []
        results = playlist['tracks']
        while results:
            tracks.extend([
                {
                    'id': item['track']['id'],
                    'name': item['track']['name'],
                    'artists': [artist['name'] for artist in item['track']['artists']],
                    'added_at': item['added_at']
                }
                for item in results['items']
                if item['track']
            ])
            
            if results['next']:
                results = sp.next(results)
            else:
                break
        
        # Sort by added date
        tracks.sort(key=lambda x: x['added_at'], reverse=True)
        recent_changes = tracks[:10]
        
        return jsonify({
            "status": "success",
            "playlist_name": playlist['name'],
            "total_tracks": len(tracks),
            "recent_changes": recent_changes
        })
        
    except Exception as e:
        logger.error(f"Error analyzing changes: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# Error Handlers
@app.errorhandler(404)
def not_found_error(error):
    return jsonify({
        "status": "error",
        "message": "Resource not found"
    }), 404

@app.route('/api/analyze-optimization/<playlist_id>', methods=['POST'])
@login_required
def analyze_optimization(playlist_id):
    try:
        sp = get_spotify_client()
        settings = request.json
        
        # Get playlist tracks
        tracks = []
        results = sp.playlist_tracks(playlist_id)
        while results:
            tracks.extend(results['items'])
            if results['next']:
                results = sp.next(results)
            else:
                break

        tracks_to_remove = []
        for item in tracks:
            if not item['track']:
                continue
                
            track = item['track']
            removal_reason = []

            # Check popularity
            if track['popularity'] < int(settings.get('minPopularity', 30)):
                removal_reason.append('Low popularity')

            # Get recent plays to check inactivity
            recent_tracks = sp.current_user_recently_played(limit=50)
            recent_track_ids = [item['track']['id'] for item in recent_tracks['items']]
            
            if track['id'] not in recent_track_ids:
                removal_reason.append('Inactive')

            # If any reasons to remove, add to list
            if removal_reason:
                tracks_to_remove.append({
                    'id': track['id'],
                    'name': track['name'],
                    'artist': track['artists'][0]['name'],
                    'reason': ', '.join(removal_reason)
                })

        return jsonify({
            'status': 'success',
            'tracksToRemove': tracks_to_remove
        })

    except Exception as e:
        logger.error(f"Error analyzing optimization: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500
    
@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "status": "error",
        "message": "An unexpected error occurred"
    }), 500

if __name__ == '__main__':
    # Verify environment variables
    required_env_vars = ['SPOTIFY_CLIENT_ID', 'SPOTIFY_CLIENT_SECRET', 'SPOTIFY_REDIRECT_URI']
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    app.run(debug=True)