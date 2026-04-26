"""
WebRTC signaling routes: /offer  and  /offer_view
"""

import json
import logging
import uuid

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRelay

from app_state import get_state
import db
from services.video_track import VideoTransformTrack
from services.audio_track import AudioTransformTrack

logger = logging.getLogger(__name__)

pcs   = set()
relay = MediaRelay()

# Module-level reference to the processed local video track (shared with /offer_view)
local_video = None


def setup_routes(app: web.Application):
    app.router.add_post("/offer", offer)
    app.router.add_post("/offer_view", offer_view)


# ── /offer – Presenter (camera user) ────────────────────────────────────────
async def offer(request: web.Request) -> web.Response:
    state = get_state(request)
    connections = state.connections
    globalvars = state.globalvars
    global local_video

    user_id = request.rel_url.query.get('token', '')
    logger.info("WebRTC offer received for user=%s", user_id)

    params = await request.json()
    sdp_offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc    = RTCPeerConnection()
    pc_id = f"PeerConnection({uuid.uuid4()})"
    pcs.add(pc)

    @pc.on("datachannel")
    def on_datachannel(channel):
        @channel.on("message")
        def on_message(message):
            if isinstance(message, str) and message.startswith("ping"):
                channel.send("pong" + message[4:])

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.info("%s connection state → %s", pc_id, pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    @pc.on("track")
    def on_track(track):
        global local_video
        logger.info("%s track received: %s", pc_id, track.kind)

        session_id = globalvars.get("insertedId")

        if track.kind == "video":
            local_video = VideoTransformTrack(
                relay.subscribe(track),
                transform=params.get("video_transform", ""),
                user_id=user_id,
                connections=connections,
                globalvars=globalvars,
                session_id=session_id,
            )
            pc.addTrack(local_video)

        elif track.kind == "audio":
            # Phase 3: route audio through PANNs (CNN14) classifier
            audio_track = AudioTransformTrack(
                relay.subscribe(track),
                user_id=user_id,
                connections=connections,
                globalvars=globalvars,
                session_id=session_id,
            )
            pc.addTrack(audio_track)
            logger.info("%s audio track attached to AudioTransformTrack", pc_id)

        @track.on("ended")
        async def on_ended():
            logger.info("%s track ended: %s", pc_id, track.kind)

    await pc.setRemoteDescription(sdp_offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps({"sdp": pc.localDescription.sdp,
                         "type": pc.localDescription.type}),
    )


# ── /offer_view – Passive viewer ─────────────────────────────────────────────
async def offer_view(request: web.Request) -> web.Response:
    global local_video

    logger.info("WebRTC offer_view received")
    params    = await request.json()
    sdp_offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc    = RTCPeerConnection()
    pc_id = f"PeerConnection({uuid.uuid4()})"
    pcs.add(pc)

    @pc.on("datachannel")
    def on_datachannel(channel):
        @channel.on("message")
        def on_message(message):
            if isinstance(message, str) and message.startswith("ping"):
                channel.send("pong" + message[4:])

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        logger.info("%s ICE state → %s", pc_id, pc.iceConnectionState)
        if pc.iceConnectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    await pc.setRemoteDescription(sdp_offer)
    for t in pc.getTransceivers():
        if t.kind == "video" and local_video:
            pc.addTrack(local_video)

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps({"sdp": pc.localDescription.sdp,
                         "type": pc.localDescription.type}),
    )


async def on_shutdown(app: web.Application):
    """Close all peer connections on server shutdown."""
    import asyncio
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()
    logger.info("All peer connections closed.")
