"""The current source and completed evidence; no history or global cache."""
from pathlib import Path
import json
import uuid


def artifact_path(directory, artifact, key='path'):
    value = Path(artifact[key])
    if value.is_absolute():
        raise ValueError('Artifact paths must be relative to the evidence directory.')
    if '..' in value.parts:
        raise ValueError('Artifact path traversal is not allowed.')
    path = (directory / value).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError('Artifact path escapes the evidence directory.')
    return path


def load(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Invalid evidence manifest.')
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ValueError('Unsupported evidence schema version.')
    if not isinstance(data.get('source'), dict) or not isinstance(data.get('artifacts'), list):
        raise ValueError('Invalid evidence manifest.')
    kept = []
    for artifact in data['artifacts']:
        primary = artifact_path(path.parent, artifact)
        readable = artifact_path(path.parent, artifact, 'readable_path') if artifact.get('readable_path') else None
        if primary.is_file() and (readable is None or readable.is_file()):
            kept.append(artifact)
    data['artifacts'] = kept
    return path, data


def add(data, directory, kind, path, **fields):
    path = Path(path).resolve()
    if not path.is_file() or not path.is_relative_to(directory.resolve()):
        raise ValueError('Completed artifact must exist inside the evidence directory.')
    artifact = {'id': kind + '-' + uuid.uuid4().hex[:10], 'type': kind,
                'path': str(path.relative_to(directory.resolve())), **fields}
    if artifact.get('readable_path') and not artifact_path(directory, artifact, 'readable_path').is_file():
        raise ValueError('Readable artifact must exist inside the evidence directory.')
    data['artifacts'].append(artifact)
    return artifact


def covers(artifact, start, end):
    span = artifact.get('source_range', {})
    return span.get('start', 0) <= start and (
        (end is None and span.get('end') is None) or
        (end is not None and span.get('end') is not None and span['end'] + 0.001 >= end)
    )
