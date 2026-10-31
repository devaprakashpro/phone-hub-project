package com.phonehubmobile

import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.projection.MediaProjection
import android.os.Handler
import android.os.Looper
import android.view.Surface
import java.nio.ByteBuffer

/**
 * Screen capture via MediaProjection → H.264 (Annex-B) via MediaCodec. Each
 * access unit is handed to [sink] as `[flags][AU bytes]` (flags bit0 = key),
 * which the desktop reads on binary channel 0x02.
 */
class ScreenEncoder(
    private val projection: MediaProjection,
    private val width: Int,
    private val height: Int,
    private val dpi: Int,
    private val bitrate: Int,
    private val sink: (ByteArray) -> Unit,
) {
    private var codec: MediaCodec? = null
    private var surface: Surface? = null
    private var display: VirtualDisplay? = null
    @Volatile private var running = false
    private var drainThread: Thread? = null

    // Android 14+ requires a registered callback before createVirtualDisplay().
    private val projCallback = object : MediaProjection.Callback() {
        override fun onStop() { running = false }
    }

    fun start() {
        val fmt = MediaFormat.createVideoFormat("video/avc", width, height).apply {
            setInteger(MediaFormat.KEY_COLOR_FORMAT,
                MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
            setInteger(MediaFormat.KEY_BIT_RATE, bitrate)
            setInteger(MediaFormat.KEY_FRAME_RATE, 30)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 2)
        }
        codec = MediaCodec.createEncoderByType("video/avc").apply {
            configure(fmt, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            surface = createInputSurface()
            start()
        }
        projection.registerCallback(projCallback, Handler(Looper.getMainLooper()))
        display = projection.createVirtualDisplay(
            "phonehub", width, height, dpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            surface, null, null,
        )
        running = true
        drainThread = Thread { drain() }.also { it.start() }
    }

    // SPS/PPS, which MediaCodec emits exactly once. We cache it and re-prepend
    // it to every keyframe so a desktop that opens its decoder late (or
    // reconnects mid-stream) always has the parameter sets instead of being
    // stuck on a black frame.
    private var config: ByteArray? = null

    private fun drain() {
        val codec = codec ?: return
        val info = MediaCodec.BufferInfo()
        while (running) {
            val idx = codec.dequeueOutputBuffer(info, 10_000)
            if (idx < 0) continue
            val buf: ByteBuffer = codec.getOutputBuffer(idx) ?: continue
            buf.position(info.offset)
            buf.limit(info.offset + info.size)
            val au = ByteArray(info.size)
            buf.get(au)
            val isConfig = (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG) != 0
            val isKey = (info.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME) != 0
            if (isConfig) config = au
            // Prepend cached SPS/PPS to keyframes (MediaCodec sends config in its
            // own buffer, never inline with the IDR).
            val cfg = config
            val payload = if (isKey && !isConfig && cfg != null) cfg + au else au
            val out = ByteArray(payload.size + 1)
            out[0] = if (isKey || isConfig) 1 else 0
            System.arraycopy(payload, 0, out, 1, payload.size)
            sink(out)
            codec.releaseOutputBuffer(idx, false)
        }
    }

    fun stop() {
        running = false
        try { drainThread?.join(500) } catch (_: Exception) {}
        try { display?.release() } catch (_: Exception) {}
        try { codec?.stop(); codec?.release() } catch (_: Exception) {}
        try { surface?.release() } catch (_: Exception) {}
        try { projection.stop() } catch (_: Exception) {}
        codec = null; display = null; surface = null
    }
}
