import moviepy.editor as mp
import os

def compress_video(input_file, output_file, target_size_mb):
    # Load the video
    video = mp.VideoFileClip(input_file)

    # Calculate the target bitrate in bits per second
    target_bitrate = (target_size_mb * 8 * 1024 * 1024) / video.duration

    # Set the codec to 'libx264' and use the target bitrate
    video.write_videofile(
    output_file,
    codec='libx264',
    bitrate=f'{int(target_bitrate)}k',
    ffmpeg_params=['-crf', '18', '-preset', 'medium']
)

    print(f"Video compressed and saved as: {output_file}")

if __name__ == "__main__":
    input_path = "video_file.mov"  # Path to the input video file
    output_path = "video_file.mov"  # Path where the compressed video will be saved
    target_size = 32  # Target size in MB

    compress_video(input_path, output_path, target_size)

