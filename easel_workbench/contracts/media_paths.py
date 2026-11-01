"""Pure route classification shared by native serving and download validation."""
import re

# Only these exact paths belong to authenticated host protocols. Ordinary output
# directories named images/accounts/jobs remain ordinary native media paths.
HOST_DISPLAY_IMAGE = re.compile(r'/api/media/images/([A-Za-z0-9_-]{1,128})/([a-f0-9]{64})/(original|thumb-256)')
HOST_MEDIA_JOB = re.compile(r'/api/media/jobs/([A-Za-z0-9_-]+)(/transcript)?')
HOST_ACCOUNT_QR = re.compile(r'/api/(?:platform-accounts|media/accounts)/([A-Za-z0-9_-]+)/qr')


def is_host_media_protocol(path):
    return path == '/api/media/accounts' or any(pattern.fullmatch(path) for pattern in (
        HOST_DISPLAY_IMAGE, HOST_MEDIA_JOB, HOST_ACCOUNT_QR))
