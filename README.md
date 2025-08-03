

## Endpoints

### 🎵 Enhanced Music Suggestion API

A FastAPI-based service that provides personalized music suggestions using the YouTube Data API v3. The API analyzes your liked songs and suggests similar music, with a fallback to popular songs when no matches are found.

## ✨ Features
```

#### Example Response
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

#### Response Codes
- `200`: Successful response with suggestions.
- `404`: No suggestions found for the given song.
- `500`: Server error or API key not configured.

---

### 2. Health Check

- **Endpoint:** `/health`
- **Method:** GET
- **Description:** Checks if the API is running.

#### Example Request
```
curl -X GET "https://song-suggest-microservice.onrender.com//health"
```

#### Example Response
```
{
  "status": "healthy"
}
```

---

## Frontend Integration

### Prerequisites
- Ensure you have a valid **YouTube Data API key** set as an environment variable (`YOUTUBE_API_KEY`) on Render.

### JavaScript Example (Frontend)
```
async function getMusicSuggestions(songName) {
  try {
    const response = await fetch(`https://song-suggest-microservice.onrender.com//suggestions?song_name=${encodeURIComponent(songName)}`);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    return data.suggestions;
  } catch (error) {
    console.error('Error fetching suggestions:', error);
    return [];
  }
}

// Usage
getMusicSuggestions("Bohemian Rhapsody").then(suggestions => {
  console.log(suggestions);
});
```

---

## CORS Policy
- The API currently allows CORS from all origins (`*`) for development convenience.
- For production, update the `allow_origins` in the CORS middleware to restrict access to only your frontend domains.

---

## Deployment on Render

1. **Create a Render Account:** Sign up at [render.com](https://render.com/).
2. **Create a New Web Service:** Choose **Python** as the runtime.
3. **Set the Start Command:**
   ```
   uvicorn main:app --host 0.0.0.0 --port $PORT
   ```
4. **Add Environment Variables:**
   - `YOUTUBE_API_KEY`: Your YouTube Data API key.
   - `PORT`: Automatically set by Render (usually `10000`).
5. **Add Requirements:** Use the provided `requirements.txt` file.
6. **Deploy:**
   - Push your code to a GitHub repository.
   - Connect the repository to Render and deploy.


