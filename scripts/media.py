"""Local evidence processing. No model imports or network access at import time."""
from __future__ import annotations

import html
from functools import lru_cache
from contextlib import contextmanager
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
        raise Failure('dependency_missing', f'{args[0]} is not installed.') from None
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
        raise Failure('processing_failed', safe_message(err or out))
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
    # Matroska DURATION stores the end timestamp, unlike MP4 duration.
    if 'matroska' in fmt.get('format_name', ''):
        data['duration'] = max(0, data['duration'] - data['start_time'])
    data['video'] = next((s for s in streams if s['codec_type'] == 'video'
                          and not s.get('disposition', {}).get('attached_pic')), None)
    data['audio'] = [s for s in streams if s['codec_type'] == 'audio']
    return data


def fingerprint(path):
    stat = Path(path).resolve().stat()
    return {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


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
            else:
                # JSON3 often repeats a growing single line rather than whole lines.
                old_words, new_words = previous['text'].split(), text.split()
                for n in range(min(len(old_words), len(new_words)), 0, -1):
                    if old_words[-n:] == new_words[:n]:
                        text = ' '.join(new_words[n:])
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
    """Yield completed frames immediately; a later failure never discards them."""
    if not info['video']:
        raise Failure('no_video', 'The selected media has no video stream.')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for requested in times:
        dest = directory / f'{uuid.uuid4().hex[:10]}.jpg'
        filters = f"select=gte(t\\,{info['start_time'] + requested:.9f}),showinfo"
        if width:
            filters += f",scale=w='min({width},iw)':h=-1"
        try:
            if info.get('duration') and requested >= info['duration']:
                raise Failure('frame_unavailable', f'Frame time {requested:.3f}s is outside the media duration.')
            if requested < 0 or not math.isfinite(requested):
                raise Failure('frame_unavailable', 'Frame time must be finite and nonnegative.')
            _, log = run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'info', '-y',
                          '-copyts', '-ss', max(0, requested - 1), '-i', path,
                          '-map', f"0:{info['video']['index']}", '-vf', filters,
                          '-frames:v', '1', '-fps_mode', 'vfr', '-q:v', '2', dest], timeout=120)
            match = re.search(r'\bn:\s*0\s+pts:.*?pts_time:([-\d.e+]+).*?\bs:(\d+)x(\d+)', log)
            if not dest.exists() or not dest.stat().st_size or not match:
                raise Failure('frame_unavailable', f'No decoded frame at or after {requested:.3f}s.')
            image = probe(dest)['video']
            actual = float(match[1]) - info['start_time']
            yield {'path': dest, 'requested_time': requested, 'actual_time': actual,
                   'width': image['width'], 'height': image['height'],
                   'source_width': int(match[2]), 'source_height': int(match[3])}
        except Failure as exc:
            dest.unlink(missing_ok=True)
            yield {'requested_time': requested,
                   'error': {'code': exc.code, 'message': str(exc), 'next_action': exc.next_action}}
        except BaseException:
            dest.unlink(missing_ok=True)
            raise


@contextmanager
def _output(path, dest):
    """Validate a temporary output before replacing any existing result."""
    dest = Path(dest)
    if Path(path).resolve() == dest.resolve() or (dest.exists() and os.path.samefile(path, dest)):
        raise Failure('unsafe_path', 'Output must not overwrite the source media.')
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name('.' + dest.stem + '-' + uuid.uuid4().hex + dest.suffix)
    try:
        yield tmp
        if not tmp.exists() or not tmp.stat().st_size:
            raise Failure('processing_failed', 'Media processing produced no output.')
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def _range(start, end):
    if not math.isfinite(start) or start < 0 or (end is not None and
            (not math.isfinite(end) or end <= start)):
        raise Failure('invalid_range', 'Media range must have a nonnegative start and a later end.')


def export_audio(path, dest, info, start=0, end=None, track=None, asr=False):
    index = audio_index(info, track)
    _range(start, end)
    clipped = start != 0 or end is not None
    args = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-ss', start, '-i', path]
    if end is not None:
        args += ['-t', end - start]
    args += ['-map', f'0:{index}', '-vn']
    if clipped or asr:
        # Preserve leading silence when the audio stream begins after the source clock.
        args += ['-af', 'aresample=async=1:first_pts=0']
    args += ['-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le'] if asr else (
        ['-c:a', 'flac'] if clipped else ['-c:a', 'copy'])
    with _output(path, dest) as tmp:
        run(args + [tmp], timeout=600)
        actual = probe(tmp)
        if not actual['audio']:
            raise Failure('processing_failed', 'Audio output contains no audio stream.')
    return {'audio_track': index, 'transcoded': asr or clipped, 'duration': actual['duration']}


@lru_cache(maxsize=1)
def _video_encoder():
    listing, _ = run(['ffmpeg', '-hide_banner', '-encoders'], timeout=30)
    if re.search(r'^ V\S*\s+libx264\s', listing, re.M):
        return ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18']
    if re.search(r'^ V\S*\s+mpeg4\s', listing, re.M):
        return ['-c:v', 'mpeg4', '-q:v', '2']
    raise Failure('dependency_missing', 'FFmpeg needs a libx264 or mpeg4 video encoder.')


def export_video(path, dest, info, start=0, end=None, track=None):
    if not info['video']:
        raise Failure('no_video', 'Cannot deliver audio-only media as a video.')
    _range(start, end)
    clipped = start != 0 or end is not None
    index = audio_index(info, track) if info['audio'] or track is not None else None
    with _output(path, dest) as tmp:
        if not clipped and track is None:
            shutil.copy2(path, tmp)
        else:
            args = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-ss', start, '-i', path]
            if end is not None:
                args += ['-t', end - start]
            args += ['-map', f"0:{info['video']['index']}"]
            if index is not None:
                args += ['-map', f'0:{index}']
            args += (_video_encoder() + ['-fps_mode', 'vfr', '-c:a', 'aac']) if clipped else ['-c', 'copy']
            run(args + [tmp], timeout=1800)
        actual = probe(tmp)
        if not actual['video'] or (index is not None and not actual['audio']):
            raise Failure('processing_failed', 'Video output is missing an expected stream.')
    result = {'transcoded': clipped, 'duration': actual['duration']}
    if index is not None:
        result['audio_track'] = index
    return result


def asr_ready(model):
    import importlib.util
    return bool(model) and Path(model).is_dir() and bool(importlib.util.find_spec('faster_whisper'))


def transcribe(path, info, start, end, language, track, model):
    audio_index(info, track)
    _range(start, end)
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
        raise Failure('no_speech', 'ASR found no speech in the requested interval.')
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
