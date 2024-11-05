from flask import Flask, redirect, request, session, url_for, render_template, flash, jsonify
from flask_session import Session
from flask_cors import CORS
from datetime import timedelta, datetime
import os
import logging
from dotenv import load_dotenv
from app.services.spotify_service import SpotifyService, SpotifyAuthError
from app.services.rate_limiter import rate_limit
from app.manager import SpotifyPlaylistManager
from app.manager import SpotifyPlaylistManager, PlaylistAnalysisError


load_dotenv()


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
celery = Celery('tasks', broker='redis://localhost:6379/0')

app = Flask(__name__)


app.config.update(
    SECRET_KEY=os.getenv('FLASK_SECRET_KEY'),
    SESSION_TYPE='filesystem',
    SESSION_PERMANENT=False,  
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1),  
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_NAME='spotify_session'  
)


CORS(app)
Session(app)


spotify_service = SpotifyService()


@app.after_request
def add_header(response):
    """Add headers to prevent caching."""
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.before_request
def check_session():
    """Check session validity before each request."""
    if 'token_info' in session:
        try:
            # Check if session is expired
            created_at = session.get('created_at')
            if created_at:
                created_at = datetime.fromisoformat(created_at)
                if datetime.now() - created_at > timedelta(hours=1):
                    logger.info("Session expired, clearing session")
                    session.clear()
                    return redirect(url_for('index'))
                    
            # Check if token needs refresh
            if spotify_service.is_token_expired(session['token_info']):
                try:
                    new_token = spotify_service.refresh_token(session['token_info'])
                    session['token_info'] = new_token
                    session['created_at'] = datetime.now().isoformat()
                    logger.info("Token refreshed successfully")
                except Exception as e:
                    logger.error(f"Token refresh failed: {str(e)}")
                    session.clear()
                    return redirect(url_for('index'))
        except Exception as e:
            logger.error(f"Session check error: {str(e)}")
            session.clear()
            return redirect(url_for('index'))

@app.route('/')
def index():
    if session.get('token_info'):
        return redirect(url_for('dashboard'))
    # Check if mobile and not logged in
    if request.headers.get('User-Agent', '').lower().find('mobile') > -1:
        session['mobile'] = True
    return render_template('index.html')
    
@app.route('/login')
def login():
    try:
        auth_url = spotify_service.get_auth_url()
        return redirect(auth_url)
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        flash('Failed to initialize login', 'error')
        return render_template('error.html', error="Authentication failed"), 500

@app.route('/mobile')
def mobile_redirect():
    if session.get('token_info'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('index'))

