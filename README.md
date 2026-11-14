# Video Studio — GitHub Actions

A small manual video creator. Enter a topic and your own narration, then run the GitHub Actions workflow. It searches Wikimedia Commons for reusable images, creates slides, synthesizes speech with eSpeak NG, and renders an MP4 with FFmpeg.

## Setup

1. Create a GitHub repository named `video-studio`.
2. Upload the contents of this folder to the repository's default branch.
3. Open **Actions** and enable workflows if GitHub asks.
4. Select **Create video** → **Run workflow**.
5. Enter a topic and narration (at least 40 characters), choose portrait or landscape, then run it.
6. When the run finishes, open its summary and download the `video-<run number>` artifact. It contains `video.mp4` and `credits.txt`.

## Important

- This first version does not invent factual narration with AI. You provide the narration text yourself; the workflow reads it aloud.
- Images are found through Wikimedia Commons. Check `credits.txt` and each file's license before publishing. Attribution is included in the output.
- eSpeak NG is a basic synthetic voice, not a studio-quality neural voice.
- GitHub Actions has usage limits. A free public repository can use standard GitHub-hosted runners without charge under GitHub's current policy, but verify current plan limits before heavy use.
- Do not put passwords, private keys, or personal data into workflow inputs.
