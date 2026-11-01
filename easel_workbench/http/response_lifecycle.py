"""Release a lazy read response when no ASGI body consumer will run."""
import asyncio


async def close_read_response(response):
    iterator = getattr(response, 'body_iterator', None)
    if getattr(iterator, 'aclose', None):
        await iterator.aclose()
    elif getattr(iterator, 'close', None):
        await asyncio.to_thread(iterator.close)
    if response.background is not None:
        await response.background()
        response.background = None
