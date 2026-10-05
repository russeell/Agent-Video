"""One entry point for obtaining and reusing video evidence."""
from __future__ import annotations
import argparse
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import sys
import tomllib
import uuid
from urllib.parse import urlsplit, parse_qs

if __package__:
    from . import media, manifest
else:
    import media
    import manifest


KINDS = {'info', 'transcript', 'frames', 'audio', 'video'}


class InputError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError(message)


def parser():
    p = Parser(description='Get video evidence and reuse it in follow-up questions.',
               epilog='Examples:\n  agent-video video.mp4 --get transcript\n'
               '  agent-video --evidence manifest.json --get frames --at 01:23 --width 1600\n'
               '  agent-video "<video-url>" --get video\n\n'
               'Returns JSON with manifest, artifacts and diagnostics.\n'
               'Exit codes: 0 success, 2 partial success, 1 failure, 64 invalid arguments.',
               formatter_class=argparse.RawDescriptionHelpFormatter)
    try:
        current_version = version('agent-video')
    except PackageNotFoundError:
        project_file = Path(__file__).resolve().parents[1] / 'pyproject.toml'
        current_version = tomllib.loads(project_file.read_text(encoding='utf-8'))['project']['version']
    p.add_argument('--version', action='version', version='agent-video ' + current_version)
    p.add_argument('source', nargs='?', help='Supported video URL or local file; use this or --evidence.')
    p.add_argument('--evidence', metavar='MANIFEST', help='Reuse a saved manifest.json instead of a new source.')
    p.add_argument('--get', default='transcript', metavar='KINDS',
                   help='Comma-separated info,transcript,frames,audio,video (default: %(default)s).')
    p.add_argument('--out', metavar='DIRECTORY',
                   help='Parent directory for new evidence (default: .agent-video); cannot combine with --evidence.')
    p.add_argument('--start', metavar='TIME',
                   help='Start in the original video: seconds, MM:SS or HH:MM:SS (default: 0).')
    p.add_argument('--end', metavar='TIME', help='End in the same time formats, after --start (default: video end).')
    p.add_argument('--at', action='append', metavar='TIMES',
                   help='Original-video times, e.g. 00:10,01:23; comma-separated or repeated; requires frames, excludes --start/--end.')
    p.add_argument('--max-frames', type=int, default=12,
                   help='Frame budget, including explicit --at times (default: %(default)s).')
    p.add_argument('--width', type=int, default=768,
                   help='Frame width in pixels, without upscaling; 0 keeps source size (default: %(default)s).')
    p.add_argument('--quality', choices=['auto', '1080p', 'source'], default='auto',
                   help='video defaults to highest available; 1080p limits the tier; frames auto uses the requested width')
    p.add_argument('--language', help='Requested subtitle or ASR language, e.g. en or zh; no automatic translation.')
    p.add_argument('--audio-track', type=int, metavar='INDEX', help='Select a nonnegative ffprobe audio stream index.')
    p.add_argument('--part', type=int, metavar='N', help='Bilibili part number, starting at 1; must agree with URL p=.')
    p.add_argument('--cookies', metavar='FILE', help='Explicitly supplied Netscape Cookie file; no browser credential access.')
    return p


