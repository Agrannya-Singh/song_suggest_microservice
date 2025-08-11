---

# 🎵 Enhanced Music Suggestion API

A FastAPI microservice that provides music suggestions using the YouTube Data API v3. The service analyzes a user's liked songs and returns similar tracks. It includes robust fallback mechanisms to always return relevant results when possible.

Production URL: https://song-suggest-microservice.onrender.com

---

## ✅ API Contract (Unchanged)

The REST API remains the same. No frontend changes are required.

1) POST /suggestions
- Description: Get song suggestions based on multiple liked songs for a user.
- Request body (JSON):
```
{
  "user_id": "user-123",
  "songs": ["Shape of You", "Blinding Lights", "Watermelon Sugar"]
}
```
- Response (200):
```
{
  "suggestions": [
    {
      "title": "Queen - Somebody To Love",
      "artist": "Queen Official",
      "youtube_video_id": "kijpcUv-b8M"
    }
    // ... more suggestions
  ]
}
```
- Errors: 400 (bad input), 404 (no matches and fallback failed), 500 (configuration)

2) GET /liked-songs?user_id=xxx
- Returns the list of liked songs stored for the given user.

3) GET /health
- Returns `{ "status": "healthy" }` if the service is running.

---

## 🔍 ML Suggestion Engine (Overview)

Goal: Provide high‑quality, low‑latency song recommendations using only the YouTube Data API and lightweight in‑process modeling.

Core approach: Content‑based ranking with TF‑IDF over YouTube metadata
- Seed selection: For each input song string, the service searches YouTube (music category) and picks the top relevant video as the seed.
- Related candidates: Uses YouTube's related videos API to retrieve candidate music videos.
- Batch enrichment: Fetches candidate details in a single batch call (snippet, statistics, contentDetails) to minimize latency.
- Text features: Builds a text corpus from title + channel name + description + tags.
- TF‑IDF similarity: Computes TF‑IDF vectors and cosine similarity between the seed text and each candidate's text.
- Heuristic score: Combines content similarity with metadata signals such as:
  - Official video phrases in title
  - Word overlap with seed title
  - Same channel as seed
  - View count scaling (light popularity prior)
- Aggregation: Merges suggestions across multiple liked songs, deduplicates by video ID and title, sorts by score, and returns the top 5.

Caching and latency optimizations
- Per‑request in‑process cache with TTL for combined suggestions.
- Function‑level LRU cache for per‑song suggestion results.
- Batch video details fetch to reduce round trips to YouTube.

Fallback mechanisms
- If no suggestions are found across all liked songs, the service fetches from YouTube's most popular music videos (category 10). It prefers videos with high view counts and returns a high‑confidence popular track.
- If even the popular feed is unavailable, the API returns a 404 with a clear error message.

Persistence
- Liked songs are saved per user via SQLAlchemy using SQLite by default. This is swappable to Postgres by setting `DATABASE_URL` without code changes. The API surface remains unchanged.

---

## 🔌 Usage Examples

curl (POST /suggestions)
```
curl -X POST \
  https://song-suggest-microservice.onrender.com/suggestions \
  -H "Content-Type: application/json" \
  -d '{
        "user_id": "demo-user",
        "songs": ["Blinding Lights", "Shape of You"]
      }'
```

curl (GET /liked-songs)
```
curl "https://song-suggest-microservice.onrender.com/liked-songs?user_id=demo-user"
```

curl (GET /health)
```
curl "https://song-suggest-microservice.onrender.com/health"
```

---

## 🌐 Frontend Integration

No changes required on the frontend. Continue calling the same endpoints and parsing the same JSON structure. Example (fetch):
```
async function getSuggestions(userId, songs) {
  const res = await fetch("https://song-suggest-microservice.onrender.com/suggestions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, songs })
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return data.suggestions;
}
```

---

## ⚙️ Configuration

Environment variables (Render -> Environment)
- YOUTUBE_API_KEY: Required.
- DATABASE_URL: Optional (defaults to SQLite `sqlite:///app.db`). For Render Postgres, provide the full connection URL.

Start command (Render)
```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Dependencies
- See `requirements.txt`. Includes SQLAlchemy and scikit‑learn for the ranking logic.

CORS
- CORS is set to allow all origins by default for ease of integration. Restrict in production as needed.

---

## 🚀 Deployment Notes for Render

- Ensure YOUTUBE_API_KEY is set as a secret.
- If using Render Postgres, set DATABASE_URL accordingly.
- Build and runtime are standard; scikit‑learn is included for TF‑IDF and cosine similarity. Render will build wheels automatically; no extra steps typically required.

---

## 🔎 Health Check
```
GET https://song-suggest-microservice.onrender.com/health
Response: { "status": "healthy" }
