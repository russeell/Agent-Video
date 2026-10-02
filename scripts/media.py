"""Local evidence processing. No model imports or network access at import time."""
from __future__ import annotations

import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid


class Failure(Exception):
    def __init__(self, code, message, next_action=None):
        super().__init__(message)
        self.code, self.next_action = code, next_action


def safe_message(value):
    # Upstream failures may contain signed CDN URLs, cookies and proxy credentials.
    text = re.sub(r'https?://[^\s\"\'<>]+', '[URL redacted]', str(value))
    text = re.sub(r'(?i)(cookie|authorization|token|password)\s*[:=][^\n]+', r'\1=[redacted]', text)
    return text[-1500:]


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with tmp.open('x', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def clock(value):
    try:
        parts = str(value).split(':')
        if not 1 <= len(parts) <= 3:
            raise ValueError()
        values = [float(x) for x in parts]
        if any(x < 0 or not math.isfinite(x) for x in values):
            raise ValueError()
        if len(values) > 1 and any(x >= 60 for x in values[1:]):
            raise ValueError()
        return sum(x * 60 ** i for i, x in enumerate(reversed(values)))
    except (ValueError, TypeError):
        raise ValueError(f'Invalid time: {value}') from None


def run(args, timeout=300):
    try:
        proc = subprocess.Popen([str(a) for a in args], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        raise Failure('missing_dependency', f'{args[0]} is not installed.') from None
    try:
        out, err = proc.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        proc.terminate()
        try:
            proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
        if sys.exc_info()[0] is KeyboardInterrupt:
            raise
        raise Failure('timeout', f'{Path(str(args[0])).name} exceeded {timeout}s.') from None
    if proc.returncode:
        raise Failure('process_failed', safe_message(err or out))
    return out, err


def probe(path):
    out, _ = run(['ffprobe', '-v', 'error', '-show_format', '-show_streams',
                  '-of', 'json', path], timeout=30)
    data = json.loads(out)
    streams = data.get('streams', [])
    if not streams:
        raise Failure('invalid_media', 'No decodable media streams found.')
    fmt = data.get('format', {})
    data['duration'] = float(fmt.get('duration') or max(
        (float(s.get('duration') or 0) for s in streams), default=0))
    data['start_time'] = float(fmt.get('start_time') or 0)
    data['video'] = next((s for s in streams if s['codec_type'] == 'video'
                          and not s.get('disposition', {}).get('attached_pic')), None)
    data['audio'] = [s for s in streams if s['codec_type'] == 'audio']
    return data


def fingerprint(path):
    path = Path(path).resolve()
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise Failure('source_changed', 'Source changed while computing its fingerprint.')
    return {'size': after.st_size, 'mtime_ns': after.st_mtime_ns, 'sha256': digest.hexdigest()}


def audio_index(info, requested=None):
    tracks = info['audio']
    if not tracks:
        raise Failure('no_audio', 'The selected media has no audio stream.')
    if requested is not None:
        if not any(s['index'] == requested for s in tracks):
            raise Failure('invalid_audio_track', f'No audio stream with ffprobe index {requested}.')
        return requested
    return next((s['index'] for s in tracks if s.get('disposition', {}).get('default')), tracks[0]['index'])


def clean_text(text):
    return html.unescape(re.sub(r'<[^>]+>|\{\\[^}]+\}', '', text)).strip()


def parse_subtitles(text, ext):
    """VTT/SRT, Bilibili JSON and yt-dlp JSON3. Never parse danmaku XML."""
    segments = []
    if ext in ('json', 'json3'):
        data = json.loads(text)
        if isinstance(data, dict) and 'body' in data:
            segments = [{'start': x['from'], 'end': x['to'], 'text': x['content']} for x in data['body']]
        elif isinstance(data, dict) and 'events' in data:
            segments = [{'start': x['tStartMs'] / 1000,
                         'end': (x['tStartMs'] + x.get('dDurationMs', 0)) / 1000,
                         'text': ''.join(s.get('utf8', '') for s in x.get('segs', []))}
                        for x in data['events'] if x.get('segs')]
        elif isinstance(data, dict) and isinstance(data.get('segments'), list):
            segments = data['segments']
        else:
            raise Failure('invalid_subtitles', 'Unrecognized subtitle JSON schema.')
    elif ext in ('srt', 'vtt'):
        lines = text.replace('\r', '').lstrip('\ufeff').split('\n')
        for i, line in enumerate(lines):
            match = re.match(r'\s*([\d:.,]+)\s*-->\s*([\d:.,]+)', line)
            if not match:
                continue
            content = []
            for following in lines[i + 1:]:
                if not following.strip():
                    break
                content.append(following)
            segments.append({'start': clock(match[1].replace(',', '.')),
                             'end': clock(match[2].replace(',', '.')),
                             'text': '\n'.join(content)})
    else:
        raise Failure('unsupported_subtitles', f'Unsupported subtitle format: {ext}')
    result = []
    for seg in sorted(segments, key=lambda x: float(x['start'])):
        start, end = float(seg['start']), float(seg['end'])
        if not math.isfinite(start + end) or start < 0 or end < start:
            continue
        text = clean_text(seg['text'])
        if not text:
            continue
        # Only deduplicate overlapping displays. A repeated sentence later survives.
        if result and start < result[-1]['end']:
            previous = result[-1]
            if text == previous['text']:
                previous['end'] = max(previous['end'], end)
                continue
            old_lines, new_lines = previous['text'].splitlines(), text.splitlines()
            for n in range(min(len(old_lines), len(new_lines)), 0, -1):
                if old_lines[-n:] == new_lines[:n]:
                    text = '\n'.join(new_lines[n:])
                    break
        if text:
            result.append({'start': start, 'end': end, 'text': text})
    return result


def subtitle_range(segments, start, end):
    return [s for s in segments if s['end'] > start and (end is None or s['start'] < end)]


def transcript_files(directory, segments, language, origin, source_range):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = 'transcript-' + uuid.uuid4().hex[:10]
    path, readable = directory / (stem + '.json'), directory / (stem + '.md')
    atomic_json(path, {'language': language, 'origin': origin,
                       'source_range': source_range, 'segments': segments})
    readable.write_text('\n'.join(f"[{s['start']:.3f}–{s['end']:.3f}] {s['text']}" for s in segments) + '\n', encoding='utf-8')
    return path, readable


def frames(path, directory, times, width, info):
    if not info['video']:
        raise Failure('no_video', 'The selected media has no video stream.')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    result = []
    for requested in times:
        dest = directory / f'{uuid.uuid4().hex[:10]}.jpg'
        filters = f"select=gte(t\\,{info['start_time'] + requested:.9f}),showinfo"
        if width:
            filters += f",scale=w='min({width},iw)':h=-1"
        try:
            _, log = run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'info', '-y',
                          '-copyts', '-ss', max(0, requested - 1), '-i', path,
                          '-map', f"0:{info['video']['index']}", '-vf', filters,
                          '-frames:v', '1', '-fps_mode', 'vfr', '-q:v', '2', dest], timeout=120)
            match = re.search(r'\bn:\s*0\s+pts:.*?pts_time:([-\d.e+]+).*?\bs:(\d+)x(\d+)', log)
            if not dest.exists() or not match:
                raise Failure('frame_unavailable', f'No decoded frame at or after {requested:.3f}s.')
            result.append({'path': dest, 'requested_time': requested,
                           'actual_time': max(0, float(match[1]) - info['start_time']),
                           'width': min(width, int(match[2])) if width else int(match[2]),
                           'source_width': int(match[2]), 'source_height': int(match[3])})
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
    return result


