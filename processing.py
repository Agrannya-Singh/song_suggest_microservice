# ==============================================================================
# BACKGROUND PROCESSING LOGIC
# ==============================================================================
# This module contains the core recommendation logic that is executed as a
# background task. It is responsible for fetching song data, calculating a
# user's "taste profile", finding similar songs, and saving the final
# recommendations to the database.
# ------------------------------------------------------------------------------

# --- Imports ---
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy.orm import Session

# Import our own modules.
import spotify_client
from models import Song, Recommendation

def generate_and_save_recommendations(user_id: str, song_names: list[str], db: Session):
    """
    The main background task function.

    This function orchestrates the entire recommendation process, from fetching
    data to saving the final results. It's designed to be called by FastAPI's
    `BackgroundTasks`.

    Args:
        user_id (str): The ID of the user requesting recommendations.
        song_names (list[str]): The list of songs liked by the user.
        db (Session): The database session provided by the API endpoint.
    """
    print(f"INFO: Background task started for user: {user_id}")

    try:
        # --- Step 1: Get audio features for all liked songs ---
        liked_song_features = []
        for song_name in song_names:
            # Check if the song is already cached in our database.
            db_song = db.query(Song).filter(Song.name.ilike(f"%{song_name}%")).first()

            # If not in the database, fetch it from Spotify.
            if not db_song:
                print(f"INFO: '{song_name}' not in DB. Searching Spotify...")
                spotify_song = spotify_client.search_for_song(song_name)

                if spotify_song:
                    features = spotify_client.get_audio_features(spotify_song["spotify_id"])
                    if features:
                        # Create a new Song object and save it to the database.
                        db_song = Song(
                            spotify_id=spotify_song["spotify_id"],
                            name=spotify_song["name"],
                            artist=spotify_song["artist"],
                            **features
                        )
                        db.add(db_song)
                        db.commit()
                        db.refresh(db_song)
                        print(f"INFO: Saved '{db_song.name}' to DB.")

            # If we have the song (either from DB or newly fetched), add its features.
            if db_song and db_song.danceability is not None:
                liked_song_features.append([
                    db_song.danceability, db_song.energy, db_song.valence, db_song.tempo
                ])

        if not liked_song_features:
            print(f"ERROR: Could not find features for any liked songs for user {user_id}.")
            return # End the task if no data could be found.

        # --- Step 2: Create the user's "taste profile" vector ---
        # This vector is the average of the features of all their liked songs.
        taste_profile = np.mean(np.array(liked_song_features), axis=0).reshape(1, -1)

        # --- Step 3: Find candidate songs for recommendation ---
        # For simplicity, we use all other songs in our database as candidates.
        liked_song_db_names = [s.lower() for s in song_names]
        candidates = db.query(Song).filter(Song.name.notin_(liked_song_db_names)).limit(500).all()

        if not candidates:
            print(f"WARN: No other songs in DB to use as candidates for user {user_id}.")
            return

        candidate_features_list = []
        valid_candidates = []
        for c in candidates:
            # Ensure the candidate has all necessary features.
            if all([c.danceability, c.energy, c.valence, c.tempo]):
                candidate_features_list.append([c.danceability, c.energy, c.valence, c.tempo])
                valid_candidates.append(c)

        if not valid_candidates:
            print(f"WARN: No valid candidates with full feature sets found for user {user_id}.")
            return

        candidate_features = np.array(candidate_features_list)

        # --- Step 4: Calculate similarity and find top matches ---
        # Cosine similarity measures the "angle" between the taste profile and each
        # candidate song's vector. A score closer to 1 means more similar.
        sim_scores = cosine_similarity(taste_profile, candidate_features)[0]

        # Get the indices of the top 5 most similar songs.
        top_indices = np.argsort(sim_scores)[::-1][:5]

        # --- Step 5: Save the results to the database ---
        # First, clear any old recommendations for this user.
        db.query(Recommendation).filter(Recommendation.user_id == user_id).delete()
        db.commit()

        # Save the new recommendations.
        for i in top_indices:
            song = valid_candidates[i]
            score = sim_scores[i]
            new_rec = Recommendation(
                user_id=user_id,
                song_name=song.name,
                artist_name=song.artist,
                score=float(score)
            )
            db.add(new_rec)

        db.commit()
        print(f"SUCCESS: Saved 5 new recommendations for user {user_id}.")

    except Exception as e:
        # Log any unexpected errors that occur during the task.
        print(f"FATAL ERROR in background task for user {user_id}: {e}")
        # Rollback any partial database changes.
        db.rollback()

