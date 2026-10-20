# Local animated avatars

David and Lucy use small, silent H.264 MP4 loops at their original playback speed.
The square portrait clips fit the existing frames without horizontal stretching.
The original sprite portraits remain as the fallback if video loading fails.

The **Pause animation** button, motion checkbox, OS reduced-motion preference and
hidden-window state pause video playback. Resuming animation resumes the same clip.
The animation is decorative: task/session status always comes from real telemetry.

Only `/assets/david.mp4` and `/assets/lucy.mp4` are allowed by the HTTP and native
host resource lists. CSP allows media from this same local origin. Clips are checked
against exact SHA-256 pins and a 2 MiB limit; frozen bundles include both clips.
Missing or changed clips fail bundle creation/verification. Remote video URLs and
arbitrary archive entries are not supported.

User-supplied media stays in the private `.runtime` asset directory, outside Git.
For this installation David is a CPU-transcoded 256×256 crop of the supplied
25-second video. Lucy is a 192×192, 2-second loop made from the supplied archive's
animated `preview.gif`. No wallpaper engine, shader, installer or archive code is
executed. Conversion reads the supplied downloads without modifying them; the
accepted runtime uses the pinned derived clips in private storage.

Source changes require the existing current-content tests, independent review and
fixed-snapshot activation. A successful local preview does not activate a release.
