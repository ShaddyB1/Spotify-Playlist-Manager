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

    def get_audio_features_batch(self, track_ids: List[str]) -> Dict[str, float]:
        """Get audio features for multiple tracks in one request."""
        try:
         
            features_dict = {}
            for i in range(0, len(track_ids), 100):
                batch = track_ids[i:i+100]
                
              
                time.sleep(1)  
                
                features = self.sp.audio_features(batch)
                
                
                for track_id, feature in zip(batch, features):
                    if feature:
                        features_dict[track_id] = feature.get('energy', 0.0)
                    else:
                        features_dict[track_id] = 0.0
                        
            return features_dict
        except Exception as e:
            logger.error(f"Error getting audio features for batch: {str(e)}")
            return {track_id: 0.0 for track_id in track_ids}

    def get_energy(self, track_id: str) -> float:
        """Get energy level for a single track."""
        try:
            features = self.get_audio_features_batch([track_id])
            return features.get(track_id, 0.0)
        except Exception as e:
            logger.error(f"Error getting energy for track {track_id}: {str(e)}")
            return 0.0

    def convert_to_serializable(self, data):
        """Convert complex data types to serializable Python types."""
        if isinstance(data, defaultdict):
            return dict(data)
        elif isinstance(data, (set, type({}.items()))):  
            return list(data)
        elif isinstance(data, dict):
            return {k: self.convert_to_serializable(v) for k, v in data.items()}
        elif isinstance(data, (list, tuple)):
            return [self.convert_to_serializable(x) for x in data]
        return data


    


    
    def optimize_playlist(self, criteria: Dict[str, Any]) -> Dict[str, Any]:
        """Optimize playlist based on given criteria."""
        try:
            logger.info(f"Starting playlist optimization with criteria: {criteria}")
            
            
            analysis = self.analyze_tracks()
            
            if not analysis['track_details']:
                raise PlaylistAnalysisError("No tracks found in playlist")
                
            tracks_to_remove = []
            for track in analysis['track_details']:
                reasons = []
                
                
                min_popularity = int(criteria.get('minPopularity', 30))
                if track['popularity'] < min_popularity:
                    reasons.append(f"Low popularity ({track['popularity']}%)")
                
                min_energy = float(criteria.get('minEnergy', 0.2))
                if track['energy'] < min_energy:
                    reasons.append(f"Low energy ({track['energy']*100:.0f}%)")
                    
                if reasons:
                    tracks_to_remove.append({
                        'id': track['id'],
                        'name': track['name'],
                        'artist': track['artists'][0] if track['artists'] else 'Unknown Artist',
                        'popularity': track['popularity'],
                        'energy': track['energy'],
                        'reasons': reasons
                    })
            
            
            removed_tracks = []
            if criteria.get('autoRemove'):
                track_uris = [f"spotify:track:{track['id']}" for track in tracks_to_remove]
                
               
                for i in range(0, len(track_uris), 100):
                    batch = track_uris[i:i+100]
                    try:
                        self.sp.playlist_remove_all_occurrences_of_items(self.playlist_id, batch)
                        removed_tracks.extend(batch)
                    except Exception as e:
                        logger.error(f"Error removing batch of tracks: {str(e)}")
            
            result = {
                'tracksAnalyzed': len(analysis['track_details']),
                'tracksToRemove': tracks_to_remove,
                'tracksRemoved': len(removed_tracks) if criteria.get('autoRemove') else 0,
                'criteriaUsed': {
                    'minPopularity': min_popularity,
                    'minEnergy': min_energy,
                    'autoRemove': criteria.get('autoRemove', False)
                },
                'playlistName': analysis.get('playlist_name', '')
            }
            
            logger.info(f"Optimization complete. Found {len(tracks_to_remove)} tracks to remove.")
            return self.convert_to_serializable(result)
            
        except Exception as e:
            logger.error(f"Optimization error: {str(e)}", exc_info=True)
            raise PlaylistAnalysisError(f"Failed to optimize playlist: {str(e)}")

    

    def analyze_tracks(self) -> Dict[str, Any]:
        """Analyze tracks for potential removal based on multiple factors."""
        try:
            # Get playlist info first
            logger.info("Getting playlist information")
            playlist_info = self.sp.playlist(self.playlist_id, fields='name')
            
            logger.info("Starting get_playlist_tracks")
            tracks = self.get_playlist_tracks()
            logger.info(f"Retrieved {len(tracks)} tracks")
            
            logger.info("Getting recently played tracks")
            recent_plays = self.sp.current_user_recently_played(limit=50)
            logger.info(f"Retrieved {len(recent_plays['items'])} recent plays")
            
            # lookup for recently played tracks
            recent_plays_lookup = {
                item['track']['id']: {
                    'played_at': datetime.fromisoformat(item['played_at'].replace('Z', '+00:00')),
                    'context': item.get('context')
                } for item in recent_plays['items']
            }
            
            # Initialize analysis dictionary with default values
            analysis = {
                'playlist_name': playlist_info.get('name', 'Untitled Playlist'),
                'total_tracks': len(tracks),
                'played_tracks': 0,
                'skipped_tracks': 0,
                'inactive_tracks': 0,
                'duplicates': [],
                'track_details': [],
                'genre_distribution': defaultdict(int),
                'artist_distribution': defaultdict(int),
                'popularity_distribution': defaultdict(int),
                'decade_distribution': defaultdict(int),
                'total_duration_ms': 0,
                'explicit_tracks': 0,
                'preview_available': 0
            }
            
            logger.info("Starting track analysis loop")
            track_ids = set()
            
            for i, track_item in enumerate(tracks):
                try:
                    track = track_item.get('track')
                    if not track:
                        logger.warning(f"Skipping track at index {i} - no track data")
                        continue
                    
                    track_id = track.get('id')
                    if not track_id:
                        logger.warning(f"Skipping track at index {i} - no track ID")
                        continue
                    
                    # duplicates
                    if track_id in track_ids:
                        analysis['duplicates'].append(track.get('name', 'Unknown Track'))
                    track_ids.add(track_id)
                    
                   
                    energy = self.get_energy(track_id)
                    
                    # track info dictionary
                    track_info = {
                        'id': track_id,
                        'name': track.get('name', 'Unknown Track'),
                        'artists': [artist.get('name', 'Unknown Artist') for artist in track.get('artists', [])],
                        'added_at': track_item.get('added_at', ''),
                        'popularity': track.get('popularity', 0),
                        'duration_ms': track.get('duration_ms', 0),
                        'explicit': track.get('explicit', False),
                        'preview_url': track.get('preview_url'),
                        'energy': energy,
                        'album': track.get('album', {}).get('name', 'Unknown Album'),
                        'release_date': track.get('album', {}).get('release_date', '')
                    }
                    
                   
                    popularity_bracket = (track_info['popularity'] // 10) * 10
                    analysis['popularity_distribution'][popularity_bracket] += 1
                    
                    for artist in track_info['artists']:
                        analysis['artist_distribution'][artist] += 1
                    
                 
                    if track_info['release_date']:
                        try:
                            year = int(track_info['release_date'][:4])
                            decade = (year // 10) * 10
                            analysis['decade_distribution'][decade] += 1
                        except (ValueError, TypeError):
                            pass
                    
                    # Check recent plays
                    if track_id in recent_plays_lookup:
                        track_info['last_played'] = recent_plays_lookup[track_id]['played_at'].isoformat()
                        analysis['played_tracks'] += 1
                    else:
                        track_info['last_played'] = None
                        analysis['inactive_tracks'] += 1
                    
                   
                    analysis['total_duration_ms'] += track_info['duration_ms']
                    if track_info['explicit']:
                        analysis['explicit_tracks'] += 1
                    if track_info['preview_url']:
                        analysis['preview_available'] += 1
                    
                    analysis['track_details'].append(track_info)
                    
                except Exception as track_error:
                    logger.error(f"Error processing track at index {i}: {str(track_error)}")
                    continue
            
            # Calculate averages and percentages
            track_count = len(analysis['track_details'])
            if track_count > 0:
                analysis.update({
                    'average_popularity': sum(t['popularity'] for t in analysis['track_details']) / track_count,
                    'average_energy': sum(t['energy'] for t in analysis['track_details']) / track_count,
                    'explicit_percentage': (analysis['explicit_tracks'] / track_count) * 100,
                    'preview_percentage': (analysis['preview_available'] / track_count) * 100,
                    'active_percentage': (analysis['played_tracks'] / track_count) * 100
                })
            else:
                analysis.update({
                    'average_popularity': 0,
                    'average_energy': 0,
                    'explicit_percentage': 0,
                    'preview_percentage': 0,
                    'active_percentage': 0
                })
            
           
            final_analysis = self.convert_to_serializable(analysis)
            
            # Sort distributions by value
            for dist_key in ['artist_distribution', 'popularity_distribution', 'decade_distribution']:
                if dist_key in final_analysis:
                    final_analysis[dist_key] = dict(sorted(
                        final_analysis[dist_key].items(),
                        key=lambda x: x[1],
                        reverse=True
                    ))
            
            logger.info(f"Completed analysis for playlist {self.playlist_id}")
            return final_analysis
            
        except Exception as e:
            logger.error(f"Error analyzing tracks: {str(e)}", exc_info=True)
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
            
           
            avg_energy = sum(audio_features) / len(audio_features) if audio_features else 0.5
            
      
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

    def verify_playlist(self) -> bool:
        """Verify that the playlist exists and is accessible."""
        try:
            playlist = self.sp.playlist(self.playlist_id, fields='id,name')
            return bool(playlist and playlist.get('id'))
        except Exception as e:
            logger.error(f"Error verifying playlist {self.playlist_id}: {str(e)}")
            return False

    

    def add_similar_tracks(self, track_ids: List[str]) -> bool:
        """Add similar tracks to the playlist."""
        try:
            track_uris = [f"spotify:track:{track_id}" for track_id in track_ids]
            
            for i in range(0, len(track_uris), 100):  
                batch = track_uris[i:i+100]
                self.sp.playlist_add_items(self.playlist_id, batch)
            
            return True
        except Exception as e:
            logger.error(f"Error adding similar tracks: {str(e)}")
            raise
