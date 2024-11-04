from flask import Flask, redirect, request, session, url_for, render_template, flash, jsonify
from flask_session import Session
from flask_cors import CORS
from datetime import timedelta
import os
from dotenv import load_dotenv
import logging
from .services.spotify_service import SpotifyService, SpotifyAuthError
from .services.rate_limiter import rate_limit
from .manager import SpotifyPlaylistManager


load_dotenv()


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)
    
   
    app.config.update(
        SECRET_KEY=os.getenv('FLASK_SECRET_KEY'),
        SESSION_TYPE='filesystem',
        SESSION_PERMANENT=True,
        PERMANENT_SESSION_LIFETIME=timedelta(days=1)
    )
    
  
    CORS(app)
    Session(app)
    
 
    spotify_service = SpotifyService()
    
    @app.route('/')
    def index():
        if session.get('token_info'):
            return redirect(url_for('dashboard'))
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

    @app.route('/callback')
    def callback():
        try:
            code = request.args.get('code')
            state = request.args.get('state')
            
            if not code or state != session.get('oauth_state'):
                raise SpotifyAuthError("Invalid OAuth callback parameters")

            
            token_info = spotify_service.get_token(code)
            user_info = spotify_service.get_current_user()
            
            # Store user info in session
            session['user_info'] = {
                'id': user_info['id'],
                'name': user_info['display_name'],
                'image': user_info['images'][0]['url'] if user_info.get('images') else None
            }
            
            return redirect(url_for('dashboard'))
        except Exception as e:
            logger.error(f"Callback error: {str(e)}")
            flash('Authentication failed', 'error')
            return redirect(url_for('index'))

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
            manager = SpotifyPlaylistManager(playlist_id)
            analysis = manager.analyze_tracks()
            return render_template('analyze.html', analysis=analysis)
        except Exception as e:
            logger.error(f"Analysis error: {str(e)}")
            flash('Failed to analyze playlist', 'error')
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

    @app.route('/api/optimize/<playlist_id>', methods=['POST'])
    @spotify_service.require_auth
    @rate_limit
    def optimize_playlist(playlist_id):
        try:
            criteria = request.json
            manager = SpotifyPlaylistManager(playlist_id)
            result = manager.optimize_playlist(criteria)
            return jsonify(result)
        except Exception as e:
            logger.error(f"Optimization error: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/logout', methods=['POST'])
    def logout():
        session.clear()
        return redirect(url_for('index'))

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('error.html', error="Page not found"), 404

    @app.errorhandler(500)
    def internal_error(error):
        return render_template('error.html', error="An internal error occurred"), 500

    return app

app = create_app()

if __name__ == '__main__':
  
    required_vars = ['SPOTIFY_CLIENT_ID', 'SPOTIFY_CLIENT_SECRET', 
                    'SPOTIFY_REDIRECT_URI', 'FLASK_SECRET_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        exit(1)
        
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)
