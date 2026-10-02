"""Small, project-owned single-video acquisition helpers.

Signed resource candidates are ephemeral and must never enter a manifest.
"""
from __future__ import annotations

import http.cookiejar
import http.client
import json
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

try:
    from .. import media
except ImportError:
    import media
Failure = media.Failure
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0 Safari/537.36'


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new and urllib.parse.urlsplit(req.full_url).hostname != urllib.parse.urlsplit(newurl).hostname:
            for name in ('Cookie', 'Authorization', 'Proxy-authorization'):
                new.remove_header(name)
        return new


def _opener(cookies=None):
    context = ssl.create_default_context()
    try:
        import truststore
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        pass
    jar = http.cookiejar.MozillaCookieJar(policy=http.cookiejar.DefaultCookiePolicy(
        strict_ns_domain=http.cookiejar.DefaultCookiePolicy.DomainStrictNonDomain))
    if cookies:
        try:
            jar.load(str(cookies), ignore_discard=True, ignore_expires=False)
        except (OSError, http.cookiejar.LoadError):
            raise Failure('invalid_cookies', 'Cannot read the Netscape Cookie file.', 'Provide an explicitly exported Cookie file.') from None
    return urllib.request.build_opener(_Redirect(), urllib.request.HTTPCookieProcessor(jar),
                                      urllib.request.HTTPSHandler(context=context))


def request(url, *, headers=None, cookies=None):
    """Open a validated HTTP response. Network retries are centralized here."""
    if urllib.parse.urlsplit(url).scheme not in ('http', 'https'):
        raise Failure('invalid_url', 'Only HTTP(S) resource addresses are supported.')
    supplied = {k: v for k, v in (headers or {}).items()
                if k.lower() not in ('cookie', 'authorization', 'proxy-authorization')}
    for attempt in range(3):
        try:
            return _opener(cookies).open(urllib.request.Request(url, headers={'User-Agent': UA, **supplied}), timeout=30)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise Failure('access_denied', f'HTTP {exc.code}: platform access was denied.', 'Try an explicitly supplied Cookie file or retry later.') from None
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise Failure('network_failed', f'HTTP request failed with status {exc.code}.', 'Retry acquisition later.') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                raise Failure('network_failed', 'HTTP request failed (network or TLS).', 'Check connectivity and system trust, then retry.') from None
        time.sleep(.25 * (attempt + 1))


def read_text(url, *, headers=None, cookies=None):
    try:
        with request(url, headers=headers, cookies=cookies) as response:
            return response.read().decode('utf-8-sig', errors='replace')
    except (OSError, http.client.HTTPException):
        raise Failure('network_failed', 'HTTP response could not be completely read.', 'Retry acquisition later.') from None


def read_json(url, *, headers=None, cookies=None):
    try:
        return json.loads(read_text(url, headers=headers, cookies=cookies))
    except ValueError:
        raise Failure('parse_failed', 'The platform returned unrecognized JSON.', 'Retry later; the platform response may have changed.') from None


def diagnostic(stage, failure):
    return {'stage': stage, 'code': failure.code, 'message': media.safe_message(failure),
            'next_action': failure.next_action}


