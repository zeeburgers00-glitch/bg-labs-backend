# Music Library for Shorts Creator

This directory contains background music tracks for use in the shorts creator project. All music files are sourced from the YouTube audio library, and are free to use under their license. You can use this audio track in any of your videos, including videos that you monetize. No attribution is required.

## Music Collection

The music is categorized by mood to match the `MusicMoodEnum` in the project:

## Mood Categories

The following moods are defined in the project's `MusicMoodEnum`:

- sad
- melancholic
- happy
- euphoric/high
- excited
- chill
- uneasy
- angry
- dark
- hopeful
- contemplative
- funny/quirky

## How to Add New Music

To add new music to the project:

1. Add your MP3 file to this directory (`static/music/`)
2. Update the `src/short-creator/music.ts` file by adding a new record to the `musicList` array:

```typescript
{
  file: "your-new-music-file.mp3",  // Filename of your MP3
  start: 5,                        // Start time in seconds (when to begin playing)
  end: 30,                          // End time in seconds (when to stop playing)
  mood: MusicMoodEnum.happy,        // Mood tag for the music
}
```

## Usage

The shorts creator uses these mood tags to filter and match appropriate music with video content. Choose tags carefully to ensure proper matching between music mood and video content.
