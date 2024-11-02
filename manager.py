import spotipy
from spotipy.oauth2 import SpotifyOAuth
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import logging
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict

# Configure logging
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

    def get_playlist_tracks(self) -> List[Dict]:
        """Get all tracks from the playlist with pagination handling."""
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

    def analyze_tracks(self) -> Dict[str, Any]:
        """
        Analyze tracks for potential removal based on multiple factors.
        Returns comprehensive analysis of playlist tracks.
        """
        try:
            tracks = self.get_playlist_tracks()
            recent_plays = self.sp.current_user_recently_played(limit=50)
            
            # Convert recent plays to a lookup dictionary
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
                if not track['track']:  # Skip None tracks
                    continue
                    
                track_id = track['track']['id']
                
                # Check for duplicates
                if track_id in track_ids:
                    analysis['duplicates'].append(track['track']['name'])
                track_ids.add(track_id)
                
                # Basic track info
                track_info = {
                    'id': track_id,
                    'name': track['track']['name'],
                    'artists': [artist['name'] for artist in track['track']['artists']],
                    'added_at': track['added_at'],
                    'popularity': track['track']['popularity'],
                    'duration_ms': track['track']['duration_ms'],
                    'explicit': track['track']['explicit'],
                    'preview_url': track['track']['preview_url']
                }
                
                # Update distributions
                analysis['popularity_distribution'][track_info['popularity'] // 10 * 10] += 1
                for artist in track_info['artists']:
                    analysis['artist_distribution'][artist] += 1
                
                # Get audio features for the track
                try:
                    audio_features = self.sp.audio_features([track_id])[0]
                    if audio_features:
                        track_info.update({
                            'danceability': audio_features['danceability'],
                            'energy': audio_features['energy'],
                            'key': audio_features['key'],
                            'tempo': audio_features['tempo']
                        })
                except Exception as e:
                    logger.warning(f"Could not get audio features for track {track_id}: {str(e)}")
                
                # Check recent plays
                if track_id in recent_plays_lookup:
                    track_info['last_played'] = recent_plays_lookup[track_id]['played_at'].isoformat()
                    analysis['played_tracks'] += 1
                else:
                    track_info['last_played'] = None
                    analysis['inactive_tracks'] += 1
                
                analysis['track_details'].append(track_info)
            
            # Calculate additional metrics
            analysis.update({
                'average_popularity': sum(t['popularity'] for t in analysis['track_details']) / len(analysis['track_details']),
                'total_duration_ms': sum(t['duration_ms'] for t in analysis['track_details']),
                'explicit_tracks': sum(1 for t in analysis['track_details'] if t['explicit']),
                'preview_available': sum(1 for t in analysis['track_details'] if t['preview_url'])
            })
            
            logger.info(f"Completed analysis for playlist {self.playlist_id}")
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing tracks: {str(e)}")
            raise PlaylistAnalysisError(f"Failed to analyze tracks: {str(e)}")

    def refresh_playlist(self, min_plays: int = 2, inactive_days: int = 30, completion_threshold: int = 40) -> Dict[str, Any]:
        """
        Refresh the playlist based on listening patterns and track metrics.
        Returns detailed analysis of changes made.
        """
        try:
            analysis = self.analyze_tracks()
            tracks = analysis['track_details']
            tracks_to_remove = []
            removal_reasons = defaultdict(list)
            current_time = datetime.now()
            
            for track in tracks:
                track_id = track['id']
                
                # Check inactivity
                if not track['last_played']:
                    added_date = datetime.fromisoformat(track['added_at'].replace('Z', '+00:00'))
                    if (current_time - added_date).days > inactive_days:
                        tracks_to_remove.append(track_id)
                        removal_reasons['inactive'].append(track['name'])
                
                # Check popularity
                if track['popularity'] < 20:
                    tracks_to_remove.append(track_id)
                    removal_reasons['low_popularity'].append(track['name'])
                
                # Check audio features
                if 'energy' in track and track['energy'] < 0.2:
                    tracks_to_remove.append(track_id)
                    removal_reasons['low_energy'].append(track['name'])
            
            # Remove duplicates
            tracks_to_remove.extend(analysis['duplicates'])
            removal_reasons['duplicates'] = analysis['duplicates']
            
            # Get recommendations for removed tracks
            seed_tracks = [track['id'] for track in tracks if track['id'] not in tracks_to_remove][:5]
            recommendations = self.get_recommendations(seed_tracks) if seed_tracks else []
            
            refresh_results = {
                'status': 'success',
                'tracks_analyzed': len(tracks),
                'tracks_removed': len(set(tracks_to_remove)),
                'removal_reasons': dict(removal_reasons),
                'recommendations': len(recommendations),
                'playlist_stats': {
                    'before': {
                        'total_tracks': analysis['total_tracks'],
                        'average_popularity': analysis['average_popularity']
                    }
                }
            }
            
            # Update playlist if tracks should be removed
            if tracks_to_remove:
                self.update_playlist(list(set(tracks_to_remove)), [r['id'] for r in recommendations])
                
                # Get updated stats
                new_analysis = self.analyze_tracks()
                refresh_results['playlist_stats']['after'] = {
                    'total_tracks': new_analysis['total_tracks'],
                    'average_popularity': new_analysis['average_popularity']
                }
            
            logger.info(f"Successfully refreshed playlist {self.playlist_id}")
            return refresh_results
            
        except Exception as e:
            logger.error(f"Error refreshing playlist: {str(e)}")
            return {'status': 'error', 'error': str(e)}

    def get_recommendations(self, seed_tracks: List[str], limit: int = 20) -> List[Dict]:
        """Get track recommendations based on seed tracks with audio feature targeting."""
        try:
            # Get audio features of seed tracks to inform recommendations
            audio_features = self.sp.audio_features(seed_tracks)
            avg_features = {
                'danceability': sum(t['danceability'] for t in audio_features if t) / len(audio_features),
                'energy': sum(t['energy'] for t in audio_features if t) / len(audio_features),
                'tempo': sum(t['tempo'] for t in audio_features if t) / len(audio_features)
            }
            
            recommendations = self.sp.recommendations(
                seed_tracks=seed_tracks[:5],  # Spotify limits to 5 seed tracks
                limit=limit,
                target_danceability=avg_features['danceability'],
                target_energy=avg_features['energy'],
                min_popularity=50  # Ensure recommended tracks have some popularity
            )
            
            logger.info(f"Generated {len(recommendations['tracks'])} recommendations")
            return recommendations['tracks']
            
        except Exception as e:
            logger.error(f"Error getting recommendations: {str(e)}")
            return []

    def update_playlist(self, tracks_to_remove: List[str], tracks_to_add: List[str]) -> bool:
        """Update the playlist by removing and adding tracks."""
        try:
            if tracks_to_remove:
                self.sp.playlist_remove_all_occurrences_of_items(
                    self.playlist_id,
                    tracks_to_remove
                )
                logger.info(f"Removed {len(tracks_to_remove)} tracks from playlist {self.playlist_id}")
            
            if tracks_to_add:
                self.sp.playlist_add_items(
                    self.playlist_id,
                    tracks_to_add
                )
                logger.info(f"Added {len(tracks_to_add)} tracks to playlist {self.playlist_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating playlist: {str(e)}")
            return False

    def get_playlist_metrics(self) -> Dict[str, Any]:
        """Get comprehensive metrics about the playlist."""
        try:
            analysis = self.analyze_tracks()
            
            metrics = {
                'basic_info': {
                    'total_tracks': analysis['total_tracks'],
                    'total_duration': analysis['total_duration_ms'] / (1000 * 60),  # in minutes
                    'average_popularity': analysis['average_popularity']
                },
                'activity': {
                    'played_tracks': analysis['played_tracks'],
                    'inactive_tracks': analysis['inactive_tracks']
                },
                'content': {
                    'explicit_tracks': analysis['explicit_tracks'],
                    'preview_available': analysis['preview_available']
                },
                'distributions': {
                    'popularity': analysis['popularity_distribution'],
                    'artists': dict(sorted(analysis['artist_distribution'].items(), 
                                        key=lambda x: x[1], 
                                        reverse=True)[:10]),  # Top 10 artists
                }
            }
            
            logger.info(f"Generated metrics for playlist {self.playlist_id}")
            return metrics
            
        except Exception as e:
            logger.error(f"Error getting playlist metrics: {str(e)}")
            raise PlaylistAnalysisError(f"Failed to get playlist metrics: {str(e)}")