@app.route('/callback')
def callback():
    try:
        logger.info(f"Callback received - args: {request.args}")
        error = request.args.get('error')
        if error:
            logger.error(f"Spotify auth error: {error}")
            flash(f'Authentication error: {error}', 'error')
            return redirect(url_for('index'))

        code = request.args.get('code')
        state = request.args.get('state')
        stored_state = session.get('oauth_state')
        
        logger.info(f"State check - Received: {state}, Stored: {stored_state}")
        
        if not code:
            logger.error("No code received in callback")
            flash('Authentication failed: No code received', 'error')
            return redirect(url_for('index'))
        
        if state != stored_state:
            logger.error(f"State mismatch: received {state}, expected {stored_state}")
            flash('Authentication failed: State verification failed', 'error')
            return redirect(url_for('index'))

        # Get token
        token_info = spotify_service.get_token(code)
        if not token_info:
            logger.error("No token info received")
            flash('Authentication failed: No token received', 'error')
            return redirect(url_for('index'))
            
        session['token_info'] = token_info
        
        # Get user info
        sp = spotify_service.get_spotify_client()
        if not sp:
            logger.error("Failed to create Spotify client")
            flash('Failed to initialize Spotify client', 'error')
            return redirect(url_for('index'))
            
        user_info = sp.current_user()
        session['user_info'] = {
            'id': user_info['id'],
            'name': user_info['display_name'],
            'image': user_info['images'][0]['url'] if user_info.get('images') else None
        }
        
        logger.info(f"Successfully authenticated user: {user_info['id']}")
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        logger.error(f"Callback error: {str(e)}", exc_info=True)
        flash(f'Authentication failed: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.errorhandler(404)
def not_found_error(error):
    if request.headers.get('User-Agent', '').lower().find('mobile') > -1:
        # If it's a mobile device and we have a session, go to dashboard
        if 'token_info' in session:
            return redirect(url_for('dashboard'))
        # If no session, go to index/login page
        return redirect(url_for('index'))
    return render_template('error.html', error="Page not found"), 404
        
@app.route('/dashboard')
@spotify_service.require_auth
def dashboard():
    try:
        playlists = spotify_service.get_user_playlists()
        return render_template('dashboard.html', 
                             playlists=playlists,
                             user=session.get('user_info'))
    except Exception as e:
        logger.error(f"Dashboard error: {str(e)}")
        flash('Failed to load playlists', 'error')
        return redirect(url_for('index'))

@app.route('/playlist/<playlist_id>/analyze')
@spotify_service.require_auth
@rate_limit
def analyze_playlist(playlist_id):
    try:
        logger.info(f"Starting analysis for playlist: {playlist_id}")
        manager = SpotifyPlaylistManager(playlist_id)
        
       
        if not manager.verify_playlist():
            logger.error(f"Playlist {playlist_id} not found or not accessible")
            flash('Playlist not found or not accessible', 'error')
            return redirect(url_for('dashboard'))
        
        analysis = manager.analyze_tracks()
        
        if not analysis:
            logger.error("Analysis returned no data")
            flash('Analysis failed - no data returned', 'error')
            return redirect(url_for('dashboard'))
        
        return render_template('analysis.html', analysis=analysis)
        
    except Exception as e:
        logger.error(f"Analysis error: {str(e)}", exc_info=True)
        flash('An error occurred during analysis. Please try again.', 'error')
        return redirect(url_for('dashboard'))

@app.route('/api/playlist/<playlist_id>/similar', methods=['GET'])
@spotify_service.require_auth
@rate_limit
def get_similar_tracks(playlist_id):
    try:
        manager = SpotifyPlaylistManager(playlist_id)
        similar_tracks = manager.get_similar_tracks(limit=20)
        return jsonify({
            'tracks': similar_tracks,
            'total': len(similar_tracks)
        })
    except Exception as e:
        logger.error(f"Similar tracks error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/playlist/<playlist_id>/similar/add', methods=['POST'])
@spotify_service.require_auth
@rate_limit
def add_similar_tracks(playlist_id):
    try:
        track_ids = request.json.get('track_ids', [])
        if not track_ids:
            return jsonify({'error': 'No tracks specified'}), 400

        manager = SpotifyPlaylistManager(playlist_id)
        manager.add_similar_tracks(track_ids)
        
        return jsonify({
            'message': f'Successfully added {len(track_ids)} tracks',
            'added_tracks': len(track_ids)
        })
    except Exception as e:
        logger.error(f"Add similar tracks error: {str(e)}")
        return jsonify({'error': str(e)}), 500
        
@app.route('/api/analyze-optimization/<playlist_id>', methods=['POST'])
@spotify_service.require_auth
@rate_limit
def analyze_optimization(playlist_id):
    try:
        criteria = request.json
        if not criteria:
            return jsonify({'error': 'No criteria provided'}), 400

        # Validate criteria
        min_popularity = int(criteria.get('minPopularity', 30))
        min_energy = float(criteria.get('minEnergy', 0.2))
            
        manager = SpotifyPlaylistManager(playlist_id)
        analysis = manager.analyze_tracks()
        
        tracks_to_remove = []
        for track in analysis['track_details']:
            reasons = []
            
           
            if track['popularity'] < min_popularity:
                reasons.append(f"Low popularity ({track['popularity']}%)")
            
         
            if track['energy'] < min_energy:
                reasons.append(f"Low energy ({track['energy']*100:.0f}%)")
            
            if reasons:
                tracks_to_remove.append({
                    'id': track['id'],
                    'name': track['name'],
                    'artist': track['artists'][0],
                    'reasons': reasons,
                    'popularity': track['popularity'],
                    'energy': track['energy']
                })
        
        return jsonify({
            'tracksToRemove': tracks_to_remove,
            'totalTracks': len(analysis['track_details']),
            'affectedTracks': len(tracks_to_remove),
            'criteria': {
                'minPopularity': min_popularity,
                'minEnergy': min_energy
            }
        })
        
    except ValueError as e:
        logger.error(f"Invalid criteria format: {str(e)}")
        return jsonify({'error': f'Invalid criteria format: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"Optimization analysis error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/optimize/<playlist_id>', methods=['POST'])
@spotify_service.require_auth
@rate_limit
def optimize_playlist(playlist_id):
    try:
        criteria = request.json
        if not criteria:
            return jsonify({'error': 'No optimization criteria provided'}), 400
            
        # Start a background task
        task = optimize_playlist_task.delay(playlist_id, criteria)
        
        # Return task ID immediately
        return jsonify({
            'task_id': task.id,
            'status': 'processing',
            'message': 'Optimization started'
        })
        
    except Exception as e:
        logger.error(f"Unexpected optimization error: {str(e)}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred during optimization'}), 500

# Celery task
@celery.task
def optimize_playlist_task(playlist_id, criteria):
    try:
        manager = SpotifyPlaylistManager(playlist_id)
        validated_criteria = {
            'minPopularity': int(criteria.get('minPopularity', 30)),
            'minEnergy': float(criteria.get('minEnergy', 0.2)),
            'autoRemove': bool(criteria.get('autoRemove', False))
        }
        
        result = manager.optimize_playlist(validated_criteria)
        return result
    except Exception as e:
        logger.error(f"Task error: {str(e)}")
        return {'error': str(e)}

# Add a status endpoint
@app.route('/api/optimize/status/<task_id>')
def get_task_status(task_id):
    task = optimize_playlist_task.AsyncResult(task_id)
    if task.ready():
        return jsonify({
            'status': 'completed',
            'result': task.result
        })
    return jsonify({
        'status': 'processing'
    })

@app.route('/logout', methods=['POST'])
def logout():
    try:
        if spotify_service:
            spotify_service.clear_auth()
        
     
        session.clear()
        
      
        response = redirect(url_for('index'))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        flash('Successfully logged out', 'success')
        return response
        
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        return redirect(url_for('index'))

@app.errorhandler(404)
def not_found_error(error):
    return render_template('error.html', error="Page not found"), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html', error="An internal error occurred"), 500

def create_app():
    return app

if __name__ == '__main__':
   
    required_vars = ['SPOTIFY_CLIENT_ID', 'SPOTIFY_CLIENT_SECRET', 
                    'SPOTIFY_REDIRECT_URI', 'FLASK_SECRET_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        exit(1)
        
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)
