"""Small, project-owned single-video acquisition helpers.

Signed resource candidates are ephemeral and must never enter a manifest.
"""
from __future__ import annotations

import http.cookiejar
import http.client
import gzip
import json
from pathlib import Path
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib

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


def _cookie_jar(cookies=None):
    jar = http.cookiejar.MozillaCookieJar(policy=http.cookiejar.DefaultCookiePolicy(
        strict_ns_domain=http.cookiejar.DefaultCookiePolicy.DomainStrictNonDomain))
    if cookies:
        try:
            jar.load(str(cookies), ignore_discard=True, ignore_expires=False)
        except (OSError, http.cookiejar.LoadError):
            raise Failure('invalid_cookies', 'Cannot read the Netscape Cookie file.', 'Provide an explicitly exported Cookie file.') from None
    return jar


def _opener(cookies=None):
    context = ssl.create_default_context()
    try:
        import truststore
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        pass
    jar = _cookie_jar(cookies)
    return urllib.request.build_opener(_Redirect(), urllib.request.HTTPCookieProcessor(jar),
                                      urllib.request.HTTPSHandler(context=context))


def request(url, *, headers=None, cookies=None, attempts=3, data=None, opener=None):
    """Open HTTP, optionally letting a full-body download own its retries."""
    if urllib.parse.urlsplit(url).scheme not in ('http', 'https'):
        raise Failure('invalid_url', 'Only HTTP(S) resource addresses are supported.')
    supplied = {k: v for k, v in (headers or {}).items()
                if k.lower() not in ('cookie', 'authorization', 'proxy-authorization')}
    for attempt in range(attempts):
        try:
            return (opener or _opener(cookies)).open(urllib.request.Request(url, data=data, headers={'User-Agent': UA, **supplied}), timeout=30)
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code in (401, 403):
                raise Failure('access_denied', f'HTTP {exc.code}: platform access was denied.', 'Try an explicitly supplied Cookie file or retry later.') from None
            retryable = exc.code in (429, 500, 502, 503, 504)
            if not retryable or attempt == attempts - 1:
                failure = Failure('network_failed', f'HTTP request failed with status {exc.code}.', 'Retry acquisition later.')
                failure.retryable = retryable
                raise failure from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            if attempt == attempts - 1:
                raise Failure('network_failed', 'HTTP request failed (network or TLS).', 'Check connectivity and system trust, then retry.') from None
        time.sleep(.25 * (attempt + 1))


def response_text(response):
    """Decode text responses, including compression used by platform pages."""
    try:
        body = response.read()
        encoding = response.headers.get('Content-Encoding', '').lower().strip()
        if encoding == 'gzip':
            body = gzip.decompress(body)
        elif encoding == 'deflate':
            body = zlib.decompress(body)
        elif encoding not in ('', 'identity'):
            raise Failure('encoding_unsupported', 'The platform returned an unsupported HTTP content encoding.')
        return body.decode('utf-8-sig', errors='replace')
    except (gzip.BadGzipFile, EOFError, zlib.error):
        raise Failure('parse_failed', 'The platform returned an invalid compressed response.') from None
    except (OSError, http.client.HTTPException):
        raise Failure('network_failed', 'HTTP response could not be completely read.', 'Retry acquisition later.') from None


def read_text(url, *, headers=None, cookies=None, data=None, opener=None):
    with request(url, headers=headers, cookies=cookies, data=data, opener=opener) as response:
        return response_text(response)


