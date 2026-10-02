"""The current source and completed evidence; no history or global cache."""
from pathlib import Path
import json
import uuid


def artifact_path(directory, artifact, key='path'):
    value = Path(artifact[key])
    if value.is_absolute():
        if not artifact.get('external'):
            raise ValueError('Only external artifacts may use absolute paths.')
        return value
    path = (directory / value).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError('Artifact path escapes the evidence directory.')
    return path


def load(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data.get('source'), dict) or not isinstance(data.get('artifacts'), list):
        raise ValueError('Invalid evidence manifest.')
    kept = []
    for artifact in data['artifacts']:
        if artifact_path(path.parent, artifact).is_file() and (
            not artifact.get('readable_path') or artifact_path(path.parent, artifact, 'readable_path').is_file()
        ):
            kept.append(artifact)
    data['artifacts'] = kept
    return path, data


def add(data, directory, kind, path, **fields):
    path = Path(path).resolve()
    external = fields.get('external', False)
    if not path.is_file() or (not external and not path.is_relative_to(directory.resolve())):
        raise ValueError('Completed artifact must exist inside evidence, or be explicitly external.')
    artifact = {'id': kind + '-' + uuid.uuid4().hex[:10], 'type': kind,
                'path': str(path) if external else str(path.relative_to(directory.resolve())), **fields}
    data['artifacts'].append(artifact)
    return artifact


def covers(artifact, start, end):
    span = artifact.get('source_range', {})
    return span.get('start', 0) <= start and (
        (end is None and span.get('end') is None) or
        (end is not None and span.get('end') is not None and span['end'] + 0.001 >= end)
    )
