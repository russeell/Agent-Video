"""西瓜视频 single-video SSR and platform share redirects.

SSR resource schema researched from yt-dlp ixigua.py at
51bab8a0116f4d8004c315706d809782607d5847 (Unlicense). Lux's MIT ixigua.go
was consulted for URL examples only; no code copied or adapted from Lux.
Native HTTP/media acquisition; challenges and authentication are not bypassed.
"""
import base64
import binascii
from datetime import datetime, timezone
import json
import hashlib
import re
from urllib.parse import urlsplit
from . import Failure, _Redirect, _opener, diagnostic, read_text, request


_HOSTS = ('ixigua.com', 'www.ixigua.com', 'm.ixigua.com', 'v.ixigua.com',
          'toutiao.com', 'www.toutiao.com', 'm.toutiao.com')


def _identity(url):
    try:
        p = urlsplit(url)
        if p.port not in (None, 80, 443):
            return None
    except ValueError:
        return None
    if p.scheme not in ('http', 'https') or p.username or p.password or p.hostname not in _HOSTS:
        return None
    if p.hostname in ('ixigua.com', 'www.ixigua.com', 'm.ixigua.com'):
        match = re.fullmatch(r'/(?:video/)?([0-9]{10,25})/?', p.path)
    elif p.hostname in ('toutiao.com', 'www.toutiao.com', 'm.toutiao.com'):
        match = re.fullmatch(r'/(?:video/|a)([0-9]{10,25})/?', p.path)
    else:
        match = None
    return match[1] if match else None