def validate(args):
    if bool(args.source) == bool(args.evidence):
        raise InputError('Provide exactly one source or --evidence.')
    if args.evidence and args.out:
        raise InputError('--out cannot be combined with --evidence.')
    args.kinds = list(dict.fromkeys(args.get.split(',')))
    if not args.kinds or any(k not in KINDS for k in args.kinds):
        raise InputError('--get accepts info,transcript,frames,audio,video.')
    # Video delivery needs the best available source, including when combined
    # with frames or audio. Keep auto's smaller dependencies for other tasks.
    if 'video' in args.kinds and args.quality == 'auto':
        args.quality = 'source'
    try:
        args.begin = media.clock(args.start) if args.start is not None else 0.0
        args.finish = media.clock(args.end) if args.end is not None else None
        args.times = [media.clock(t) for group in args.at for t in group.split(',')] if args.at is not None else None
    except ValueError as exc:
        raise InputError(str(exc)) from None
    if args.finish is not None and args.finish <= args.begin:
        raise InputError('--end must be later than --start.')
    if args.times is not None and ('frames' not in args.kinds or args.start is not None or args.end is not None):
        raise InputError('--at requires frames and cannot be combined with --start/--end.')
    if args.kinds == ['info'] and (args.start is not None or args.end is not None):
        raise InputError('info-only does not accept a time interval.')
    if args.max_frames < 1 or args.width < 0 or (args.times is not None and len(args.times) > args.max_frames):
        raise InputError('Frame budget must be positive; width nonnegative; --at must fit the budget.')
    if args.audio_track is not None and args.audio_track < 0:
        raise InputError('--audio-track must be a nonnegative ffprobe stream index.')
    if args.part is not None and args.part < 1:
        raise InputError('--part must be positive.')
    if args.cookies and not Path(args.cookies).is_file():
        raise InputError('Cookie file does not exist.')
    if args.source and urlsplit(args.source).scheme in ('http', 'https'):
        url = urlsplit(args.source)
        if args.part is not None and not (url.hostname == 'b23.tv' or (url.hostname or '').endswith('bilibili.com')):
            raise InputError('--part is only applicable to Bilibili.')
        linked_part = parse_qs(url.query).get('p', [None])[0]
        if args.part is not None and linked_part is not None:
            try:
                conflict = int(linked_part) != args.part
            except ValueError:
                raise InputError('Invalid part in source URL.') from None
            if conflict:
                raise InputError('--part conflicts with the source URL part.')
    if args.source and not urlsplit(args.source).scheme in ('http', 'https'):
        if not Path(args.source).is_file():
            raise InputError('Local source file does not exist.')
        if args.part is not None:
            raise InputError('--part is only applicable to Bilibili.')
    return args


def diagnostic(stage, exc):
    aliases = {'missing_dependency': 'dependency_missing', 'process_failed': 'processing_failed',
               'no_speech_detected': 'no_speech'}
    code = getattr(exc, 'code', 'processing_failed')
    return {'stage': stage, 'code': aliases.get(code, code),
            'message': media.safe_message(exc), 'next_action': getattr(exc, 'next_action', None)}


def local_subtitles(path):
    candidates = []
    for ext in ('vtt', 'srt', 'json'):
        for candidate in sorted(path.parent.glob(path.stem + '*.' + ext)):
            suffix = candidate.stem[len(path.stem):]
            if suffix and not suffix.startswith('.'):
                continue
            language = suffix[1:] or None
            if language in ('danmaku', 'live_chat'):
                continue
            candidates.append({'path': candidate, 'ext': ext, 'language': language, 'origin': 'local_subtitle'})
    return candidates


def choose_local(candidates, language):
    if language:
        candidates = [c for c in candidates if c['language'] == language or
                      (c['language'] and c['language'].split('-')[0] == language.split('-')[0])]
    else:
        plain = [c for c in candidates if c['language'] is None]
        if plain:
            candidates = plain
        elif len({c['language'] for c in candidates}) > 1:
            raise media.Failure('subtitle_language_ambiguous', 'Choose --language from: ' +
                                ', '.join(sorted({c['language'] for c in candidates})))
    return candidates[0] if candidates else None


