import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { request, useConnection } from "./api";

function useMedia(id: string) {
  return useQuery<{ url: string }>({
    queryKey: ["preview-media", id],
    queryFn: () => request(`/api/assets/${id}/ticket`, {}),
    enabled: !!id,
    staleTime: 20 * 60 * 1000,
    refetchInterval: 20 * 60 * 1000,
  });
}

function ClipPlayer({
  clip,
  start,
  time,
  playing,
  silent,
  onTime,
  onEnd,
  onError,
}: {
  clip: any;
  start: number;
  time: number;
  playing: boolean;
  silent: boolean;
  onTime: (v: number) => void;
  onEnd: () => void;
  onError: (s: string) => void;
}) {
  const source = useMedia(clip.asset_id);
  const element = useRef<HTMLVideoElement>(null);
  const wanted = clip.trim_in + (time - start) * (clip.speed || 1);
  const sync = () => {
    const video = element.current;
    if (!video || video.readyState < 1) return;
    if (Math.abs(video.currentTime - wanted) > 0.18)
      video.currentTime = Math.max(
        clip.trim_in,
        Math.min(clip.trim_out - 0.01, wanted),
      );
    video.playbackRate = clip.speed || 1;
    video.volume = Math.max(0, Math.min(1, clip.volume ?? 1));
    if (playing)
      video
        .play()
        .catch(() => onError("Press Play again after the clip loads."));
    else video.pause();
  };
  useEffect(sync, [time, playing, source.data?.url, clip.speed, clip.volume]);
  return (
    <video
      ref={element}
      src={
        source.data ? useConnection.getState().url + source.data.url : undefined
      }
      muted={silent || clip.mute}
      playsInline
      preload="auto"
      onLoadedMetadata={sync}
      onEnded={onEnd}
      onError={() =>
        onError(
          "This preview source is unavailable. Refresh media access or restore the take.",
        )
      }
      onTimeUpdate={(e) => {
        if (!playing) return;
        const position = e.currentTarget.currentTime;
        if (position >= clip.trim_out - 0.025) onEnd();
        else onTime(start + (position - clip.trim_in) / (clip.speed || 1));
      }}
    />
  );
}

function PreviewAudio({
  track,
  time,
  playing,
  duck,
}: {
  track: any;
  time: number;
  playing: boolean;
  duck: boolean;
}) {
  const source = useMedia(track.asset_id);
  const element = useRef<HTMLAudioElement>(null);
  const sync = () => {
    const audio = element.current;
    if (!audio || audio.readyState < 1) return;
    const offset = time - track.start;
    const length = track.trim_out - track.trim_in;
    const active = playing && !track.mute && offset >= 0 && offset < length;
    if (
      Math.abs(audio.currentTime - (track.trim_in + Math.max(0, offset))) > 0.25
    )
      audio.currentTime = Math.max(
        0,
        track.trim_in + Math.max(0, Math.min(length, offset)),
      );
    const fade = Math.min(
      1,
      track.fade_in ? Math.max(0, offset) / track.fade_in : 1,
      track.fade_out ? Math.max(0, length - offset) / track.fade_out : 1,
    );
    audio.volume = Math.max(
      0,
      Math.min(1, (track.volume ?? 1) * fade * (track.duck && duck ? 0.3 : 1)),
    );
    if (active) audio.play().catch(() => {});
    else audio.pause();
  };
  useEffect(sync, [time, playing, source.data?.url, track, duck]);
  return (
    <audio
      ref={element}
      preload="metadata"
      src={
        source.data ? useConnection.getState().url + source.data.url : undefined
      }
      onLoadedMetadata={sync}
    />
  );
}

