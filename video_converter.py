import os
from pathlib import Path
from moviepy.editor import VideoFileClip

def convert_video_to_mp3(video_path: str | Path) -> str | None:
    abs_video = str(Path(video_path).resolve().absolute())
    abs_mp3 = str(Path(video_path).with_suffix('.mp3').resolve().absolute())
    
    video_clip = None
    try:
        video_clip = VideoFileClip(abs_video)
        
        # Check if the video actually has an audio track
        if video_clip.audio is None:
            video_clip.close()
            return None
            
        # Extract audio and write to mp3. logger=None prevents console spam.
        video_clip.audio.write_audiofile(abs_mp3, logger=None)
        
        # CRITICAL: Close clips to release file locks
        video_clip.audio.close()
        video_clip.close()
        video_clip = None # Ensure reference is cleared
        
        # Delete original video file to save space
        Path(abs_video).unlink(missing_ok=True)
        
        return abs_mp3
        
    except Exception as e:
        print(f"Failed to convert video {abs_video}: {e}")
        if video_clip is not None:
            try:
                video_clip.close()
            except:
                pass
        return None