def download_file(url, path, *, headers=None, cookies=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.part')
    try:
        with request(url, headers=headers, cookies=cookies) as response, tmp.open('xb') as handle:
            count = 0
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
                count += len(chunk)
            size = response.headers.get('Content-Length')
            if not count or (size and count != int(size)):
                raise Failure('download_incomplete', 'The resource download was empty or incomplete.', 'Retry acquisition.')
        tmp.replace(path)
        return path
    except (OSError, ValueError, http.client.HTTPException):
        raise Failure('download_failed', 'The resource could not be completely written.', 'Check disk space and retry.') from None
    finally:
        tmp.unlink(missing_ok=True)


def select_subtitle(candidates, language=None, original_language=None):
    candidates = [c for c in candidates if c.get('url') and not any(
        value in str(c.get('language', '')).lower() + str(c.get('kind', '')).lower()
        for value in ('danmaku', 'live_chat'))]
    if not candidates:
        return None
    target = language or original_language
    if target:
        exact = [c for c in candidates if c.get('language', '').lower() == target.lower()]
        candidates = exact or [c for c in candidates if c.get('language', '').lower().split('-')[0] == target.lower().split('-')[0]]
        if not candidates:
            raise Failure('subtitle_language_unavailable', f'No subtitle matches language {target}.', 'Choose another available language.')
    elif len({c.get('language') for c in candidates}) > 1:
        raise Failure('subtitle_ambiguous', 'Subtitle language is unknown and multiple languages are available.', 'Specify --language using an available subtitle language.')
    ranks = {'platform_manual': 0, 'platform_auto': 1, 'platform_unknown': 2}
    return min(candidates, key=lambda c: ranks.get(c.get('origin'), 2))


def fetch_subtitle(candidate, cookies=None):
    return read_text(candidate['url'], headers=candidate.get('headers'), cookies=cookies)


def select_formats(formats, *, want_video=True, quality='auto', width=768):
    if quality not in ('auto', '1080p', 'source'):
        raise Failure('invalid_quality', 'Quality must be auto, 1080p or source.')
    audio = [f for f in formats if f.get('has_audio') or f.get('has_audio') is None]
    if not want_video:
        if not audio:
            raise Failure('no_audio', 'No downloadable actual audio stream is available.')
        return [max(audio, key=lambda f: (not f.get('has_video'), f.get('bitrate') or 0))]
    videos = [f for f in formats if f.get('has_video')]
    if not videos:
        raise Failure('media_unavailable', 'No downloadable video stream is available.', 'Retry later or use a local media file.')
    def rank(f):
        # Bitrate is only a final tie-breaker; it is not a codec-independent
        # measure of visual quality.
        return ((f.get('width') or 0) * (f.get('height') or 0),
                f.get('fps') or 0, f.get('bitrate') or 0)
    if quality == 'source' or (quality == 'auto' and want_video != 'frames') or (want_video == 'frames' and width == 0):
        selected = max(videos, key=rank)
    elif want_video == 'frames' and quality == 'auto':
        suitable = [f for f in videos if (f.get('width') or 0) >= width]
        selected = min(suitable, key=rank) if suitable else max(videos, key=rank)
    else:
        suitable = [f for f in videos if min(f.get('width') or 0, f.get('height') or 0) <= 1080
                    and max(f.get('width') or 0, f.get('height') or 0) <= 1920]
        selected = max(suitable, key=rank) if suitable else min(videos, key=rank)
    result = [selected]
    if want_video != 'frames' and selected.get('has_audio') is False and audio:
        result.append(max(audio, key=lambda f: (not f.get('has_video'), f.get('bitrate') or 0)))
    return result


def download(resolved, directory, *, want_video=True, quality='auto', width=768, cookies=None):
    selected = select_formats(resolved['formats'], want_video=want_video, quality=quality, width=width)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    token = uuid.uuid4().hex[:12]
    try:
        for index, candidate in enumerate(selected):
            if candidate.get('protocol') == 'hls' or candidate.get('ext') == 'm3u8':
                from .generic import download_hls
                paths.append(download_hls(candidate, directory / f'{token}-{index}.mkv', cookies=cookies))
                continue
            if candidate.get('protocol') == 'dash' or candidate.get('ext') == 'mpd':
                raise Failure('format_unsupported', 'DASH streaming is not implemented.', 'Use another available format or local media.')
            ext = candidate.get('ext', 'bin')
            if ext not in ('mp4', 'm4a', 'webm', 'flv', 'mp3', 'mov', 'mkv', 'm4v', 'ogg', 'wav', 'bin'):
                ext = 'bin'
            paths.append(download_file(candidate['url'], directory / f'{token}-{index}.{ext}',
                                       headers=candidate.get('headers'), cookies=cookies))
        if len(paths) == 2:
            final = directory / f'{token}.mkv'
            paths.append(final)
            media.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                       '-i', paths[0], '-i', paths[1], '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy', final], timeout=600)
        else:
            final = paths[0]
        actual = media.probe(final)
        if want_video and not actual['video']:
            raise Failure('invalid_media', 'Downloaded media has no video stream.')
        if (not want_video or any(f.get('has_audio') for f in selected)) and not actual['audio']:
            raise Failure('invalid_media', 'Downloaded media is missing the expected audio stream.')
        expected = resolved.get('metadata', {}).get('duration')
        if expected and actual['duration'] < expected - max(2, expected * .03):
            raise Failure('download_incomplete', 'Downloaded media is shorter than the platform duration.', 'Retry or choose a different format.')
        for path in paths:
            if path != final:
                path.unlink(missing_ok=True)
        return final
    except BaseException:
        for path in paths:
            path.unlink(missing_ok=True)
        raise


def resolve(url, *, part=None, cookies=None, need=None):
    host = (urllib.parse.urlsplit(url).hostname or '').lower()
    if host in ('b23.tv', 'www.bilibili.com', 'bilibili.com', 'm.bilibili.com'):
        from . import bilibili
        return bilibili.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('www.youtube.com', 'youtube.com', 'm.youtube.com', 'youtu.be'):
        from . import youtube
        return youtube.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('v.qq.com', 'm.v.qq.com'):
        from . import tencent
        return tencent.resolve(url, part=part, cookies=cookies, need=need)
    if host.endswith('.tiktok.com') or host == 'tiktok.com':
        from . import tiktok
        return tiktok.resolve(url, part=part, cookies=cookies, need=need)
    if host.endswith('.douyin.com') or host == 'douyin.com':
        from . import douyin
        return douyin.resolve(url, part=part, cookies=cookies, need=need)
    from . import generic
    return generic.resolve(url, part=part, cookies=cookies, need=need)