export function TimelinePreview({ value }: { value: any }) {
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [snap, setSnap] = useState(true);
  const [error, setError] = useState("");
  const starts: number[] = [];
  let total = 0;
  for (const clip of value.clips) {
    starts.push(total);
    total += (clip.trim_out - clip.trim_in) / (clip.speed || 1);
  }
  let index = 0;
  for (let i = 0; i < starts.length; i++)
    if (starts[i] <= Math.min(time, total - 0.001)) index = i;
  const clip = value.clips[index];
  useEffect(() => {
    setPlaying(false);
    setTime((v) => Math.min(v, Math.max(0, total - 0.01)));
    setError("");
  }, [JSON.stringify(value.clips)]);
  const seek = (v: number) => {
    let next = Math.max(0, Math.min(total, v));
    if (snap) {
      const boundary = [...starts, total].find(
        (p) => Math.abs(p - next) < 0.12,
      );
      if (boundary !== undefined) next = boundary;
    }
    setTime(next);
    setError("");
  };
  const finish = () => {
    const next = index + 1 < starts.length ? starts[index + 1] : total;
    setTime(next);
    if (next >= total) setPlaying(false);
  };
  const voice = value.audio.some(
    (t: any) =>
      t.role === "voiceover" &&
      !t.mute &&
      time >= t.start &&
      time < t.start + t.trim_out - t.trim_in,
  );
  if (!clip) return <p className="muted">Add clips to preview your cut.</p>;
  return (
    <div className="assembled-preview">
      <div className="preview-picture">
        <ClipPlayer
          key={clip.id}
          clip={clip}
          start={starts[index]}
          time={time}
          playing={playing}
          silent={value.settings.audio_mode === "silent"}
          onTime={setTime}
          onEnd={finish}
          onError={(message) => {
            setError(message);
            setPlaying(false);
          }}
        />
      </div>
      {value.settings.audio_mode === "mixed" &&
        value.audio.map((track: any) => (
          <PreviewAudio
            key={track.id}
            track={track}
            time={time}
            playing={playing}
            duck={voice}
          />
        ))}
      <div className="button-row">
        <button
          className="button primary"
          onClick={() => {
            if (time >= total - 0.02) setTime(0);
            setError("");
            setPlaying((p) => !p);
          }}
        >
          {playing ? "Pause preview" : "Play cut"}
        </button>
        <button
          className="button"
          onClick={() => {
            setPlaying(false);
            seek(0);
          }}
        >
          Go to start
        </button>
        <span>
          {time.toFixed(2)} / {total.toFixed(2)} s · clip {index + 1} of{" "}
          {value.clips.length}
        </span>
        <label>
          <input
            type="checkbox"
            checked={snap}
            onChange={(e) => setSnap(e.target.checked)}
          />{" "}
          Snap to cuts
        </label>
      </div>
      <label>
        Shared playhead
        <input
          aria-label="Timeline playhead"
          type="range"
          min={0}
          max={total}
          step={0.01}
          value={Math.min(time, total)}
          onChange={(e) => seek(Number(e.target.value))}
        />
      </label>
      <div className="timeline-ruler">
        {value.clips.map((c: any, i: number) => (
          <button
            key={c.id}
            style={{ flex: (c.trim_out - c.trim_in) / (c.speed || 1) }}
            onClick={() => seek(starts[i])}
            className={index === i ? "selected" : ""}
          >
            {i + 1} · {((c.trim_out - c.trim_in) / (c.speed || 1)).toFixed(1)}s
          </button>
        ))}
      </div>
      {error && <p role="alert">{error}</p>}
      <p className="muted">
        Quick playback uses cuts and approximate browser audio levels. Render a
        saved preview to inspect exact transitions, loops and the final sound
        mix.
      </p>
    </div>
  );
}

export function AudioWaveform({ assetId }: { assetId: string }) {
  const result = useQuery<{
    peaks: number[];
    duration: number;
    truncated: boolean;
  }>({
    queryKey: ["waveform", assetId],
    queryFn: () => request(`/api/assets/${assetId}/waveform`),
    staleTime: Infinity,
  });
  if (!result.data)
    return (
      <p className="muted">
        {result.error
          ? "Waveform unavailable; the original track remains available."
          : "Loading audio waveform…"}
      </p>
    );
  const peaks = result.data.peaks;
  const points = peaks
    .flatMap((v, i) => [
      `${(i * 1000) / peaks.length},${30 - v * 28}`,
      `${(i * 1000) / peaks.length},${30 + v * 28}`,
    ])
    .join(" ");
  return (
    <figure className="audio-waveform">
      <svg
        viewBox="0 0 1000 60"
        preserveAspectRatio="none"
        role="img"
        aria-label="Audio amplitude waveform"
      >
        <polyline
          points={points}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        />
      </svg>
      <figcaption>
        Source waveform · {result.data.duration.toFixed(1)} s
        {result.data.truncated ? " · first ten minutes" : ""}
      </figcaption>
    </figure>
  );
}