def read_browser_text(url, *, headers=None, cookies=None):
    """Read a platform page that needs a browser-compatible HTTP/TLS client."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
        raise Failure('invalid_url', 'Only HTTP(S) page addresses without embedded credentials are supported.')
    from curl_cffi.requests import Session
    from curl_cffi.requests.exceptions import RequestException
    supplied = {k: v for k, v in (headers or {}).items()
                if k.lower() not in ('cookie', 'authorization', 'proxy-authorization')}
    try:
        with Session(impersonate='chrome', cookies=_cookie_jar(cookies)) as session:
            response = session.get(url, headers=supplied, timeout=30, max_redirects=5, stream=True)
            try:
                if response.status_code in (401, 403):
                    raise Failure('access_denied', f'HTTP {response.status_code}: platform access was denied.')
                if response.status_code >= 400:
                    raise Failure('network_failed', f'HTTP request failed with status {response.status_code}.')
                body = bytearray()
                for chunk in response.iter_content():
                    body.extend(chunk)
                    if len(body) > 2000000:
                        raise Failure('parse_failed', 'The platform page exceeds the static parsing limit.')
                return body.decode('utf-8-sig', errors='replace')
            finally:
                response.close()
    except RequestException:
        raise Failure('network_failed', 'Platform page request failed (network or TLS).',
                      'Check connectivity and system trust, then retry.') from None


def read_json(url, *, headers=None, cookies=None, data=None, opener=None):
    try:
        return json.loads(read_text(url, headers=headers, cookies=cookies, data=data, opener=opener))
    except ValueError:
        raise Failure('parse_failed', 'The platform returned unrecognized JSON.', 'Retry later; the platform response may have changed.') from None


def diagnostic(stage, failure):
    return {'stage': stage, 'code': failure.code, 'message': media.safe_message(failure),
            'next_action': failure.next_action}


def download_file(url, path, *, headers=None, cookies=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.part')
    requested = re.fullmatch(r'bytes=0-([0-9]+)', next(
        (value for name, value in (headers or {}).items() if name.lower() == 'range'), ''))
    expected_size = int(requested[1]) + 1 if requested else None
    try:
        for attempt in range(3):
            try:
                with request(url, headers=headers, cookies=cookies, attempts=1) as response, tmp.open('wb') as handle:
                    count = 0
                    while True:
                        try:
                            chunk = response.read(1024 * 1024)
                        except (OSError, http.client.HTTPException):
                            raise Failure('network_failed', 'HTTP response could not be completely read.', 'Retry acquisition later.') from None
                        if not chunk:
                            break
                        handle.write(chunk)
                        count += len(chunk)
                    size = response.headers.get('Content-Length')
                    if (not count or (size and count != int(size))
                            or expected_size is not None and count != expected_size):
                        raise Failure('download_incomplete', 'The resource download was empty or incomplete.', 'Retry acquisition.')
                tmp.replace(path)
                return path
            except Failure as exc:
                if (exc.code not in ('network_failed', 'download_incomplete')
                        or not getattr(exc, 'retryable', True) or attempt == 2):
                    raise
                time.sleep(.25 * (attempt + 1))
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
        languages = ', '.join(sorted({c.get('language') for c in candidates if c.get('language')}))
        raise Failure('subtitle_ambiguous', 'Original speech language is unknown; available subtitles: ' + languages + '.',
                      'Specify --language for the requested transcript; subtitle defaults may be translations.')
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
    complete_sizes = all(f.get('width') and f.get('height') for f in videos)
    def rank(f):
        # Bitrate is only a final tie-breaker; it is not a codec-independent
        # measure of visual quality. Some APIs expose only a resolution label;
        # compare those labels without inventing the missing width.
        resolution = ((f['width'] * f['height'], 0) if complete_sizes else
                      (f.get('height') or 0, f.get('width') or 0))
        return (resolution,
                f.get('fps') or 0, f.get('bitrate') or 0)
    if quality == 'source' or (quality == 'auto' and want_video != 'frames') or (want_video == 'frames' and width == 0):
        originals = [f for f in videos if f.get('is_original') is True]
        selected = max(originals or videos, key=rank)
    elif want_video == 'frames' and quality == 'auto':
        suitable = [f for f in videos if (f.get('width') or 0) >= width]
        selected = min(suitable, key=rank) if suitable else max(videos, key=rank)
    else:
        suitable = [f for f in videos if min(f.get('width') or 0, f.get('height') or 0) <= 1080
                    and max(f.get('width') or 0, f.get('height') or 0) <= 1920]
        selected = max(suitable, key=rank) if suitable else min(videos, key=rank)
    result = [selected]
    if want_video != 'frames' and selected.get('has_audio') is False:
        if selected.get('audio_group'):
            audio = [f for f in audio if f.get('audio_group') == selected['audio_group']]
            if not audio:
                raise Failure('audio_unavailable', 'The selected HLS video has no matching original audio rendition.')
        if audio:
            result.append(max(audio, key=lambda f: (not f.get('has_video'), f.get('bitrate') or 0)))
    return result


def download(resolved, directory, *, want_video=True, quality='auto', width=768, cookies=None, video_path=None):
    if not resolved['formats']:
        access_error = next((d for d in resolved.get('diagnostics', [])
                             if d.get('stage') == 'media' and d.get('code') == 'auth_required'), None)
        if access_error:
            raise Failure(access_error['code'], access_error['message'], access_error.get('next_action'))
    selected = select_formats(resolved['formats'], want_video=want_video, quality=quality, width=width)
    expected_audio = (want_video != 'frames' and resolved.get('metadata', {}).get('audio_expected') is True)
    if want_video != 'frames' and all(f.get('has_audio') is False for f in selected):
        audio_error = next((d for d in resolved.get('diagnostics', []) if d.get('stage') == 'media'
                            and d.get('code') in ('audio_unavailable', 'audio_ambiguous')), None)
        if audio_error:
            raise Failure(audio_error['code'], audio_error['message'], audio_error.get('next_action'))
        if expected_audio:
            raise Failure('no_audio', 'The video has an expected audio track, but no usable original audio stream was obtained.')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    owned = []
    reuse_video = (video_path is not None and len(selected) == 2
                   and selected[0].get('has_video') and selected[0].get('has_audio') is False
                   and selected[1].get('has_audio') and not selected[1].get('has_video')
                   and all(f.get('protocol') not in ('hls', 'dash')
                           and f.get('ext') not in ('m3u8', 'mpd') for f in selected))
    token = uuid.uuid4().hex[:12]
    try:
        for index, candidate in enumerate(selected):
            if index == 0 and reuse_video:
                paths.append(Path(video_path))
                continue
            if candidate.get('protocol') == 'hls' or candidate.get('ext') == 'm3u8':
                if __package__ == 'scripts.platforms':
                    from ..streams import download_hls
                else:
                    from streams import download_hls
                paths.append(download_hls(candidate, directory / f'{token}-{index}.mkv', cookies=cookies))
                owned.append(paths[-1])
                continue
            if candidate.get('protocol') == 'dash' or candidate.get('ext') == 'mpd':
                raise Failure('format_unsupported', 'DASH streaming is not implemented.', 'Use another available format or local media.')
            ext = candidate.get('ext', 'bin')
            if ext not in ('mp4', 'm4a', 'webm', 'flv', 'mp3', 'mov', 'mkv', 'm4v', 'ogg', 'wav', 'bin'):
                ext = 'bin'
            paths.append(download_file(candidate['url'], directory / f'{token}-{index}.{ext}',
                                       headers=candidate.get('headers'), cookies=cookies))
            owned.append(paths[-1])
        if len(paths) == 2:
            final = directory / f'{token}.mkv'
            paths.append(final)
            owned.append(final)
            media.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                       '-i', paths[0], '-i', paths[1], '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy', final], timeout=600)
        else:
            final = paths[0]
        actual = media.probe(final)
        if want_video and not actual['video']:
            raise Failure('invalid_media', 'Downloaded media has no video stream.')
        if (expected_audio or not want_video or any(f.get('has_audio') for f in selected)) and not actual['audio']:
            raise Failure('invalid_media', 'Downloaded media is missing the expected audio stream.')
        expected = resolved.get('metadata', {}).get('duration')
        if expected and actual['duration'] < expected - max(2, expected * .03):
            raise Failure('download_incomplete', f'Downloaded media is shorter than the platform duration ({actual["duration"]:g}s vs {expected:g}s).',
                          'Check playback access or another available format.')
        if expected and actual['duration'] > expected + max(2, expected * .03):
            raise Failure('media_mismatch', f'Downloaded media is longer than the platform duration ({actual["duration"]:g}s vs {expected:g}s).',
                          'Check work identity and playback access; do not reuse mismatched media.')
        for path in owned:
            if path != final:
                path.unlink(missing_ok=True)
        return final
    except BaseException:
        for path in owned:
            path.unlink(missing_ok=True)
        raise


def resolve(url, *, part=None, cookies=None, need=None):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise Failure('invalid_url', 'A platform video URL must use HTTP or HTTPS.')
    host = parsed.hostname.lower()
    if host in ('b23.tv', 'www.bilibili.com', 'bilibili.com', 'm.bilibili.com'):
        from . import bilibili
        return bilibili.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('www.youtube.com', 'youtube.com', 'm.youtube.com', 'youtu.be'):
        from . import youtube
        return youtube.resolve(url, part=part, cookies=cookies, need=need)
    if host.endswith('.tiktok.com') or host == 'tiktok.com':
        from . import tiktok
        return tiktok.resolve(url, part=part, cookies=cookies, need=need)
    if host.endswith('.douyin.com') or host in ('douyin.com', 'iesdouyin.com', 'www.iesdouyin.com'):
        from . import douyin
        return douyin.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com'):
        from . import twitter
        return twitter.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('reddit.com', 'www.reddit.com', 'old.reddit.com', 'new.reddit.com', 'm.reddit.com'):
        from . import reddit
        return reddit.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('instagram.com', 'www.instagram.com'):
        from . import instagram
        return instagram.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('xiaohongshu.com', 'www.xiaohongshu.com', 'xhslink.com', 'www.xhslink.com'):
        from . import xiaohongshu
        return xiaohongshu.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('kuaishou.com', 'www.kuaishou.com', 'www1.kuaishou.com', 'www2.kuaishou.com',
                'v.kuaishou.com', 'www.gifshow.com', 'v.m.chenzhongtech.com'):
        from . import kuaishou
        return kuaishou.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('vimeo.com', 'www.vimeo.com', 'player.vimeo.com'):
        from . import vimeo
        return vimeo.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('dailymotion.com', 'www.dailymotion.com', 'geo.dailymotion.com', 'dai.ly'):
        from . import dailymotion
        return dailymotion.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('ted.com', 'www.ted.com'):
        from . import ted
        return ted.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('twitch.tv', 'www.twitch.tv', 'm.twitch.tv', 'go.twitch.tv', 'clips.twitch.tv'):
        from . import twitch
        return twitch.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('weibo.com', 'www.weibo.com', 'm.weibo.cn', 'video.weibo.com'):
        from . import weibo
        return weibo.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('weixin.qq.com', 'channels.weixin.qq.com'):
        from . import wechat
        return wechat.resolve(url, part=part, cookies=cookies, need=need)
    if re.fullmatch(r'(?:(?:www|[a-z]{2})\.)?pornhub\.(?:com|net|org)', host):
        from . import pornhub
        return pornhub.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('loom.com', 'www.loom.com'):
        from . import loom
        return loom.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('drive.google.com', 'docs.google.com'):
        from . import googledrive
        return googledrive.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('linkedin.com', 'www.linkedin.com'):
        from . import linkedin
        return linkedin.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('streamable.com', 'www.streamable.com'):
        from . import streamable
        return streamable.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('bsky.app', 'www.bsky.app', 'main.bsky.dev'):
        from . import bluesky
        return bluesky.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('zhihu.com', 'www.zhihu.com'):
        from . import zhihu
        return zhihu.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('ixigua.com', 'www.ixigua.com', 'm.ixigua.com', 'v.ixigua.com',
                'toutiao.com', 'www.toutiao.com', 'm.toutiao.com'):
        from . import ixigua
        return ixigua.resolve(url, part=part, cookies=cookies, need=need)
    if any(host == site or host.endswith('.' + site) for site in ('cctv.com', 'cctv.cn', 'cntv.com', 'cntv.cn')):
        from . import cctv
        return cctv.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('91porn.com', 'www.91porn.com', 'up.91splt.app'):
        from . import porn91
        return porn91.resolve(url, part=part, cookies=cookies, need=need)
    if host in ('missav.ws', 'www.missav.ws', 'missav.com', 'www.missav.com'):
        from . import missav
        return missav.resolve(url, part=part, cookies=cookies, need=need)
    raise Failure('unsupported_source', 'This website is not supported by Agent Video.',
                  'Use a supported platform video URL or a local media file.')