class _ShareRedirect(_Redirect):
    # Run before the shared HTTPRedirectHandler, otherwise it follows first.
    handler_order = 499

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            p = urlsplit(newurl)
            if p.port not in (None, 80, 443):
                raise ValueError
        except ValueError:
            raise Failure('invalid_url', 'Ixigua share returned an invalid platform address.') from None
        if p.scheme not in ('http', 'https') or p.hostname not in _HOSTS or p.username or p.password:
            raise Failure('invalid_url', 'Ixigua share redirected outside supported platform hosts.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _json_payload(text):
    # SSR uses JavaScript's undefined for absent fields. Replace that token
    # only outside JSON strings; do not rewrite user titles/descriptions.
    text = re.sub(r'^\s*window\._SSR_HYDRATED_DATA\s*=\s*', '', text).strip().rstrip(';')
    pieces = re.split(r'("(?:\\.|[^"\\])*")', text)
    for i in range(0, len(pieces), 2):
        pieces[i] = re.sub(r'\bundefined\b', 'null', pieces[i])
    return json.loads(''.join(pieces))


def _formats(resources):
    seen = set()
    for resource in resources.values() if isinstance(resources, dict) else []:
        if not isinstance(resource, dict):
            continue
        dynamic = resource.get('dynamic_video') if isinstance(resource.get('dynamic_video'), dict) else {}
        for entries, has_video, has_audio in ((resource.get('video_list'), True, None),
                (dynamic.get('dynamic_video_list'), True, False),
                (dynamic.get('dynamic_audio_list'), False, True)):
            for entry in entries.values() if isinstance(entries, dict) else entries or []:
                if not isinstance(entry, dict) or not entry.get('main_url'):
                    continue
                if entry.get('is_drm') or entry.get('encrypted'):
                    continue
                try:
                    address = base64.b64decode(entry['main_url'], validate=True).decode('utf-8')
                except (ValueError, binascii.Error, UnicodeError):
                    continue
                if urlsplit(address).scheme not in ('http', 'https') or address in seen:
                    continue
                seen.add(address)
                yield {'url': address, 'ext': 'mp4' if has_video else 'm4a',
                       'has_video': has_video, 'has_audio': has_audio,
                       'width': entry.get('vwidth'), 'height': entry.get('vheight'),
                       'fps': entry.get('fps'), 'bitrate': entry.get('bitrate'),
                       'filesize': entry.get('size'), 'format_id': entry.get('quality_type')}


def _mobile_address(value):
    """Undo the public mobile player's address envelope, never media encryption.

    Observed own-site 6512.f2038ad7.js (2026-10-05): CryptoJS passphrase
    AES/CBC, OpenSSL Salted__ envelope, then string reversal. The passphrase
    is a public player constant, not an account credential or a DRM key.
    """
    try:
        payload = base64.b64decode(value[::-1], validate=True)
        if not payload.startswith(b'Salted__') or len(payload) < 32 or (len(payload) - 16) % 16:
            raise ValueError
        salt = payload[8:16]
        derived, previous = b'', b''
        while len(derived) < 48:
            previous = hashlib.md5(previous + b'xigua.fe.web_mobile' + salt).digest()
            derived += previous
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.primitives.padding import PKCS7
        except ImportError:
            raise Failure('dependency_missing', 'Ixigua mobile address decoding needs cryptography.',
                          'Install the project dependencies, then retry.') from None
        decryptor = Cipher(algorithms.AES(derived[:32]), modes.CBC(derived[32:48])).decryptor()
        plaintext = decryptor.update(payload[16:]) + decryptor.finalize()
        unpadder = PKCS7(128).unpadder()
        address = (unpadder.update(plaintext) + unpadder.finalize()).decode('utf-8')
        parsed = urlsplit(address)
        if (parsed.port not in (None, 80, 443) or parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
                or not (parsed.hostname == 'ixigua.com' or parsed.hostname.endswith('.ixigua.com'))):
            raise ValueError
        return address
    except (TypeError, ValueError, UnicodeError, binascii.Error):
        raise Failure('parse_failed', 'Ixigua returned an unrecognized mobile resource address.') from None


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    try:
        p = urlsplit(url)
        if p.port not in (None, 80, 443):
            raise ValueError
    except ValueError:
        raise Failure('invalid_url', 'An Ixigua single-video URL with a standard HTTP(S) port is required.') from None
    if p.scheme not in ('http', 'https') or p.username or p.password or p.hostname not in _HOSTS:
        raise Failure('invalid_url', 'An Ixigua single-video or supported platform share URL is required.')
    identifier = _identity(url)
    share = (p.hostname == 'v.ixigua.com' and re.fullmatch(r'/[A-Za-z0-9_-]+/?', p.path)
             or p.hostname == 'm.toutiao.com' and re.fullmatch(r'/is/[A-Za-z0-9_-]+/?', p.path))
    if not identifier and share:
        opener = _opener(cookies)
        opener.add_handler(_ShareRedirect())
        with request(url, cookies=cookies, opener=opener) as response:
            identifier = _identity(response.geturl())
        if not identifier:
            raise Failure('invalid_url', 'Ixigua share did not resolve to a supported single video.')
    if not identifier:
        raise Failure('invalid_url', 'An Ixigua single-video or supported platform share URL is required.')
    canonical = 'https://www.ixigua.com/' + identifier
    page = read_text(canonical, cookies=cookies)
    embedded = re.search(r'<script\b[^>]*\bid=["\']SSR_HYDRATED_DATA["\'][^>]*>(.*?)</script>', page, re.S)
    mobile = re.search(r'window\._SSR_DATA\s*=\s*(.*?)</script>', page, re.S)
    if not embedded and not mobile and cookies is None:
        if __package__ == 'scripts.platforms':
            from ..browser import browser_page
        else:
            from browser import browser_page
        page = browser_page(canonical, ready=lambda text: bool(re.search(r'window\._SSR_DATA\s*=|SSR_HYDRATED_DATA', text)))
        embedded = re.search(r'<script\b[^>]*\bid=["\']SSR_HYDRATED_DATA["\'][^>]*>(.*?)</script>', page, re.S)
        mobile = re.search(r'window\._SSR_DATA\s*=\s*(.*?)</script>', page, re.S)
    if not embedded and not mobile:
        raise Failure('page_unavailable', 'Ixigua returned no readable video SSR data; the response may be a web challenge.',
                      'Retry later or provide an explicitly exported Cookie file or local media.')
    try:
        if embedded:
            data = _json_payload(embedded[1])['anyVideo']['gidInformation']
            video = data['packerData']['video']
        else:
            data = json.loads(mobile[1])['data']['storeState']['detail']
            original = data['videoData']['result']
            video = dict(original, video_abstract=original.get('abstract'),
                video_publish_time=original.get('publish_time'), video_watch_count=original.get('play_count'),
                user_info={'name': (original.get('media_user') or {}).get('screen_name')})
    except (TypeError, ValueError, KeyError):
        raise Failure('parse_failed', 'Ixigua returned unrecognized single-video SSR data.') from None
    actual = video.get('gid') or video.get('group_id') or data.get('gid')
    if not actual or str(actual) != identifier or not video.get('title'):
        raise Failure('parse_failed', 'Ixigua SSR does not confirm the requested video identity.')
    if video.get('is_live') or video.get('live_status'):
        raise Failure('live_unsupported', 'Ixigua live streams are unsupported.')
    result = {'source': {'platform': 'ixigua', 'id': identifier, 'url': canonical},
        'metadata': {'platform': 'ixigua', 'id': identifier, 'url': canonical,
                     'title': video['title'], 'description': video.get('video_abstract'),
                     'author': (video.get('user_info') or {}).get('name'), 'duration': video.get('duration'),
                     'published_at': video.get('video_publish_time'), 'view_count': video.get('video_watch_count'),
                     'like_count': video.get('video_like_count'), 'comment_count': video.get('comment_count'),
                     'original_language': None, 'audio_expected': None,
                     'collected_at': datetime.now(timezone.utc).isoformat()},
        'subtitles': [], 'formats': [], 'diagnostics': []}
    needs = set(need or ('info', 'transcript', 'video'))
    if 'transcript' in needs:
        result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_unavailable',
            'Ixigua SSR exposes no verified downloadable subtitle tracks.', 'Use local ASR.')))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        if video.get('is_drm') or video.get('is_pay') or video.get('is_paid'):
            result['diagnostics'].append(diagnostic('media', Failure('access_denied', 'Ixigua marks this video protected or paid.')))
        else:
            result['formats'] = list(_formats(video.get('videoResource')))
            if mobile and video.get('url'):
                try:
                    address = _mobile_address(video['url'])
                    definitions = video.get('definition') or []
                    size = re.fullmatch(r'(\d+)p', definitions[0]) if len(definitions) == 1 else None
                    result['formats'].append({'url': address, 'ext': 'mp4', 'has_video': True, 'has_audio': None,
                                              'height': int(size[1]) if size else None})
                except Failure as exc:
                    result['diagnostics'].append(diagnostic('media', exc))
            if any(f['has_audio'] is True for f in result['formats']):
                result['metadata']['audio_expected'] = True
            if not result['formats'] and not any(d['stage'] == 'media' for d in result['diagnostics']):
                result['diagnostics'].append(diagnostic('media', Failure('media_unavailable', 'Ixigua exposes no supported public media resources.')))
    return result
