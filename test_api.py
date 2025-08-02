#!/usr/bin/env python3
"""
Test script for the YouTube Music Suggestion API
"""
import requests
import json

# API base URL (adjust if running on different host/port)
BASE_URL = "http://localhost:8000"

def test_health_check():
    """Test the health check endpoint"""
    try:
        response = requests.get(f"{BASE_URL}/health")
        print(f"Health Check Status: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"Health check failed: {e}")
        return False

def test_suggestions():
    """Test the suggestions endpoint"""
    test_data = {
        "user_id": "test_user_123",
        "songs": ["Shape of You", "Blinding Lights", "Watermelon Sugar"]
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/suggestions",
            json=test_data,
            headers={"Content-Type": "application/json"}
        )
        print(f"\nSuggestions Status: {response.status_code}")
        
        if response.status_code == 200:
            suggestions = response.json()
            print("✅ Suggestions received successfully!")
            print(f"Number of suggestions: {len(suggestions.get('suggestions', []))}")
            
            for i, suggestion in enumerate(suggestions.get('suggestions', [])[:3], 1):
                print(f"{i}. {suggestion.get('title')} by {suggestion.get('artist')}")
                print(f"   YouTube ID: {suggestion.get('youtube_video_id')}")
                print(f"   Score: {suggestion.get('score')}")
        else:
            print(f"❌ Error: {response.status_code}")
            print(f"Response: {response.text}")
            
    except Exception as e:
        print(f"Suggestions test failed: {e}")

def test_liked_songs():
    """Test the liked songs endpoint"""
    try:
        response = requests.get(f"{BASE_URL}/liked-songs?user_id=test_user_123")
        print(f"\nLiked Songs Status: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Liked songs test failed: {e}")

if __name__ == "__main__":
    print("🎵 Testing YouTube Music Suggestion API")
    print("=" * 50)
    
    # Test health check first
    if test_health_check():
        print("✅ API server is running!")
        
        # Test other endpoints
        test_suggestions()
        test_liked_songs()
    else:
        print("❌ API server is not responding. Make sure it's running on localhost:8000")
        print("\nTo start the server, run:")
        print("uvicorn main:app --reload --host 0.0.0.0 --port 8000")
