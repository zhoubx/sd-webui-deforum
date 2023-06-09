import os
import cv2
import shutil
import math
import requests
import subprocess
from pkg_resources import resource_filename
from modules.shared import state

def vid2frames(video_path, video_in_frame_path, n=1, overwrite=True, extract_from_frame=0, extract_to_frame=-1, out_img_format='jpg', numeric_files_output = False): 
    if (extract_to_frame <= extract_from_frame) and extract_to_frame != -1:
        raise RuntimeError('Error: extract_to_frame can not be higher than extract_from_frame')
    
    if n < 1: n = 1 #HACK Gradio interface does not currently allow min/max in gr.Number(...) 

    # check vid path using a function and only enter if we get True
    if is_vid_path_valid(video_path):
        
        name = get_frame_name(video_path)
        
        vidcap = cv2.VideoCapture(video_path)
        video_fps = vidcap.get(cv2.CAP_PROP_FPS)

        input_content = []
        if os.path.exists(video_in_frame_path) :
            input_content = os.listdir(video_in_frame_path)

        # check if existing frame is the same video, if not we need to erase it and repopulate
        if len(input_content) > 0:
            #get the name of the existing frame
            content_name = get_frame_name(input_content[0])
            if not content_name.startswith(name):
                overwrite = True

        # grab the frame count to check against existing directory len 
        frame_count = int(vidcap.get(cv2.CAP_PROP_FRAME_COUNT)) 
        
        # raise error if the user wants to skip more frames than exist
        if n >= frame_count : 
            raise RuntimeError('Skipping more frames than input video contains. extract_nth_frames larger than input frames')
        
        expected_frame_count = math.ceil(frame_count / n) 
        # Check to see if the frame count is matches the number of files in path
        if overwrite or expected_frame_count != len(input_content):
            shutil.rmtree(video_in_frame_path)
            os.makedirs(video_in_frame_path, exist_ok=True) # just deleted the folder so we need to make it again
            input_content = os.listdir(video_in_frame_path)
        
        print(f"Trying to extract frames from video with input FPS of {video_fps}. Please wait patiently.")
        if len(input_content) == 0:
            vidcap.set(cv2.CAP_PROP_POS_FRAMES, extract_from_frame) # Set the starting frame
            success,image = vidcap.read()
            count = extract_from_frame
            t=1
            success = True
            while success:
                if state.interrupted:
                    return
                if (count <= extract_to_frame or extract_to_frame == -1) and count % n == 0:
                    if numeric_files_output == True:
                        cv2.imwrite(video_in_frame_path + os.path.sep + f"{t:05}.{out_img_format}" , image) # save frame as file
                    else:
                        cv2.imwrite(video_in_frame_path + os.path.sep + name + f"{t:05}.{out_img_format}" , image) # save frame as file
                    t += 1
                success,image = vidcap.read()
                count += 1
            print(f"Successfully extracted {count} frames from video.")
        else:
            print("Frames already unpacked")
        vidcap.release()
        return video_fps

# make sure the video_path provided is an existing local file or a web URL with a supported file extension
def is_vid_path_valid(video_path):
    # make sure file format is supported!
    file_formats = ["mov", "mpeg", "mp4", "m4v", "avi", "mpg", "webm"]
    extension = video_path.rsplit('.', 1)[-1].lower()
    # vid path is actually a URL, check it 
    if video_path.startswith('http://') or video_path.startswith('https://'):
        response = requests.head(video_path)
        if response.status_code == 404 or response.status_code != 200:
            raise ConnectionError("Video URL is not valid. Response status code: {}".format(response.status_code))
        if extension not in file_formats:
            raise ValueError("Video file format '{}' not supported. Supported formats are: {}".format(extension, file_formats))
    else:
        if not os.path.exists(video_path):
            raise RuntimeError("Video path does not exist.")
        if extension not in file_formats:
            raise ValueError("Video file format '{}' not supported. Supported formats are: {}".format(extension, file_formats))
    return True

# quick-retreive just the frame count and FPS of a video (local or URL-based)    
def get_quick_vid_info(vid_local_path):
    vidcap = cv2.VideoCapture(vid_local_path)
    video_fps = vidcap.get(cv2.CAP_PROP_FPS)
    video_frame_count = int(vidcap.get(cv2.CAP_PROP_FRAME_COUNT)) 
    video_width = int(vidcap.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_height = int(vidcap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    vidcap.release()
    if video_fps.is_integer():
        video_fps = int(video_fps)

    return video_fps, video_frame_count, (video_width, video_height)
    
# Stitch images to a h264 mp4 video using ffmpeg
def ffmpeg_stitch_video(ffmpeg_location=None, fps=None, outmp4_path=None, stitch_from_frame=0, stitch_to_frame=None, imgs_path=None, add_soundtrack=None, audio_path=None, crf=17, preset='veryslow'):
    # TODO: add audio custom print msgs for a nice user experience
    print(f"Trying to stitch video from frames using FFMPEG:\nFrames:\n{imgs_path}\nTo Video:\n{outmp4_path}")
    try:
        cmd = [
            ffmpeg_location,
            '-y',
            '-vcodec', 'png',
            '-r', str(int(fps)),
            '-start_number', str(stitch_from_frame),
            '-i', imgs_path,
            '-frames:v', str(stitch_to_frame),
            '-c:v', 'libx264',
            '-vf',
            f'fps={int(fps)}',
            '-pix_fmt', 'yuv420p',
            '-crf', str(crf),
            '-preset', preset,
            '-pattern_type', 'sequence',
            outmp4_path
        ]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
    except FileNotFoundError:
        raise FileNotFoundError("FFmpeg not found. Please make sure you have a working ffmpeg path under 'ffmpeg_location' parameter.")
    except Exception as e:
        raise Exception(f'Error stitching frames to video. Actual runtime error:{e}')

    if add_soundtrack != 'None':
        try:
            cmd = [
                ffmpeg_location,
                '-i',
                outmp4_path,
                '-i',
                audio_path,
                '-map', '0:v',
                '-map', '1:a',
                '-c:v', 'copy',
                '-shortest',
                outmp4_path+'.temp.mp4'
            ]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate()
            if process.returncode != 0:
                print(stderr)
                raise RuntimeError(stderr)
            os.replace(outmp4_path+'.temp.mp4', outmp4_path)
        except Exception as e:
            print(f'Error adding audio to video. Actual error: {e}')
    # If we reached this point, all ok. Let the user know!
    print("FFMPEG Video Stitching done!")

def get_frame_name(path):
    name = os.path.basename(path)
    name = os.path.splitext(name)[0]
    return name
    
def get_next_frame(outdir, video_path, frame_idx, mask=False):
    frame_path = 'inputframes'
    if (mask): frame_path = 'maskframes'
    return os.path.join(outdir, frame_path, get_frame_name(video_path) + f"{frame_idx+1:05}.jpg")
     
def find_ffmpeg_binary():
    for package in ['imageio_ffmpeg', 'imageio-ffmpeg']:
        try:
            package_path = resource_filename(package, 'binaries')
            files = [os.path.join(package_path, f) for f in os.listdir(package_path) if f.startswith("ffmpeg-")]
            files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            return files[0] if files else 'ffmpeg'
        except:
            return 'ffmpeg'