class Watch:
    def __init__(self, args):
        self.args = args
        self.result = []
        self.diagnostics = []
        self.resolved = None
        self.media_resolved = False
        self.info = None
        self.local = None
        self.completed = set()
        self.access_context = None
        if args.cookies:
            cookie_file = Path(args.cookies).resolve()
            stat = cookie_file.stat()
            # Identify a changed explicit credential file without retaining its path or contents.
            self.access_context = hashlib.sha256(f'{cookie_file}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()
        if args.evidence:
            try:
                self.path, self.data = manifest.load(args.evidence)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise InputError(str(exc)) from None
            source = self.data['source']
            if args.part is not None and args.part != source.get('part'):
                raise InputError('An evidence manifest has a fixed source part.')
            if source.get('platform') == 'local':
                self.local = Path(source['path'])
                if self.local.is_file():
                    current = media.fingerprint(self.local)
                    if current != source.get('fingerprint'):
                        self.data['artifacts'] = []
                        source['fingerprint'] = current
        else:
            if urlsplit(args.source).scheme in ('http', 'https'):
                source = {'url': args.source}
            else:
                self.local = Path(args.source).resolve()
                source = {'platform': 'local', 'id': self.local.stem, 'path': str(self.local),
                          'fingerprint': media.fingerprint(self.local)}
            directory = (Path(args.out or '.agent-video') / uuid.uuid4().hex[:12]).resolve()
            directory.mkdir(parents=True)
            self.path = directory / 'manifest.json'
            self.data = {'schema_version': 1, 'source': source, 'artifacts': []}
        self.directory = self.path.parent
        self.save()

    def save(self):
        self.data['diagnostics'] = self.diagnostics
        media.atomic_json(self.path, self.data)

    def add(self, kind, path, **fields):
        if kind in ('video', 'frames') and self.data['source'].get('platform') == 'bilibili':
            fields['quality_revision'] = 1
        artifact = manifest.add(self.data, self.directory, kind, path, **fields)
        self.save()
        return artifact

    def deliver(self, artifact):
        if artifact['id'] not in {a['id'] for a in self.result}:
            self.result.append(artifact)

    def fail(self, stage, exc):
        item = diagnostic(stage, exc)
        if item not in self.diagnostics:
            self.diagnostics.append(item)
        self.save()

    def resolve(self, media_needed=False):
        if self.resolved is None or (media_needed and not self.media_resolved):
            if __package__:
                from . import platforms
            else:
                import platforms
            print('Resolving video source…', file=sys.stderr)
            needs = self.args.kinds + (['media'] if media_needed else [])
            previous = self.resolved
            refreshed = platforms.resolve(self.data['source']['url'], part=self.data['source'].get('part', self.args.part),
                                          cookies=self.args.cookies, need=needs)
            if previous:
                refreshed['subtitles'] = previous.get('subtitles', refreshed.get('subtitles', []))
                refreshed['metadata'] = {**previous.get('metadata', {}), **refreshed.get('metadata', {})}
            self.resolved = refreshed
            self.media_resolved = bool(set(needs) & {'video', 'audio', 'frames', 'media'})
            self.data['source'] = self.resolved['source']
            existing_info = next((a for a in self.data['artifacts'] if a['type'] == 'info'), None)
            if existing_info:
                from datetime import datetime, timezone
                metadata = {**self.resolved['metadata'], 'collected_at': datetime.now(timezone.utc).isoformat()}
                media.atomic_json(manifest.artifact_path(self.directory, existing_info), metadata)
            for item in self.resolved.get('diagnostics', []):
                if item not in self.diagnostics:
                    self.diagnostics.append(item)
            self.save()
        return self.resolved

    def metadata(self):
        existing = next((a for a in self.data['artifacts'] if a['type'] == 'info'), None)
        if existing:
            self.deliver(existing)
            self.completed.add('info')
            return
        if self.local:
            self.info = media.probe(self.local)
            metadata = dict.fromkeys(['author', 'description', 'published_at', 'thumbnail', 'view_count', 'like_count', 'comment_count'])
            metadata.update(platform='local', id=self.local.stem, source=str(self.local), title=self.local.name,
                            duration=self.info['duration'])
        else:
            metadata = dict(self.resolve()['metadata'])
        from datetime import datetime, timezone
        metadata['collected_at'] = datetime.now(timezone.utc).isoformat()
        path = self.directory / 'metadata.json'
        media.atomic_json(path, metadata)
        self.deliver(self.add('info', path))
        self.completed.add('info')

    def duration(self):
        if self.info:
            return self.info['duration']
        full = [a['source_range']['end'] for a in self.data['artifacts']
                if a.get('internal') and a.get('source_range', {}).get('end') is not None]
        if full:
            return max(full)
        for artifact in self.data['artifacts']:
            if artifact['type'] == 'info':
                value = json.loads(manifest.artifact_path(self.directory, artifact).read_text()).get('duration')
                if value is not None:
                    return float(value)
        return None

    def interval(self):
        duration = self.duration()
        self.check_range(duration)
        return self.args.begin, self.args.finish if self.args.finish is not None else duration

    def check_range(self, duration):
        if duration is not None and (self.args.begin >= duration or
                self.args.finish is not None and self.args.finish > duration + 0.001):
            raise media.Failure('range_out_of_bounds',
                                f'Requested interval is outside the source duration ({duration:g}s).')

    def matching(self, kind, start, end):
        for a in self.data['artifacts']:
            if a['type'] != kind or not manifest.covers(a, start, end):
                continue
            if kind in ('transcript', 'audio', 'video') and self.args.audio_track is not None and a.get('audio_track') != self.args.audio_track:
                continue
            if kind in ('transcript', 'audio', 'video') and self.args.audio_track is None and a.get('audio_track') is not None:
                if a.get('audio_track_default') is False:
                    continue
                if (not self.local and not a.get('internal')
                        and a.get('audio_track_default') is None):
                    continue
                if self.local and a.get('audio_track_default') is not True:
                    if not self.local.is_file() or a['audio_track'] != media.audio_index(self.info or media.probe(self.local)):
                        continue
            if kind == 'transcript' and self.args.language and self.args.language not in (
                    a.get('requested_language'), a.get('language')):
                continue
            if kind == 'transcript' and self.args.language is None and (
                    'requested_language' not in a or a['requested_language'] is not None):
                continue
            if kind == 'video' and (a.get('frames_only') or
                not self.current_quality(a) or
                (self.access_context is not None and a.get('access_context') != self.access_context) or
                (self.args.quality != 'auto' and a.get('quality') not in (self.args.quality, 'source'))):
                continue
            if kind in ('video', 'audio'):
                info = media.probe(manifest.artifact_path(self.directory, a))
                if (kind == 'video' and not info['video'] or
                        (kind == 'audio' or a.get('audio_track') is not None) and not info['audio']):
                    continue
            return a
        return None

    def current_quality(self, artifact):
        # Earlier Bilibili extraction could miss HD and mark 480p as the best source.
        # Recheck those files once after enabling full anonymous playurl formats.
        needs_best = self.args.quality == 'source' or ('frames' in self.args.kinds and self.args.width == 0)
        return (not needs_best or self.data['source'].get('platform') != 'bilibili'
                or artifact.get('quality_revision', 0) >= 1)

    def acquire(self, purpose):
        if self.local and self.local.is_file():
            return self.local, self.info or media.probe(self.local)
        full_end = self.duration()
        for kind in (['video', 'audio'] if purpose == 'audio' else ['video']):
            for a in self.data['artifacts']:
                if a['type'] != kind or not manifest.covers(a, 0, full_end):
                    continue
                if purpose == 'video' and a.get('frames_only'):
                    continue
                if purpose != 'audio' and not self.current_quality(a):
                    continue
                if purpose != 'audio' and self.access_context is not None and a.get('access_context') != self.access_context:
                    continue
                if purpose != 'audio' and self.args.quality != 'auto' and a.get('quality') not in (self.args.quality, 'source'):
                    continue
                path = manifest.artifact_path(self.directory, a)
                info = media.probe(path)
                if purpose in ('audio', 'video') and info['audio'] and not a.get('internal'):
                    # Exports can select a different source track and renumber it.
                    if (self.args.audio_track is None and a.get('audio_track_default') is not True
                            or self.args.audio_track is not None and a.get('audio_track') != self.args.audio_track):
                        continue
                    if info['audio'] and (a.get('audio_track') not in {s['index'] for s in info['audio']}
                            or self.args.audio_track is None and a.get('audio_track') != media.audio_index(info)):
                        continue
                if purpose == 'video' and (not info['video'] or
                        (a.get('audio_track') is not None and not info['audio'])):
                    continue
                if not info['audio'] and (purpose == 'audio' or self.args.audio_track is not None):
                    if ((a.get('internal') or self.local and kind == 'video') and not a.get('frames_only')
                            and a.get('audio_track') is None
                            and (self.access_context is None or a.get('access_context') == self.access_context)):
                        raise media.Failure('no_audio', 'The saved complete video has no audio stream.')
                    continue
                if purpose == 'frames' and a.get('quality') != 'source':
                    ceiling = a.get('available_max_width')
                    if not info['video'] or ((self.args.width == 0 or info['video']['width'] < self.args.width)
                                            and (not ceiling or info['video']['width'] < ceiling)):
                        continue
                if self.args.audio_track is not None:
                    try:
                        media.audio_index(info, self.args.audio_track)
                    except media.Failure:
                        continue
                return path, info
        if self.local:
            raise media.Failure('source_unavailable',
                                'The original local file is unavailable and saved media cannot supply the requested material.',
                                'Use the available saved materials, or restore the original file to obtain missing evidence.')
        cached_source = dict(self.data['source'])
        resolved = self.resolve(media_needed=True)
        if __package__:
            from . import platforms
        else:
            import platforms
        want_video = {'video': True, 'frames': 'frames', 'audio': False}[purpose]
        formats = resolved.get('formats', [])
        selected = platforms.select_formats(formats, want_video=want_video, quality=self.args.quality,
                                            width=self.args.width) if formats else []
        visual = next((f for f in selected if f.get('has_video')), None)
        max_width = max((f.get('width') or 0 for f in formats if f.get('has_video')), default=0)
        video_path = None
        if (purpose == 'video' and cached_source == resolved['source'] and len(selected) == 2
                and visual and visual.get('has_audio') is False
                and selected[1].get('has_audio') and not selected[1].get('has_video')
                and all(f.get('protocol') not in ('hls', 'dash')
                        and f.get('ext') not in ('m3u8', 'mpd') for f in selected)):
            expected = resolved.get('metadata', {}).get('duration')
            for a in self.data['artifacts']:
                if (a['type'] != 'video' or not a.get('frames_only') or a.get('quality') != 'source'
                        or not self.current_quality(a) or a.get('access_context') != self.access_context
                        or (cached_source.get('platform') == 'bilibili' and a.get('quality_revision', 0) < 1)
                        or not manifest.covers(a, 0, full_end)):
                    continue
                path = manifest.artifact_path(self.directory, a)
                info = media.probe(path)
                if (not info['video'] or info['audio']
                        or not manifest.covers(a, 0, info['duration'])
                        or info['video']['width'] != visual.get('width')
                        or info['video']['height'] != visual.get('height')
                        or (expected and (info['duration'] < expected - max(2, expected * .03)
                            or a.get('source_range', {}).get('end', 0) < expected - max(2, expected * .03)))):
                    continue
                video_path = path
                break
        # Old evidence has no ceiling marker. Resolve once, then compare actual files
        # with the chosen format rather than downloading the same low-quality stream.
        if purpose == 'frames' and self.args.quality == 'auto' and self.args.width > 0 and visual and visual.get('width') and visual.get('height'):
            for a in self.data['artifacts']:
                if a['type'] != 'video' or not manifest.covers(a, 0, full_end) or (purpose == 'video' and a.get('frames_only')):
                    continue
                if self.access_context is not None and a.get('access_context') != self.access_context:
                    continue
                path = manifest.artifact_path(self.directory, a)
                info = media.probe(path)
                if not info['video'] or info['video']['width'] < visual['width'] or info['video']['height'] < visual['height']:
                    continue
                if any(f.get('has_audio') for f in selected) and not info['audio']:
                    continue
                if self.args.audio_track is not None:
                    media.audio_index(info, self.args.audio_track)
                a.update(available_max_width=max_width, access_context=self.access_context)
                self.save()
                return path, info
        print('Obtaining required media…', file=sys.stderr)
        path = Path(platforms.download(resolved, self.directory / ('video' if purpose != 'audio' else 'audio'),
                                      want_video=want_video,
                                      quality=self.args.quality, width=self.args.width, cookies=self.args.cookies,
                                      video_path=video_path)).resolve()
        if not path.is_file() or path.stat().st_size == 0:
            raise media.Failure('invalid_media', 'Download did not produce a nonempty file.')
        info = media.probe(path)
        if purpose != 'audio' and not info['video']:
            raise media.Failure('no_video', 'Downloaded media has no video stream.')
        if any(f.get('has_audio') for f in selected) and not info['audio']:
            raise media.Failure('invalid_media', 'Downloaded media is missing the expected audio stream.')
        if purpose == 'audio':
            media.audio_index(info, self.args.audio_track)
        fields = {'source_range': {'start': 0, 'end': info['duration']}, 'quality': 'source' if purpose == 'frames' and self.args.width == 0 else self.args.quality, 'internal': True}
        fields['access_context'] = self.access_context
        if max_width:
            fields['available_max_width'] = max_width
        if purpose == 'frames':
            fields['frames_only'] = True
        if info['video']:
            fields['width'] = info['video']['width']
            fields['height'] = info['video']['height']
        if info['audio']:
            fields['audio_track'] = media.audio_index(info, self.args.audio_track)
            fields['audio_track_default'] = fields['audio_track'] == media.audio_index(info)
        self.add('audio' if purpose == 'audio' else 'video', path, **fields)
        return path, info

    def transcript(self, shared=None):
        start, end = self.interval()
        existing = self.matching('transcript', start, end)
        if existing:
            span = existing['source_range']
            if span == {'start': start, 'end': end}:
                if 'text_span' not in existing:
                    data = json.loads(manifest.artifact_path(self.directory, existing).read_text())
                    existing['text_span'] = media.transcript_span(data['segments'])
                self.deliver(existing)
                return
            data = json.loads(manifest.artifact_path(self.directory, existing).read_text())
            segments = media.subtitle_range(data['segments'], start, end)
            language, origin = existing.get('language'), existing.get('origin')
            track = existing.get('audio_track')
            track_default = existing.get('audio_track_default')
        else:
            candidate = None
            if self.local:
                candidate = choose_local(local_subtitles(self.local), self.args.language)
            else:
                resolved = self.resolve()
                if __package__:
                    from . import platforms
                else:
                    import platforms
                candidate = platforms.select_subtitle(resolved.get('subtitles', []), language=self.args.language,
                                                      original_language=resolved.get('metadata', {}).get('original_language', resolved.get('metadata', {}).get('language')))
            subtitle_error = None
            if candidate:
                try:
                    text = candidate['path'].read_text(encoding='utf-8') if self.local else platforms.fetch_subtitle(candidate, cookies=self.args.cookies)
                    all_segments = media.parse_subtitles(text, candidate['ext'])
                    if not all_segments:
                        raise media.Failure('subtitle_absent', 'The subtitle track contains no valid speech segments.')
                    segments = media.subtitle_range(all_segments, start, end)
                    language, origin, track = candidate.get('language'), candidate.get('origin', 'platform_unknown'), None
                    track_default = None
                except (ValueError, OSError, media.Failure) as exc:
                    subtitle_error = exc
                    candidate = None
            if not candidate:
                model = os.environ.get('AGENT_VIDEO_ASR_MODEL')
                if not model or not media.asr_ready(model):
                    if subtitle_error:
                        raise subtitle_error
                    prior = next((d for d in self.diagnostics if d.get('stage') in ('transcript', 'subtitles')
                                  and d.get('code') not in ('subtitle_absent',)), None)
                    if prior:
                        raise media.Failure(prior['code'], prior['message'], prior.get('next_action'))
                    raise media.Failure('subtitle_absent',
                                        'No usable subtitle was obtained; local ASR is not configured.',
                                        'Provide subtitles or prepare ASR and set AGENT_VIDEO_ASR_MODEL.')
                path, info = shared if shared and shared[1]['audio'] else self.acquire('audio')
                self.check_range(info['duration'])
                track = media.audio_index(info, self.args.audio_track)
                track_default = track == media.audio_index(info)
                data = media.transcribe(path, info, start, self.args.finish, self.args.language, track, model)
                segments, language, origin = data['segments'], data['language'], 'asr'
                end = self.args.finish if self.args.finish is not None else info['duration']
        span = {'start': start, 'end': end}
        path, readable = media.transcript_files(self.directory, segments, language, origin, span)
        fields = {'source_range': span, 'text_span': media.transcript_span(segments),
                  'language': language, 'origin': origin,
                  'requested_language': self.args.language,
                  'readable_path': str(readable.relative_to(self.directory))}
        if track is not None:
            fields['audio_track'] = track
            fields['audio_track_default'] = track_default
        self.deliver(self.add('transcript', path, **fields))

    def frame_times(self, info):
        if self.args.times is not None:
            return list(dict.fromkeys(self.args.times))
        self.check_range(info['duration'])
        start = self.args.begin
        end = self.args.finish if self.args.finish is not None else info['duration']
        if start >= info['duration'] or end <= start:
            raise media.Failure('range_out_of_bounds', 'Requested interval is outside the source.')
        count = self.args.max_frames
        # Centers avoid the undecodable exact end and remain inside the requested range.
        return [start + (end - start) * (i + 0.5) / count for i in range(count)]

    def frames(self, shared):
        path, info = shared
        if info['video'] and self.args.width and info['video']['width'] < self.args.width:
            self.fail('frames', media.Failure('quality_insufficient',
                f'Requested frame width {self.args.width}px; available media is {info["video"]["width"]}×{info["video"]["height"]}. Frames retain the available resolution without upscaling.',
                'Use the available frames, provide a higher-resolution local file, or explicitly supply new credentials / quality to check for an upgrade.'))
        times = self.frame_times(info)
        missing = []
        for time in times:
            existing = next((a for a in self.data['artifacts'] if a['type'] == 'frames' and
                             self.current_quality(a) and
                             abs(a.get('requested_time', -1) - time) < 0.000001 and
                             (self.access_context is None or a.get('access_context') == self.access_context) and
                             (self.args.quality == 'auto' and self.args.width > 0 or
                              a.get('quality') == ('source' if self.args.width == 0 else self.args.quality)) and
                             a.get('width', 0) >= (min(self.args.width, info['video']['width']) if self.args.width else info['video']['width'])), None) if info['video'] else None
            if existing:
                self.deliver(existing)
            else:
                missing.append(time)
        failures = False
        for frame in media.frames(path, self.directory / 'frames', missing, self.args.width, info):
            if frame.get('error'):
                self.diagnostics.append({'stage': 'frames', **frame['error']})
                self.save()
                failures = True
                continue
            frame = dict(frame)
            dest = frame.pop('path')
            self.deliver(self.add('frames', dest, quality='source' if self.args.width == 0 else self.args.quality,
                                  access_context=self.access_context, **frame))
        if failures:
            return False
        return True

    def export(self, kind, shared):
        start, end = self.interval()
        existing = self.matching(kind, start, end)
        if existing and existing['source_range'] == {'start': start, 'end': end}:
            self.deliver(existing)
            return
        path, info = shared
        self.check_range(info['duration'])
        end = self.args.finish if self.args.finish is not None else info['duration']
        track = media.audio_index(info, self.args.audio_track) if info['audio'] else None
        suffix = path.suffix if kind == 'video' and start == 0 and self.args.finish is None else ('.mkv' if kind == 'video' else '.mka')
        dest = self.directory / kind / (uuid.uuid4().hex[:10] + suffix)
        function = media.export_video if kind == 'video' else media.export_audio
        details = function(path, dest, info, start, self.args.finish, self.args.audio_track)
        verified = media.probe(dest)
        if not dest.stat().st_size or (kind == 'video' and not verified['video']):
            raise media.Failure('invalid_media', 'Export does not contain the expected media.')
        if kind == 'audio' or info['audio']:
            media.audio_index(verified)
        fields = {'source_range': {'start': start, 'end': end}, 'transcoded': details['transcoded']}
        if track is not None:
            fields['audio_track'] = track
            fields['audio_track_default'] = track == media.audio_index(info)
        if kind == 'video':
            fields['quality'] = 'source' if self.local else self.args.quality
            fields['access_context'] = self.access_context
            fields['width'] = verified['video']['width']
            fields['height'] = verified['video']['height']
            source_artifact = next((a for a in self.data['artifacts'] if a['type'] == 'video' and
                                    manifest.artifact_path(self.directory, a) == path), None)
            if source_artifact and source_artifact.get('available_max_width'):
                fields['available_max_width'] = source_artifact['available_max_width']
        self.deliver(self.add(kind, dest, **fields))

    def run(self):
        print('Preparing evidence…', file=sys.stderr)
        try:
            self.metadata()
        except InputError:
            raise
        except Exception as exc:
            self.fail('info', exc)
        # Merge dependent requests: one media fetch, richest requested material wins.
        shared = None
        wanted = set(self.args.kinds)
        wanted_to_process = wanted
        if wanted - {'info'}:
            try:
                self.interval()
            except media.Failure as exc:
                self.fail('range', exc)
                # Metadata and previously completed evidence remain available.
                wanted_to_process = set()
        for kind in ('video', 'audio'):
            if kind not in wanted_to_process:
                continue
            start, end = self.interval()
            cached = self.matching(kind, start, end)
            if cached and cached.get('source_range') == {'start': start, 'end': end}:
                self.deliver(cached)
                self.completed.add(kind)
        # Standalone frames remain reusable when they already meet the requested
        # width. Smaller frames must consult the saved media ceiling before reuse.
        if ('frames' in wanted_to_process and self.args.times is not None and self.access_context is None
                and (self.args.quality == 'auto' or self.args.width == 0)):
            cached_frames = [next((a for a in self.data['artifacts'] if a['type'] == 'frames'
                and self.current_quality(a)
                and abs(a.get('requested_time', -1) - time) < 0.000001
                and (a.get('width', 0) >= self.args.width if self.args.width else
                     a.get('quality') == 'source' and a.get('width') == a.get('source_width'))), None)
                for time in dict.fromkeys(self.args.times)]
            if all(cached_frames):
                for cached in cached_frames:
                    self.deliver(cached)
                self.completed.add('frames')
        need_visual = bool({'video', 'frames'} & (wanted_to_process - self.completed))
        need_audio = 'audio' in wanted_to_process - self.completed
        if need_visual or need_audio:
            try:
                shared = self.acquire('video' if 'video' in wanted or (need_visual and (need_audio or ('transcript' in wanted and media.asr_ready(os.environ.get('AGENT_VIDEO_ASR_MODEL'))))) else 'frames' if need_visual else 'audio')
            except Exception as exc:
                self.fail('media', exc)
        for kind in self.args.kinds:
            if kind in self.completed or kind not in wanted_to_process:
                continue
            try:
                if kind == 'transcript':
                    self.transcript(shared)
                elif shared is None:
                    continue
                elif kind == 'frames':
                    if not self.frames(shared):
                        continue
                else:
                    self.export(kind, shared)
                self.completed.add(kind)
            except Exception as exc:
                self.fail(kind, exc)
        status = 'ok' if wanted <= self.completed else 'partial' if self.result else 'error'
        self.data['last_request'] = {'get': self.args.kinds, 'start': self.args.begin, 'end': self.args.finish,
                                     'at': self.args.times, 'status': status, 'artifact_ids': [a['id'] for a in self.result]}
        self.save()
        result = {'status': status, 'manifest': str(self.path),
                  'artifacts': [{'type': a['type'], 'path': str(manifest.artifact_path(self.directory, a)),
                                 **({'text_span': a['text_span']} if 'text_span' in a else {}),
                                 **({'readable_path': str(manifest.artifact_path(self.directory, a, 'readable_path'))} if a.get('readable_path') else {})}
                                for a in self.result], 'diagnostics': self.diagnostics}
        return result, {'ok': 0, 'partial': 2, 'error': 1}[status]


def main(argv=None):
    watch = None
    try:
        args = validate(parser().parse_args(argv))
        watch = Watch(args)
        result, code = watch.run()
    except (InputError, ValueError) as exc:
        result, code = {'status': 'error', 'manifest': None, 'artifacts': [],
                        'diagnostics': [diagnostic('arguments', exc)]}, 64
    except KeyboardInterrupt:
        if watch:
            watch.fail('cancel', media.Failure('cancelled', 'Request was cancelled; completed evidence remains available.'))
            watch.data['last_request'] = {'get': watch.args.kinds,
                'status': 'partial' if watch.result else 'error', 'artifact_ids': [a['id'] for a in watch.result]}
            watch.save()
        result, code = {'status': 'partial' if watch and watch.result else 'error',
                        'manifest': str(watch.path) if watch else None,
                        'artifacts': [{'type': a['type'], 'path': str(manifest.artifact_path(watch.directory, a))}
                                      for a in watch.result] if watch else [],
                        'diagnostics': watch.diagnostics if watch else [{'stage': 'cancel', 'code': 'cancelled', 'message': 'Cancelled.', 'next_action': None}]}, 130
    except Exception as exc:
        result, code = {'status': 'error', 'manifest': str(watch.path) if watch else None,
                        'artifacts': [], 'diagnostics': [diagnostic('source', exc)]}, 1
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
