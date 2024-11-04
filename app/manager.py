import spotipy
from spotipy.oauth2 import SpotifyOAuth
from datetime import datetime
import os
from dotenv import load_dotenv
import logging
from typing import Dict, List, Optional
from collections import defaultdict
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PlaylistAnalysisError(Exception):
    """Custom exception for playlist analysis errors."""
    pass

class SpotifyPlaylistManager:
    def __init__(self, playlist_id: str):
        """Initialize the Spotify client with comprehensive scope."""
        load_dotenv()
        
        self.scope = (
            "playlist-modify-public playlist-modify-private "
            "user-library-read user-read-recently-played "
            "user-read-playback-state playlist-read-private "
            "user-top-read"
        )
        
        try:
            self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=os.getenv('SPOTIFY_CLIENT_ID'),
                client_secret=os.getenv('SPOTIFY_CLIENT_SECRET'),
                redirect_uri=os.getenv('SPOTIFY_REDIRECT_URI'),
                scope=self.scope
            ))
            self.playlist_id = playlist_id
            logger.info(f"Successfully initialized SpotifyPlaylistManager for playlist: {playlist_id}")
        except Exception as e:
            logger.error(f"Failed to initialize Spotify client: {str(e)}")
            raise

    def convert_to_serializable(self, data):
        """Convert complex data types to serializable Python types."""
        if isinstance(data, defaultdict):
            return dict(data)
        elif isinstance(data, (set, dict.items().__class__)):
            return list(data)
        elif isinstance(data, dict):
            return {k: self.convert_to_serializable(v) for k, v in data.items()}
        elif isinstance(data, (list, tuple)):
            return [self.convert_to_serializable(x) for x in data]
        return data

    def get_playlist_tracks(self) -> List[Dict]:
        """Get all tracks from the playlist with pagination."""
        try:
            tracks = []
            results = self.sp.playlist_tracks(self.playlist_id)
            
            while results:
                tracks.extend(results['items'])
                if results['next']:
                    results = self.sp.next(results)
                else:
                    break
                    
            logger.info(f"Retrieved {len(tracks)} tracks from playlist {self.playlist_id}")
            return tracks
        except Exception as e:
            logger.error(f"Error retrieving playlist tracks: {str(e)}")
            raise PlaylistAnalysisError(f"Failed to get playlist tracks: {str(e)}")

    def get_energy(self, track_id: str) -> float:
        """Get energy level for a track."""
        try:
            features = self.sp.audio_features([track_id])[0]
            return features['energy'] if features else 0.0
        except Exception as e:
            logger.error(f"Error getting energy for track {track_id}: {str(e)}")
            return 0.0

    def analyze_tracks(self) -> Dict[str, Any]:
        """Analyze tracks for potential removal based on multiple factors."""
        try:
            tracks = self.get_playlist_tracks()
            recent_plays = self.sp.current_user_recently_played(limit=50)
            
            recent_plays_lookup = {
                item['track']['id']: {
                    'played_at': datetime.fromisoformat(item['played_at'].replace('Z', '+00:00')),
                    'context': item.get('context')
                } for item in recent_plays['items']
            }
            
            analysis = {
                'total_tracks': len(tracks),
                'played_tracks': 0,
                'skipped_tracks': 0,
                'inactive_tracks': 0,
                'duplicates': [],
                'track_details': [],
                'genre_distribution': defaultdict(int),
                'artist_distribution': defaultdict(int),
                'popularity_distribution': defaultdict(int),
                'decade_distribution': defaultdict(int)
            }
            
            track_ids = set()
            
            for track in tracks:
                if not track['track']:
                    continue
                    
                track_id = track['track']['id']
                
                # Check for duplicates
                if track_id in track_ids:
                    analysis['duplicates'].append(track['track']['name'])
                track_ids.add(track_id)
                
                track_info = {
                    'id': track_id,
                    'name': track['track']['name'],
                    'artists': [artist['name'] for artist in track['track']['artists']],
                    'added_at': track['added_at'],
                    'popularity': track['track']['popularity'],
                    'duration_ms': track['track']['duration_ms'],
                    'explicit': track['track']['explicit'],
                    'preview_url': track['track']['preview_url'],
                    'energy': self.get_energy(track_id)
                }
                
                analysis['popularity_distribution'][track_info['popularity'] // 10 * 10] += 1
                for artist in track_info['artists']:
                    analysis['artist_distribution'][artist] += 1
                
                if track_id in recent_plays_lookup:
                    track_info['last_played'] = recent_plays_lookup[track_id]['played_at'].isoformat()
                    analysis['played_tracks'] += 1
                else:
                    track_info['last_played'] = None
                    analysis['inactive_tracks'] += 1
                
                analysis['track_details'].append(track_info)
            
            analysis.update({
                'average_popularity': sum(t['popularity'] for t in analysis['track_details']) / len(analysis['track_details']) if analysis['track_details'] else 0,
                'total_duration_ms': sum(t['duration_ms'] for t in analysis['track_details']),
                'explicit_tracks': sum(1 for t in analysis['track_details'] if t['explicit']),
                'preview_available': sum(1 for t in analysis['track_details'] if t['preview_url']),
                'average_energy': sum(t['energy'] for t in analysis['track_details']) / len(analysis['track_details']) if analysis['track_details'] else 0
            })

            final_analysis = {
            'total_tracks': analysis['total_tracks'],
            'played_tracks': analysis['played_tracks'],
            'skipped_tracks': analysis['skipped_tracks'],
            'inactive_tracks': analysis['inactive_tracks'],
            'duplicates': list(analysis['duplicates']),
            'track_details': list(analysis['track_details']),
            'genre_distribution': dict(analysis['genre_distribution']),
            'artist_distribution': dict(analysis['artist_distribution']),
            'popularity_distribution': dict(analysis['popularity_distribution']),
            'decade_distribution': dict(analysis['decade_distribution']),
            'average_popularity': analysis['average_popularity'],
            'total_duration_ms': analysis['total_duration_ms'],
            'explicit_tracks': analysis['explicit_tracks'],
            'preview_available': analysis['preview_available'],
            'average_energy': analysis['average_energy']
        }

            
            
            logger.info(f"Completed analysis for playlist {self.playlist_id}")
            return final_analysis
            
        except Exception as e:
            logger.error(f"Error analyzing tracks: {str(e)}")
            raise PlaylistAnalysisError(f"Failed to analyze tracks: {str(e)}")

    def get_similar_tracks(self, limit: int = 20) -> List[Dict]:
        """Get similar tracks based on playlist tracks."""
        try:
            tracks = self.get_playlist_tracks()
            if not tracks:
                return []

            # Get seed tracks and audio features
            seed_tracks = [t['track']['id'] for t in tracks[:5] if t['track']]
            audio_features = [self.get_energy(track_id) for track_id in seed_tracks]
            
            # Calculate average energy
            avg_energy = sum(audio_features) / len(audio_features) if audio_features else 0.5
            
            # Get recommendations
            recommendations = self.sp.recommendations(
                seed_tracks=seed_tracks[:5],
                limit=limit,
                target_energy=avg_energy,
                min_popularity=30
            )

            existing_track_ids = {track['track']['id'] for track in tracks if track['track']}
            similar_tracks = [
                {
                    'id': track['id'],
                    'name': track['name'],
                    'artist': track['artists'][0]['name'],
                    'popularity': track['popularity'],
                    'preview_url': track['preview_url'],
                    'image': track['album']['images'][0]['url'] if track['album']['images'] else None
                }
                for track in recommendations['tracks']
                if track['id'] not in existing_track_ids
            ]

            return similar_tracks

        except Exception as e:
            logger.error(f"Error finding similar tracks: {str(e)}")
            raise

    def add_similar_tracks(self, track_ids: List[str]) -> bool:
        """Add similar tracks to the playlist."""
        try:
            track_uris = [f"spotify:track:{track_id}" for track_id in track_ids]
            
            for i in range(0, len(track_uris), 100):  # Add in batches of 100
                batch = track_uris[i:i+100]
                self.sp.playlist_add_items(self.playlist_id, batch)
            
            return True
        except Exception as e:
            logger.error(f"Error adding similar tracks: {str(e)}")
            raise
