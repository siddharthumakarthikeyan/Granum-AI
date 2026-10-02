/** Generated caption timing follows encoded media, not the automation wall clock. */
import { spawnSync } from "node:child_process";
import { readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

export function videoDuration(file) {
  // FFmpeg is a recording prerequisite; do not assume a separate ffprobe binary exists.
  const probe = spawnSync("ffmpeg", ["-hide_banner", "-i", file, "-t", "0", "-f", "null", "-"], { encoding: "utf8" });
  if (probe.status !== 0) throw new Error(probe.stderr || String(probe.error));
  const match = probe.stderr.match(/Duration: (\d+):(\d+):([\d.]+)/);
  if (!match) throw new Error(`No encoded duration for ${file}`);
  return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]);
}

const stamp = seconds => new Date(Math.round(seconds * 1000)).toISOString().slice(11, 23);

export async function publishTiming(output, capture) {
  const duration = videoDuration(path.join(output, `${capture.chapter}.mp4`));
  const captureDuration = capture.capture_duration ?? capture.duration;
  const capturedCues = capture.captured_cues ?? capture.cues;
  const cues = capturedCues.map(cue => ({ ...cue, at: cue.at * duration / captureDuration }));
  const metadata = { ...capture, duration, capture_duration: captureDuration, captured_cues: capturedCues,
    caption_timing: "Original wall-clock cues scaled to encoded video duration; retained separately for provenance.", cues };
  const captions = "WEBVTT\n\n" + cues.map((cue, i) =>
    `${i + 1}\n${stamp(cue.at)} --> ${stamp(cues[i + 1]?.at ?? duration)}\n${cue.text}\n`).join("\n");
  await writeFile(path.join(output, `${capture.chapter}.vtt`), captions);
  await writeFile(path.join(output, `${capture.chapter}.json`), JSON.stringify(metadata, null, 2) + "\n");
  return metadata;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const output = process.argv[2];
  if (!output) throw new Error("Pass the existing generated course-assets directory.");
  for (const file of (await readdir(output)).filter(file => /^\d\d-.*\.json$/.test(file)).sort()) {
    const metadata = await publishTiming(output, JSON.parse(await readFile(path.join(output, file), "utf8")));
    console.log(`${metadata.chapter}: ${metadata.duration}s encoded, ${metadata.capture_duration.toFixed(2)}s automation; captions aligned.`);
  }
}