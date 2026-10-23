# Bilingual recording and MTP comparison

Open `http://JETSON_IP:8090` using your own device address. The video plays and detects real source frames continuously; only preview delivery is limited to about 10 Hz. Recorded replay never replaces the left-hand live video.

## Language

Choose **中文 / English** in the header. Labels, settings, events, accessibility labels and experiment controls switch immediately, and the choice survives refresh. This action does not reset video, tracking, event identity or an ongoing LLM task.

A new demo, manual replay/seek, region or rule change, and a new video upload use the selected language for the new event's analysis. That language is frozen with the event. Historical reports and retries preserve the original language, with an original-language label when necessary.

## Record two independent demos

1. Select a language and **MTP OFF**. Prepare your screen recorder, then click **Start demo**.
2. The video starts at zero, 1× speed, with the existing region and thresholds. A real count trigger saves an event, then the local model executes the tool plan and report.
3. After completion choose **MTP ON** and start another demo for the second recording. No screen recording is performed by this project.
4. **Fullscreen** maximizes the available space. The main layout keeps video left and analysis right; detailed settings and reports use drawers.

The current count is live; the right-hand report analyzes the **frozen trigger moment**, whose count and timestamp are shown above it. A later live frame may have a different count. Automatic looping reuses the event to avoid repeatedly queueing the same response; a manual new demo resets tracking and creates a fresh event.

Movement categories are computed from normalized tracked bottom-center displacement in a recent 3-second window, with at least 0.8 seconds of observation. Low displacement does not establish that someone is standing, loitering or blocking passage. Longest continuous visibility excludes time before the clip and while occluded. The LLM must not infer identity, intent, fighting, falls or scene safety.

## Replay a fair comparison

**History** opens a saved paired benchmark. Choose a pair and click **Play pipeline**. Both traces share the original clock; only text actually produced by that timestamp is visible. `Recorded Run Replay` remains visible. Main-screen live counts and the current production report retain their own clocks and event identity.

**Statistics & raw records** shows every attempt, server metrics and ZIP export. Starting a benchmark uses the selected frozen event, pauses detection computation for exclusive model use, alternates OFF→ON / ON→OFF, restarts and warms up each mode, and requires at least five valid results per mode and matching request hashes. Ordinary live responses and trace replay do not pause detection.

Model loading, first-token latency, decision, report generation, tools and complete task time are separate. Token counts / decode / acceptance come from server data; missing values are N/A. Two separate video recordings are demonstrations, not a substitute for same-input paired measurements.

## Evidence and troubleshooting

- **Settings:** ROI, thresholds, recovery, cooldown, video, playback and count CSV.
- **Events:** original snapshot, real tool receipts, acknowledgement, report download, retry and cancellation.
- **History → Statistics & raw records:** all benchmark attempts and JSON / CSV / Trace export.
- On the device, `data/sessions/`, `data/snapshots/`, `data/reports/`, `data/agent/`, `data/benchmarks/` and `data/crowd.sqlite` retain the original evidence. These runtime files are not part of the source repository.

See [troubleshooting](troubleshooting.md) for deployment problems.