def export_audio(path, dest, info, start=0, end=None, track=None, asr=False):
    index = audio_index(info, track)
    clipped = start != 0 or end is not None
    args = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-ss', start, '-i', path]
    if end is not None:
        args += ['-t', end - start]
    args += ['-map', f'0:{index}', '-vn']
    args += ['-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le'] if asr else (
        ['-c:a', 'flac'] if clipped else ['-c:a', 'copy'])
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(args + [dest], timeout=600)
    actual = probe(dest)
    return {'audio_track': index, 'transcoded': asr or clipped,
            'duration': actual['duration']}


def export_video(path, dest, info, start=0, end=None, track=None):
    if not info['video']:
        raise Failure('no_video', 'Cannot deliver audio-only media as a video.')
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if start == 0 and end is None and track is None:
        shutil.copy2(path, dest)
        return {'transcoded': False, 'duration': info['duration']}
    args = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-ss', start, '-i', path]
    if end is not None:
        args += ['-t', end - start]
    args += ['-map', f"0:{info['video']['index']}"]
    if info['audio']:
        args += ['-map', f'0:{audio_index(info, track)}']
    elif track is not None:
        audio_index(info, track)
    args += ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-c:a', 'aac', dest]
    run(args, timeout=1800)
    return {'transcoded': True, 'duration': probe(dest)['duration']}


def asr_ready(model):
    import importlib.util
    return bool(importlib.util.find_spec('faster_whisper')) and Path(model).is_dir()


def transcribe(path, info, start, end, language, track, model):
    if not asr_ready(model):
        raise Failure('asr_unavailable', 'Local ASR dependency or model directory is missing.',
                      'Install the asr extra and set AGENT_VIDEO_ASR_MODEL to a downloaded model directory.')
    with tempfile.TemporaryDirectory(prefix='agent-video-asr-') as tmp:
        audio = Path(tmp) / 'speech.wav'
        export_audio(path, audio, info, start, end, track, asr=True)
        result = Path(tmp) / 'result.json'
        args = [sys.executable, str(Path(__file__).resolve()), '--asr-worker', str(audio), str(result), str(model)]
        if language:
            args.append(language)
        run(args, timeout=1800)
        data = json.loads(result.read_text())
    for segment in data['segments']:
        segment['start'] += start
        segment['end'] += start
    if not data['segments']:
        raise Failure('no_speech_detected', 'ASR found no speech in the requested interval.')
    return data


def _asr_worker():
    from faster_whisper import WhisperModel
    model = WhisperModel(sys.argv[4], device='cpu', compute_type='int8', local_files_only=True)
    segments, info = model.transcribe(sys.argv[2], language=sys.argv[5] if len(sys.argv) > 5 else None,
                                     vad_filter=True)
    atomic_json(sys.argv[3], {'language': info.language,
                             'segments': [{'start': s.start, 'end': s.end, 'text': s.text.strip()}
                                          for s in segments if s.text.strip()]})


if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == '--asr-worker':
    _asr_worker()
